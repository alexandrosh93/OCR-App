"""ElevenLabs voice (e.g. the user's own cloned voice «Alex H») for the voiceover, in ONE take.

The whole script (hook + lines + CTA) goes to ElevenLabs in a single request, like pasting it on the site, so
tone and rhythm flow from line to line. The with-timestamps endpoint gives the time of every character; from
that we get the word timings and cut the take into one clip per line for the video timeline.

Key: in the cloud session the proxy injects it for api.elevenlabs.io (network secret
"ElevenLabs API key (kouponaki reels)"); elsewhere set ELEVENLABS_API_KEY.
Config: "tts_engine": "elevenlabs", "elevenlabs_voice": <voice id>, "elevenlabs_model", "elevenlabs_settings".
A take costs about one credit per character of the script (~550 for an «Ήξερες ότι;»); it is cached, so
re-renders with the same text cost nothing.
"""
import base64
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache')
WORD = re.compile(r"\w+(?:['’-]\w+)*['’]?")


def request(text, voice, model, settings, fmt='mp3_44100_128', tries=4):
    key = os.environ.get('ELEVENLABS_API_KEY', 'proxy-injected')       # the session proxy replaces the placeholder
    ca = os.environ.get('SSL_CERT_FILE') or next((p for p in ('/root/.ccr/ca-bundle.crt',) if os.path.exists(p)), None)
    body = {'text': text, 'model_id': model}
    if settings:
        body['voice_settings'] = settings
    url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format={fmt}'
    for attempt in range(tries):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                     headers={'xi-api-key': key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180, context=ssl.create_default_context(cafile=ca)) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise RuntimeError(f'ElevenLabs HTTP {e.code}: {e.read()[:300]!r}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        print('elevenlabs: retry', file=sys.stderr)
        time.sleep(5 * (attempt + 1))


def one_take(texts, voice, model='eleven_v4', settings=None, sr=48000):
    """-> [(float32 audio at sr, [[word, start, end], ...]), ...], one clip per text, cut from a single take."""
    full = ' '.join(t.strip() for t in texts)
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(json.dumps([voice, model, settings, full], ensure_ascii=False).encode()).hexdigest()[:16]
    js = os.path.join(CACHE, f'el_{key}.json')
    if not os.path.exists(js):
        d = request(full, voice, model, settings)
        json.dump({'audio': d['audio_base64'], 'alignment': d.get('alignment') or d.get('normalized_alignment')},
                  open(js, 'w'))
    d = json.load(open(js))
    mp3 = base64.b64decode(d['audio'])
    pcm = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', '-', '-f', 's16le', '-ac', '1', '-ar', str(sr), '-'],
                         input=mp3, capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    x *= 0.89 / max(np.abs(x).max(), 1e-3)                             # one level for the whole take
    al = d['alignment']
    chars, t0s, t1s = al['characters'], al['character_start_times_seconds'], al['character_end_times_seconds']
    if ''.join(chars) != full:                                         # map our text onto the returned characters
        print('elevenlabs: alignment text differs from the script, matching by position', file=sys.stderr)
    lines, pos = [], 0
    for t in texts:
        t = t.strip()
        ws = [[m.group(0), t0s[min(pos + m.start(), len(t0s) - 1)], t1s[min(pos + m.end() - 1, len(t1s) - 1)]]
              for m in WORD.finditer(t)]
        lines.append(ws)
        pos += len(t) + 1
    out = []
    for i, ws in enumerate(lines):
        a = max(0.0, ws[0][1] - 0.04)
        nxt = lines[i + 1][0][1] - 0.04 if i + 1 < len(lines) else len(x) / sr
        b = min(nxt, ws[-1][2] + (0.6 if i + 1 < len(lines) else 0.4))   # keep the natural pause after the line
        clip = x[int(a * sr):int(b * sr)].copy()
        f_in, f_out = int(0.01 * sr), int(0.06 * sr)
        clip[:f_in] *= np.linspace(0, 1, f_in)
        clip[-f_out:] *= np.linspace(1, 0, f_out)
        out.append((clip, [[w, s - a, e - a] for w, s, e in ws]))
    return out
