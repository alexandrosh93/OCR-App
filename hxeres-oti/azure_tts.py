"""Official Azure AI Speech TTS (REST API) with per-word timings for the captions.

The REST endpoint returns audio only. The websocket endpoint that also streams word boundaries cannot be
reached through the cloud session's proxy, so the timings are recovered here instead:

1. the line is synthesised normally (this is the audio that goes in the video);
2. the same voice reads the same words once more with a short pause after every word, so in that
   "reference" rendition each word's span is known exactly from the silences;
3. DTW over MFCC features (same voice, same words, so the match is tight) maps those spans onto the
   natural reading; a voice-activity check snaps each word's edges to where speech really starts/ends,
   and every comma / full stop of the text is put exactly on its pause in the audio.
Checked against the exact word boundaries of the edge-tts endpoint (same voice, same audio) on 21 lines:
mean error 20 ms, worst 0.1 s. The timings follow the edge-tts convention (word starts a little early,
which suits captions), so scene anchors tuned on the old voice keep their feel.

Key: in the cloud session the proxy injects it for <region>.tts.speech.microsoft.com (network secret
"Azure Speech key (kouponaki-tts)"); elsewhere set AZURE_SPEECH_KEY (and AZURE_SPEECH_REGION if not
northeurope).

    python3 azure_tts.py "Κείμενο προς ανάγνωση" out.wav     # quick test: prints the word timings
"""
import io
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import wave

import numpy as np

REGION = os.environ.get('AZURE_SPEECH_REGION', 'northeurope')
FMT = 'riff-48khz-16bit-mono-pcm'
WORD_GAP_MS = 150             # pause after every word in the reference rendition
GAP_KEEP = 3                  # frames of each such pause kept for the DTW
LEAD, LEAD_FIRST, END_PAD = 0.074, 0.118, 0.058   # match the edge-tts word-boundary convention
PUNCT = ',.;!?·:…\u037e'
HOP = 0.01                    # feature frame step (s)
SILENCE_DB = 40               # a frame is silence when it is this far below the loudest frame


def words_of(text):
    """Word tokens the way the captions use them (punctuation dropped, inner apostrophes/hyphens kept)."""
    return re.findall(r"\w+(?:['’-]\w+)*['’]?", text)


def _esc(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def ssml(body, voice, rate='+0%', pitch='+0Hz'):
    """SSML document; `body` must already be XML-escaped (it may contain <break/> tags)."""
    lang = '-'.join(voice.split('-')[:2])
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang}">'
            f'<voice name="{voice}"><prosody rate="{rate}" pitch="{pitch}">{body}</prosody></voice></speak>')


def synth(doc, region=REGION, fmt=FMT, tries=8):
    """POST an SSML document to the REST endpoint -> (float32 mono audio, sample rate)."""
    key = os.environ.get('AZURE_SPEECH_KEY', 'proxy-injected')       # the session proxy replaces the placeholder
    ca = os.environ.get('SSL_CERT_FILE') or next((p for p in ('/root/.ccr/ca-bundle.crt',) if os.path.exists(p)), None)
    ctx = ssl.create_default_context(cafile=ca)
    url = f'https://{region}.tts.speech.microsoft.com/cognitiveservices/v1'
    for attempt in range(tries):
        req = urllib.request.Request(url, data=doc.encode('utf-8'), method='POST', headers={
            'Content-Type': 'application/ssml+xml', 'X-Microsoft-OutputFormat': fmt,
            'Ocp-Apim-Subscription-Key': key, 'User-Agent': 'hxeres-oti'})
        try:
            with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
                data = r.read()
            with wave.open(io.BytesIO(data)) as w:
                x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
                return x, w.getframerate()
        except urllib.error.HTTPError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == tries - 1:
                raise RuntimeError(f'Azure TTS HTTP {e.code}: {e.read()[:300]!r}') from None
            wait = float(e.headers.get('Retry-After') or 0) or min(60.0, 5.0 * (attempt + 1))   # free tier: 20 req/min
        except (urllib.error.URLError, TimeoutError, ConnectionError, wave.Error) as e:
            if attempt == tries - 1:
                raise
            wait = 3.0 * (attempt + 1)
        print(f'azure tts: retry in {wait:.0f}s', file=sys.stderr)
        time.sleep(wait)


def speak(text, voice='el-GR-NestorasNeural', rate='+0%', pitch='+0Hz'):
    """Plain synthesis of a text (no word timings) -> (float32 audio, sample rate)."""
    return synth(ssml(_esc(text), voice, rate, pitch))


# ------------------------------------------------------------------ features
def _to16k(x, sr):
    q = int(round(sr / 16000))
    if q <= 1:
        return x.astype(np.float64)
    n = 8 * q * 2 + 1                                   # windowed-sinc low-pass, then keep every q-th sample
    t = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * (0.45 / q) * t) * np.hamming(n)
    return np.convolve(x.astype(np.float64), h / h.sum(), mode='same')[::q]


_FB = {}


def _mel_fb(nfft=512, sr=16000, n_mels=40, fmin=60.0, fmax=7600.0):
    if nfft not in _FB:
        mel = lambda f: 2595 * np.log10(1 + f / 700)
        hz = lambda m: 700 * (10 ** (m / 2595) - 1)
        bins = np.floor((nfft + 1) * hz(np.linspace(mel(fmin), mel(fmax), n_mels + 2)) / sr).astype(int)
        fb = np.zeros((n_mels, nfft // 2 + 1))
        for m in range(1, n_mels + 1):
            l, c, r = bins[m - 1], bins[m], bins[m + 1]
            fb[m - 1, l:c] = (np.arange(l, c) - l) / max(c - l, 1)
            fb[m - 1, c:r] = (r - np.arange(c, r)) / max(r - c, 1)
        _FB[nfft] = fb
    return _FB[nfft]


def features(x, sr):
    """-> (frame features: 13 MFCC + deltas + log energy, CMVN over speech frames; level in dB; speech mask)."""
    y = _to16k(x, sr)
    hop, win, nfft = 160, 400, 512
    y = np.pad(y, (0, max(0, win - len(y))))
    n = 1 + (len(y) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    raw = y[idx]
    db = 10 * np.log10(np.mean(raw ** 2, axis=1) + 1e-12)
    speech = db > db.max() - SILENCE_DB
    pre = np.concatenate([y[:1], y[1:] - 0.97 * y[:-1]])[idx] * np.hamming(win)
    logmel = np.log(np.abs(np.fft.rfft(pre, nfft)) ** 2 @ _mel_fb(nfft).T + 1e-10)
    N = logmel.shape[1]
    dct = np.cos(np.pi / N * (np.arange(N) + 0.5)[None, :] * np.arange(1, 14)[:, None])
    cep = logmel @ dct.T
    p = np.pad(cep, ((2, 2), (0, 0)), mode='edge')
    delta = (p[3:-1] - p[1:-3] + 2 * (p[4:] - p[:-4])) / 10
    f = np.hstack([cep, delta, db[:, None]])
    ref = f[speech] if speech.sum() > 5 else f
    return (f - ref.mean(0)) / (ref.std(0) + 1e-6), db, speech


def dtw_path(A, B):
    """Plain DTW (steps: diagonal, down, right) between frame sequences A (n x d) and B (m x d)."""
    C = np.sqrt(np.maximum(0.0, (A ** 2).sum(1)[:, None] + (B ** 2).sum(1)[None, :] - 2 * A @ B.T))
    n, m = C.shape
    D = np.empty((n, m))
    D[0] = np.cumsum(C[0])
    for i in range(1, n):
        best = D[i - 1].copy()                                  # from above
        best[1:] = np.minimum(best[1:], D[i - 1, :-1])          # or diagonal
        cs = np.cumsum(C[i])
        D[i] = cs + np.minimum.accumulate(C[i] + best - cs)     # or from the left (min-plus scan)
    i, j, path = n - 1, m - 1, [(n - 1, m - 1)]
    while i or j:
        if not i:
            j -= 1
        elif not j:
            i -= 1
        else:
            _, i, j = min((D[i - 1, j - 1], i - 1, j - 1), (D[i - 1, j], i - 1, j), (D[i, j - 1], i, j - 1))
        path.append((i, j))
    return path[::-1]


def _runs(mask, a, b):
    """[start, end) runs of True in mask[a:b]."""
    out, i = [], a
    while i < b:
        if mask[i]:
            j = i
            while j < b and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _punct_after(text, toks):
    """For each token: is it followed by punctuation in the text (where the voice pauses)?"""
    out, pos = [], 0
    for w in toks:
        j = text.find(w, pos)
        pos = j + len(w) if j >= 0 else pos
        rest = text[pos:pos + 3].lstrip("'’ ")
        out.append(bool(rest) and rest[0] in PUNCT)
    return out


def align(x, sr, ref, ref_sr, text, toks):
    """Word spans (s) in x, from the reference rendition with a pause after every word. None if it fails."""
    n = len(toks)
    Fa, _, sp_a = features(x, sr)
    Fr, _, sp_r = features(ref, ref_sr)
    on_r, on_a = np.where(sp_r)[0], np.where(sp_a)[0]
    if n < 2 or len(on_r) < 2 or len(on_a) < 2:
        return None
    first, last = on_r[0], on_r[-1] + 1
    gaps = [g for g in _runs(~sp_r, first, last) if g[1] - g[0] >= 0.6 * WORD_GAP_MS / 1000 / HOP]
    if len(gaps) < n - 1:
        return None
    gaps = sorted(sorted(gaps, key=lambda g: g[0] - g[1])[:n - 1])      # the n-1 longest, in order
    spans, s = [], first
    for a, b in gaps:
        spans.append((s, a))
        s = b
    spans.append((s, last))
    keep, pos = [], []                     # reference frames for the DTW: the words, pauses cut very short
    for w, (a, b) in enumerate(spans):
        pos.append((len(keep), len(keep) + b - a))
        keep += list(range(a, b))
        if w < len(gaps):
            tail = list(range(b, gaps[w][1]))
            keep += tail[:GAP_KEEP] + (tail[-GAP_KEEP:] if len(tail) > 2 * GAP_KEEP else [])
    a0, a1 = on_a[0], on_a[-1] + 1         # align only the speech part of the line
    path = dtw_path(Fa[a0:a1], Fr[keep])
    first_a, last_a = {}, {}
    for i, j in path:
        first_a.setdefault(j, i + a0)
        last_a[j] = i + a0
    out = []
    for a, b in pos:
        s, e = first_a[a], last_a[b - 1] + 1
        while s < e - 1 and not sp_a[s]:                         # snap to where speech really starts / ends
            s += 1
        while e - 1 > s and not sp_a[e - 1]:
            e -= 1
        out.append([s, e])
    pauses = [p for p in _runs(~sp_a, a0, a1) if p[1] - p[0] >= 8]
    for w, punct in enumerate(_punct_after(text, toks)[:-1], 1):    # punctuation = a pause: snap onto it
        if not punct or not pauses:
            continue
        b = out[w][0]
        dist = lambda p: 0 if p[0] <= b <= p[1] else min(abs(b - p[0]), abs(b - p[1]))
        p = min(pauses, key=dist)
        if dist(p) * HOP <= 0.35 and out[w - 1][0] < p[0] and p[1] < out[w][1] + 40:
            out[w - 1][1], out[w][0] = p[0], p[1]
            out[w][1] = max(out[w][1], out[w][0] + 4)
    for w in range(1, n):                                        # in order, never overlapping
        if out[w][0] < out[w - 1][1]:
            mid = (out[w][0] + out[w - 1][1]) // 2
            out[w - 1][1], out[w][0] = mid, mid
    return _to_seconds(out)


def _to_seconds(out):
    """Frame spans -> seconds, in the edge-tts convention: starts slightly early, a word ends where the next starts."""
    sec = [[max(0.0, s * HOP + 0.008 - (LEAD_FIRST if w == 0 else LEAD)), (e - 1) * HOP + 0.017]
           for w, (s, e) in enumerate(out)]
    for w in range(len(sec) - 1):
        sec[w][1] = max(sec[w][0] + 0.02, min(sec[w][1], sec[w + 1][0]))
    sec[-1][1] += END_PAD
    return sec


def estimate(x, sr, toks):
    """Fallback: share the speech span out by syllable count (rough)."""
    _, _, sp = features(x, sr)
    on = np.where(sp)[0]
    f0, f1 = (on[0], on[-1] + 1) if len(on) else (0, int(len(x) / sr / HOP))
    syl = [max(1, len(re.findall(r'[αεηιουωάέήίόύώϊϋΐΰ]+', w.lower()))) for w in toks]
    edges = np.round(f0 + (f1 - f0) * np.concatenate([[0], np.cumsum(syl)]) / sum(syl)).astype(int)
    return _to_seconds([[a, b] for a, b in zip(edges[:-1], edges[1:])])


def tts_words(text, voice='el-GR-NestorasNeural', rate='+0%', pitch='+0Hz'):
    """-> (float32 audio, sample rate, [[word, start, end], ...]) like edge-tts word boundaries."""
    toks = words_of(text)
    x, sr = synth(ssml(_esc(text), voice, rate, pitch))
    spans = None
    if len(toks) > 1:
        brk = f'<break time="{WORD_GAP_MS}ms"/>'
        ref, rsr = synth(ssml(brk.join(_esc(w) for w in toks), voice, rate, pitch))
        spans = align(x, sr, ref, rsr, text, toks)
    if spans is None and len(toks) > 1:
        print(f'azure tts: word alignment failed, estimating timings for: {text}', file=sys.stderr)
    if spans is None:
        spans = estimate(x, sr, toks)
    return x, sr, [[w, round(a, 3), round(b, 3)] for w, (a, b) in zip(toks, spans)]


if __name__ == '__main__':
    txt = sys.argv[1] if len(sys.argv) > 1 else 'Ήξερες ότι ο ΑΠΟΕΛ κλείνει εκατό χρόνια ιστορίας?'
    x, sr, ws = tts_words(txt, rate='+10%')
    if len(sys.argv) > 2:
        with wave.open(sys.argv[2], 'wb') as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f'{len(x) / sr:.2f}s @ {sr} Hz')
    for w in ws:
        print(f'{w[1]:6.2f} {w[2]:6.2f}  {w[0]}')
