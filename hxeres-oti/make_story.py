#!/usr/bin/env python3
"""'Ήξερες ότι;' story generator — a TikTok-native reel built from scratch from a real photo + a fact.

    python3 make_story.py configs/anorthosis_tiktok.json ../videos/anorthosis_tiktok.mp4
    python3 make_story.py configs/anorthosis_tiktok.json --preview 3,6,9,12 preview.png

TikTok conventions baked in:
  * hook first: the opening question is spoken over the intro (no silent branded intro)
  * word-by-word captions (current word lit up, optional emoji), like CapCut auto-captions
  * safe zones: nothing important under the top tabs, the right-hand like/comment/share column
    or the bottom caption/description area
  * fast scene cuts on the voice, comment call-to-action at the end, no fade-out (loops cleanly)

Scenes (one per VO line): date (flip-clock year), score (photo card + scoreboard that can go 3-0 → 3-1),
fact (crest on rays, headline words slam in, mascot, stamp, confetti), then the end card.
Timings: seconds after the line starts, or {"word": "πρώτη"} = when the voice says that word
("edge": "end" for the end of the word, "nth" for repeated words, "offset" to nudge).
"""
import sys, os, json, math, random, hashlib, subprocess, wave, ssl, asyncio, unicodedata, time
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont
from make_video import (HERE, CACHE, W, H, FPS, SR, T_INTRO, NAVY, INK, LIME, fnt, ease, ease_out, ease_out_back,
                        with_alpha, glow_of, place, vgrad, sticker_text, calendar_icon, Intro, band_noise, env_t,
                        sfx_pop, sfx_thud, sfx_whoosh, sfx_boom)

FLASH = (215, 255, 200)
YELLOW = (255, 222, 40)
# TikTok / Reels safe area on 1080x1920: below the top tabs, left of the button column, above the description
LOGO_Y = 175
STICKER_Y, STICKER_S = 305, 0.34
XC = 515              # content centre, nudged left of the like/comment/share column
TEXT_W = 800          # widest text block
CAP_Y = 1400          # captions band (inside the safe area, above the description)
EMOJI_FONT = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'


def norm(w):
    w = unicodedata.normalize('NFD', w.lower())
    return ''.join(c for c in w if not unicodedata.combining(c) and c.isalnum())


def caps(s):
    """Greek all-caps: uppercase without the tonos (keep the dialytika)."""
    s = unicodedata.normalize('NFD', s.upper())
    return unicodedata.normalize('NFC', ''.join(c for c in s if c != '́'))


# --------------------------------------------------------------------- voice
VOICE_FX = ('highpass=f=80,equalizer=f=180:t=q:w=1:g=-2,equalizer=f=3300:t=q:w=1.4:g=4,'
            'equalizer=f=8000:t=q:w=1:g=2,acompressor=threshold=-22dB:ratio=3.5:attack=4:release=80:makeup=5')


TTS_ENGINE = os.environ.get('HXERES_TTS', 'azure')     # 'azure' (official Azure AI Speech) or 'edge'


def tts_words(text, voice, rate, pitch='+0Hz', fx=True, engine=None):
    """Greek TTS + per-word timings. Returns (mono float audio at SR, [[word, start, end], ...]).
    engine 'azure' (default): the official Azure AI Speech REST API, word timings by alignment (azure_tts.py);
    'edge': the edge-tts read-aloud endpoint (same voices, exact word boundaries, unofficial)."""
    engine = engine or TTS_ENGINE
    os.makedirs(CACHE, exist_ok=True)
    tag = 'words' if engine == 'edge' else f'{engine}|words'          # edge keeps its old cache keys
    key = hashlib.sha1(f'{tag}|{voice}|{rate}|{pitch}|{fx}|{text}'.encode()).hexdigest()[:16]
    wav, js = os.path.join(CACHE, f'{key}.wav'), os.path.join(CACHE, f'{key}.json')
    if not (os.path.exists(wav) and os.path.exists(js)) and engine == 'azure':
        import azure_tts
        x, sr, words = azure_tts.tts_words(text, voice, rate, pitch)
        src = wav[:-4] + '.src.wav'
        with wave.open(src, 'wb') as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    elif not (os.path.exists(wav) and os.path.exists(js)):
        import edge_tts, edge_tts.communicate as c
        ca = os.environ.get('SSL_CERT_FILE') or ('/root/.ccr/ca-bundle.crt' if os.path.exists('/root/.ccr/ca-bundle.crt') else None)
        if ca:
            c._SSL_CTX = ssl.create_default_context(cafile=ca)

        async def run():
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary='WordBoundary')
            audio, words = bytearray(), []
            async for ch in comm.stream():
                if ch['type'] == 'audio':
                    audio += ch['data']
                elif ch['type'] == 'WordBoundary':
                    words.append([ch['text'], ch['offset'] / 1e7, (ch['offset'] + ch['duration']) / 1e7])
            return bytes(audio), words

        for attempt in range(6):                     # the free TTS endpoint fails now and then: retry
            try:
                audio, words = asyncio.run(run())
                if audio and words:
                    break
            except Exception as e:
                if attempt == 5:
                    raise
                print(f'tts retry ({e.__class__.__name__})', file=sys.stderr)
            time.sleep(2 * (attempt + 1))
        src = wav[:-4] + '.mp3'
        open(src, 'wb').write(audio)
    if not (os.path.exists(wav) and os.path.exists(js)):
        t0, t1 = max(0.0, words[0][1] - 0.04), words[-1][2] + 0.3
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-ss', f'{t0:.3f}', '-to', f'{t1:.3f}']
                       + (['-af', VOICE_FX] if fx else []) + ['-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le', wav], check=True)
        os.remove(src)
        json.dump([[w, a - t0, b - t0] for w, a, b in words], open(js, 'w', encoding='utf-8'), ensure_ascii=False)
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    n = len(x)
    x[:int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    x[n - int(0.08 * SR):] *= np.linspace(1, 0, int(0.08 * SR))
    return x / max(np.abs(x).max(), 1e-3) * 0.89, json.load(open(js, encoding='utf-8'))


def question_rise(audio, words, semitones=7.0, start=0.5, dip=-1.0, stretch=1.25):
    """Give a line a clear question ending on its last word (e.g. '...στη σειρά;').
    The TTS reads Greek questions almost flat and lets the last vowel go low and weak, so: a sensitive pitch
    analysis finds that vowel's pulses, then Praat PSOLA (keeps timbre) adds a slight dip and a smooth rise
    to `semitones` above the line's median, and draws the final syllable out a little (`stretch`)."""
    try:
        import parselmouth
        from parselmouth.praat import call
    except ImportError:
        print('question_rise: pip install praat-parselmouth to enable it', file=sys.stderr)
        return audio
    if not words:
        return audio
    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SR)
    # sensitive analysis: low floor and voicing threshold, so the soft final vowel still gets pulses
    pitch = call(snd, 'To Pitch (ac)', 0.005, 40, 15, 'no', 0.01, 0.2, 0.01, 0.35, 0.14, 400)
    pulses = call([snd, pitch], 'To PointProcess (cc)')
    man = call(snd, 'To Manipulation', 0.01, 40, 400)
    call([man, pulses], 'Replace pulses')
    pt = call(pitch, 'Down to PitchTier')
    n = call(pt, 'Get number of points')
    pts = [(call(pt, 'Get time from index', i), call(pt, 'Get value at index', i)) for i in range(1, n + 1)]
    w0, w1 = words[-1][1], words[-1][2]
    d0 = w0 + 0.15 * (w1 - w0)
    r0 = w0 + start * (w1 - w0)
    tail = [t for t, f in pts if r0 <= t <= w1 + 0.25]
    if not tail:
        print('question_rise: last word has no voiced end, skipped', file=sys.stderr)
        return audio
    r1 = max(tail)
    med = float(np.median([f for t, f in pts if t < w0] or [f for t, f in pts]))
    before = [f for t, f in pts if d0 <= t < r0]
    f_start = min(before[-1] if before else med, med) * 2 ** (dip / 12)
    f_end = med * 2 ** (semitones / 12)

    def target(t, f):
        if t < d0:
            return f
        if t < r0:
            return f * 2 ** (dip * ease((t - d0) / max(r0 - d0, 1e-3)) / 12)
        k = ease_out(min(1, (t - r0) / max(r1 - r0, 1e-3)), 1.6)
        return f_start * (f_end / f_start) ** k

    call(pt, 'Remove points between', d0 - 1e-3, len(audio) / SR + 1)
    for t, f in pts:
        if t >= d0 - 1e-3:
            call(pt, 'Add point', t, target(t, f))
    call([pt, man], 'Replace pitch tier')
    if stretch and stretch != 1:                          # draw the questioning syllable out a little
        dt = call(man, 'Extract duration tier')
        call(dt, 'Add point', r0 - 0.02, 1.0)
        call(dt, 'Add point', r0, stretch)
        call(dt, 'Add point', r1 + 0.04, stretch)
        call(dt, 'Add point', r1 + 0.06, 1.0)
        call([dt, man], 'Replace duration tier')
    y = call(man, 'Get resynthesis (overlap-add)').values[0].astype(np.float32)
    return y / max(np.abs(y).max(), 1e-3) * np.abs(audio).max()


def is_question(text):
    return text.rstrip().endswith((';', '?', '\u037e'))


def tighten(audio, words, max_pause=0.22, keep_after=0.14):
    """Shorten long pauses between words (TTS stops ~1s at every '!') so the read stays punchy."""
    cuts = []
    for (w0, a0, b0), (w1, a1, b1) in zip(words, words[1:]):
        c0, c1 = b0 + keep_after, a1 - (max_pause - keep_after)
        if c1 - c0 > 0.03:
            cuts.append((c0, c1))
    if not cuts:
        return audio, words
    parts, pos = [], 0
    f = int(0.004 * SR)
    for c0, c1 in cuts:
        i0, i1 = int(c0 * SR), int(c1 * SR)
        seg = audio[pos:i0].copy()
        if len(seg) > 2 * f:
            seg[-f:] *= np.linspace(1, 0, f)
            if pos:
                seg[:f] *= np.linspace(0, 1, f)
        parts.append(seg)
        pos = i1
    tail = audio[pos:].copy()
    tail[:f] *= np.linspace(0, 1, min(f, len(tail)))
    parts.append(tail)

    def shift(t):
        return t - sum(min(c1, max(t, c0)) - c0 for c0, c1 in cuts if t > c0)
    return np.concatenate(parts), [[w, shift(a), shift(b)] for w, a, b in words]


# ---------------------------------------------------------------- graphics
def fit_text(text, color, maxw, max_size, min_size=36, step=6):
    size = max_size
    while True:
        im = sticker_text(text, fnt('FiraSansExtraCondensed-Black', size), color,
                          stroke=int(max(6, size * 0.075)), depth=int(max(5, size * 0.055)))
        if im.width <= maxw or size <= min_size:
            return im
        size -= step


def plain_text(text, font, color=(255, 255, 255), stroke=0, stroke_col=INK):
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, t, r, b = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
    im = Image.new('RGBA', (r - l + 8, b - t + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4 - l, 4 - t), text, font=font, fill=color + (255,), stroke_width=stroke,
                            stroke_fill=stroke_col + (255,))
    return im


def hgrad(size, c0, c1):
    w, h = size
    t = np.linspace(0, 1, w)[None, :, None]
    g = np.array(c0)[None, None] * (1 - t) + np.array(c1)[None, None] * t
    return Image.fromarray(np.repeat(g, h, axis=0).astype(np.uint8), 'RGB')


def shade(c, k):
    return tuple(int(max(0, min(255, v * k))) for v in c)


_emoji = {}


def emoji_img(ch, size):
    if (ch, size) not in _emoji:
        im = Image.new('RGBA', (170 * max(1, len(ch)), 170), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((10, 10), ch, font=ImageFont.truetype(EMOJI_FONT, 109), embedded_color=True)
        im = im.crop(im.getbbox())
        _emoji[(ch, size)] = im.resize((max(1, int(im.width * size / im.height)), size), Image.LANCZOS)
    return _emoji[(ch, size)]


def bubble_icon(size, color=(6, 30, 16)):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((s * .06, s * .1, s * .94, s * .72), s * .2, fill=color + (255,))
    d.polygon([(s * .25, s * .66), (s * .48, s * .66), (s * .22, s * .92)], fill=color + (255,))
    for x in (.32, .5, .68):
        d.ellipse((s * x - s * .055, s * .41 - s * .055, s * x + s * .055, s * .41 + s * .055), fill=LIME + (255,))
    return im


# ---------------------------------------------------------------- odometer
def odometer_strip(font, w, h, color):
    """Digits 0..9,0 stacked vertically, one per w×h cell."""
    strip = Image.new('RGBA', (w, h * 11), (0, 0, 0, 0))
    d = ImageDraw.Draw(strip)
    for i in range(11):
        s = str(i % 10)
        l, t, r, b = d.textbbox((0, 0), s, font=font)
        d.text((w / 2 - (l + r) / 2, h * i + h / 2 - (t + b) / 2), s, font=font, fill=color + (255,))
    return strip


def tile_parts(w, h, border=LIME, radius=24):
    bg = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=(10, 24, 42, 250),
                        outline=(border + (255,)) if border else None, width=4 if border else 0)
    ov = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle((5, 5, w - 6, h // 2), max(4, radius - 6), fill=(255, 255, 255, 16))  # top-half sheen
    d.rectangle((6, h // 2 - 2, w - 7, h // 2 + 1), fill=(2, 6, 14, 230))                  # flip-clock split
    return bg, ov


def digit_tile(strip, bg, ov, v):
    h = bg.height
    y = int(round((v % 10) * h))
    tile = bg.copy()
    tile.alpha_composite(strip.crop((0, y, strip.width, y + h)))
    tile.alpha_composite(ov)
    m = Image.new('L', tile.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), 24, fill=255)
    tile.putalpha(ImageChops.multiply(tile.getchannel('A'), m))
    return tile


def roll(t, target, t0, t1, spins):
    """Odometer value: spins down onto `target` between t0 and t1."""
    span = 10 * spins + 5
    if t <= t0:
        return target + span
    return target + span * (1 - ease_out(min(1, (t - t0) / max(t1 - t0, 0.05)), 3))


def step_value(t, steps, spin=0.75):
    """Digit that spins onto steps[0] and then ticks forward to each later value at its time."""
    t0, v = steps[0]
    if t < t0 + spin:
        return roll(t, v, t0, t0 + spin, 1)
    for ta, vk in steps[1:]:
        if t < ta:
            return v
        delta = (vk - v) % 10
        p = (t - ta) / 0.35
        if delta and p < 1:
            return v + delta * ease_out(p, 3)
        v = vk
    return v


# --------------------------------------------------------------------- sfx
def sfx_tick(dur=0.02):
    t = env_t(dur)
    return band_noise(dur, 2500, 8000) * np.exp(-t * 300)


def sfx_confetti(dur=1.6):
    t = env_t(dur)
    rng = np.random.default_rng(5)
    out = band_noise(dur, 400, 9000) * np.exp(-t * 55) * 0.9 + sfx_thud(dur) * 0.5
    for _ in range(45):                               # crackle of falling paper
        st = int(rng.uniform(0.05, 1.4) * SR)
        click = band_noise(0.01, 3000, 10000) * np.exp(-env_t(0.01) * 500) * rng.uniform(0.05, 0.25) * (1 - st / (1.6 * SR))
        out[st:st + len(click)] += click[:len(out) - st]
    return out


# -------------------------------------------------------------------- story
class Story:
    def __init__(self, cfg_path):
        self.cfg = cfg = json.load(open(cfg_path, encoding='utf-8'))
        for k, v in self.CFG_DEFAULTS.items():        # template defaults (e.g. the voice of template 3)
            cfg.setdefault(k, v)
        self.load_voice()
        self.intro = Intro()
        self.team = cfg['team']
        self.tcol = tuple(self.team['color'])
        self.photo = Image.open(os.path.join(HERE, cfg['photo'])).convert('RGB')
        self.events, self.shakes, self.flashes = [], [], []
        self.timeline()
        self.build_backdrop()
        self._init_rest()

    def load_voice(self):
        """TTS for hook + lines + CTA with word timings, rising questions and optional pause tightening."""
        cfg = self.cfg
        voice = cfg.get('voice', 'el-GR-NestorasNeural')
        rate, pitch, fx = cfg.get('rate', '+18%'), cfg.get('pitch', '+10Hz'), cfg.get('voice_fx', True)
        lines = [cfg.get('hook', cfg.get('intro_line', 'Ήξερες ότι;'))] + cfg['lines'] + \
                [cfg.get('cta', 'Ακολούθησε το Κουπονάκι για περισσότερα!')]
        lines = [l if isinstance(l, dict) else {'text': l} for l in lines]      # a line may override rate / pitch
        for i, l in enumerate(lines):
            if is_question(l['text']):
                print(f'note: voice line {i} is a question ({l["text"][:45]}...): new videos keep questions out of '
                      'the voiceover (see CLAUDE.md)', file=sys.stderr)
        self.line_text = [l['text'] for l in lines]
        mp = cfg.get('max_pause', 0.22)               # null = keep the voice's natural pauses
        def tts_text(l):                              # the TTS only rises on '?', not on the Greek ';'
            t = l['text']
            return t.rstrip()[:-1] + '?' if l.get('question', is_question(t)) and t.rstrip()[-1:] in ';\u037e' else t
        engine = cfg.get('tts_engine')                # null = TTS_ENGINE (azure); "edge" = the old endpoint
        raw = None
        if engine == 'elevenlabs':                    # one take of the whole script (eleven_tts.py)
            import eleven_tts
            try:
                raw = eleven_tts.one_take([l['text'] for l in lines], cfg['elevenlabs_voice'],
                                          cfg.get('elevenlabs_model', 'eleven_v4'), cfg.get('elevenlabs_settings'), SR)
            except Exception as e:                    # e.g. credits used up: the video still comes out, with Azure
                print(f'WARNING: ElevenLabs failed ({str(e)[:160]}), falling back to Azure ({voice})', file=sys.stderr)
                engine = None
        if raw is None:
            raw = [tts_words(tts_text(l), l.get('voice', voice), l.get('rate', rate), l.get('pitch', pitch), fx, engine)
                   for l in lines]
        # questions get a real rising end (TTS reads them almost flat); "question": false turns it off
        qs = cfg.get('question_semitones', 6.0)
        def ask(a, w, l):
            y = question_rise(a, w, l.get('question_semitones', qs), start=l.get('question_start', 0.5),
                              stretch=l.get('question_stretch', 1.25))
            extra = (len(y) - len(a)) / SR
            return y, (w[:-1] + [[w[-1][0], w[-1][1], w[-1][2] + extra]] if w else w)
        raw = [ask(a, w, l) if l.get('question', is_question(l['text'])) else (a, w) for (a, w), l in zip(raw, lines)]
        self.vo = [tighten(*v, max_pause=mp) if mp else v for v in raw]

    def _init_rest(self):
        cfg = self.cfg
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((330, int(kl.height * 330 / kl.width)), Image.LANCZOS)
        self.k_big = kl.resize((760, int(kl.height * 760 / kl.width)), Image.LANCZOS)
        self.scenes = []
        for i, sc in enumerate(cfg['scenes']):
            line, T = i + 1, self.scene_t[i]
            self.scenes.append(dict(T=T, bd=self.bd_for(sc.get('backdrop')),
                                    draw=getattr(self, 'build_' + sc['type'])(sc, line, T)))
            if i:
                self.events.append((T - 0.2, 'whoosh'))
                self.flashes.append(T)
        self.events += [(self.t_intro - 0.15, 'whoosh'), (self.t_end - 0.1, 'whoosh'), (self.t_end + 0.2, 'boom_soft')]
        self.build_end_card()
        self.build_captions()
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.0), v=rnd.uniform(18, 60),
                           ph=rnd.uniform(0, 6.28)) for _ in range(60)]

    # ---------------------------------------------------------------- timing
    CFG_DEFAULTS = {}
    HOOK_START, INTRO_MIN = 0.6, T_INTRO      # voice start and minimum intro length (the sticker intro needs 2.6 s)

    def timeline(self):
        d = [len(a) / SR for a, _ in self.vo]
        starts = [self.cfg.get('hook_start', self.HOOK_START)]
        self.t_intro = max(self.INTRO_MIN, starts[0] + d[0] + 0.3)      # the intro lasts as long as the hook
        t = self.t_intro + 0.3
        for i in range(1, len(self.vo) - 1):
            starts.append(t)
            t += d[i] + self.cfg.get('line_gap', 0.4)
        t += self.cfg.get('hold', 0.6)
        self.t_end = t - 0.3
        starts.append(t)
        self.vo_starts = starts
        self.total = t + d[-1] + self.cfg.get('tail', 0.8)
        self.scene_t = [self.t_intro] + [starts[i] - 0.3 for i in range(2, len(self.vo) - 1)]

    def at(self, line, spec):
        if isinstance(spec, (int, float)):
            return self.vo_starts[line] + spec
        words = self.vo[line][1]
        target = norm(spec['word'])
        hits = [w for w in words if norm(w[0]) == target] or [w for w in words if norm(w[0]).startswith(target)]
        if not hits:
            raise ValueError(f"word {spec['word']!r} not found in line {line}: {[w[0] for w in words]}")
        w = hits[min(spec.get('nth', 0), len(hits) - 1)]
        return self.vo_starts[line] + (w[2] if spec.get('edge') == 'end' else w[1]) + spec.get('offset', 0)

    def add_ticks(self, fn, t0, t1):
        last, kept = None, []
        for tt in np.arange(t0, t1 + 0.001, 0.004):
            k = math.floor(fn(tt) + 0.5)
            if last is not None and k != last and (not kept or tt - kept[-1] > 0.035):
                kept.append(tt)
            last = k
        self.events += [(tt, 'tick') for tt in kept]

    # ---------------------------------------------------------------- backdrop
    def load_photo(self, path=None):
        """Extra real photos per scene (cached); None = the main photo."""
        if path is None:
            return self.photo
        cache = self.__dict__.setdefault('_photos', {})
        if path not in cache:
            cache[path] = Image.open(os.path.join(HERE, path)).convert('RGB')
        return cache[path]

    def bd_for(self, path=None):
        if path is None:
            return self.bd
        cache = self.__dict__.setdefault('_bds', {})
        if path not in cache:
            cache[path] = self.make_bd(self.load_photo(path))
        return cache[path]

    def make_bd(self, p):
        """Blurred, darkened, team-tinted cover of a photo (1.2x the frame, for slow drift)."""
        BW, BH = int(W * 1.2), int(H * 1.2)
        k = max(BW / p.width, BH / p.height)
        small = p.resize((max(1, int(p.width * k / 6)), max(1, int(p.height * k / 6))), Image.BILINEAR)
        big = small.filter(ImageFilter.GaussianBlur(7)).resize((int(p.width * k), int(p.height * k)), Image.BILINEAR)
        x0, y0 = (big.width - BW) // 2, (big.height - BH) // 2
        bd = big.crop((x0, y0, x0 + BW, y0 + BH))
        bd = Image.blend(bd, Image.new('RGB', bd.size, NAVY), 0.58)
        return Image.blend(bd, vgrad(bd.size, shade(self.tcol, 0.55), NAVY), 0.32)

    def scene_backdrop(self, t):
        """Backdrop of the current scene, cross-fading from the previous scene's photo."""
        i = 0
        for k, sc in enumerate(self.scenes):
            if sc['T'] <= t:
                i = k
        cur = self.scenes[i]
        fr = self.backdrop(t, cur['bd'])
        if i > 0 and t < cur['T'] + 0.4 and self.scenes[i - 1]['bd'] is not cur['bd']:
            fr = Image.blend(self.backdrop(t, self.scenes[i - 1]['bd']), fr, ease((t - cur['T']) / 0.4))
        return fr

    def build_backdrop(self):
        p = self.photo
        BW, BH = int(W * 1.2), int(H * 1.2)
        k = max(BW / p.width, BH / p.height)
        small = p.resize((max(1, int(p.width * k / 6)), max(1, int(p.height * k / 6))), Image.BILINEAR)
        big = small.filter(ImageFilter.GaussianBlur(7)).resize((int(p.width * k), int(p.height * k)), Image.BILINEAR)
        x0, y0 = (big.width - BW) // 2, (big.height - BH) // 2
        bd = big.crop((x0, y0, x0 + BW, y0 + BH))
        bd = Image.blend(bd, Image.new('RGB', bd.size, NAVY), 0.58)
        bd = Image.blend(bd, vgrad(bd.size, shade(self.tcol, 0.55), NAVY), 0.32)
        self.bd = bd
        yy, xx = np.mgrid[0:H, 0:W]
        dd = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.66)) ** 2)
        self.vig = Image.fromarray((np.clip((dd - 0.5) * 1.3, 0, 0.65) * 255).astype(np.uint8))
        b = Image.new('L', (W // 2, H // 2), 0)
        ImageDraw.Draw(b).polygon([(0, 0), (W // 2, H * 0.32), (W * 0.32, H // 2)], fill=110)
        self.beam = b.filter(ImageFilter.GaussianBlur(40))
        rnd = random.Random(21)
        light = tuple(min(255, int(c * 1.4 + 60)) for c in self.tcol)
        self.bokeh = []
        for _ in range(22):
            r = rnd.choice([26, 38, 54, 72])
            s = int(r * 2.8)
            m = Image.new('L', (s, s), 0)
            ImageDraw.Draw(m).ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=255)
            m = m.filter(ImageFilter.GaussianBlur(r * 0.3)).point(lambda v, a=rnd.uniform(0.07, 0.2): int(v * a))
            spr = Image.new('RGBA', (s, s), rnd.choice([LIME, (255, 255, 255), light]) + (0,))
            spr.putalpha(m)
            self.bokeh.append(dict(spr=spr, x=rnd.uniform(0, W), y=rnd.uniform(0, H), vx=rnd.uniform(-10, 10),
                                   vy=rnd.uniform(-38, -12)))

    def backdrop(self, t, bd=None):
        bd = self.bd if bd is None else bd
        z = 1 + 0.08 * ease(t / self.total)
        ww, wh = bd.width / z, bd.height / z
        cx = bd.width / 2 + (bd.width - ww) / 2 * math.sin(t * 0.3)
        cy = bd.height / 2
        fr = bd.resize((W, H), Image.BILINEAR, box=(cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)).convert('RGBA')
        for side in (0, 1):
            m = self.beam.rotate(8 * math.sin(t * 0.6 + side * 2.0), center=(0, 0), resample=Image.BILINEAR)
            if side:
                m = m.transpose(Image.FLIP_LEFT_RIGHT)
            m = m.resize((W, H), Image.BILINEAR).point(lambda v: int(v * 0.5 * (0.75 + 0.25 * math.sin(t * 1.7 + side))))
            lay = Image.new('RGBA', (W, H), (225, 255, 215, 0))
            lay.putalpha(m)
            fr = Image.alpha_composite(fr, lay)
        for b in self.bokeh:
            s = b['spr'].width
            x = (b['x'] + b['vx'] * t) % (W + s) - s / 2
            y = (b['y'] + b['vy'] * t) % (H + s) - s / 2
            place(fr, b['spr'], x, y)
        return fr

    def particles(self, fr, t, alpha=0.5):
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for p in self.parts:
            y = (p['y'] - p['v'] * t) % H
            x = p['x'] + 14 * math.sin(t * 0.8 + p['ph'])
            a = int(alpha * 255 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2.3 + p['ph']))))
            r = p['r']
            d.ellipse((x - r, y - r, x + r, y + r), fill=(150, 255, 100, a))
        return Image.alpha_composite(fr, lay)

    def shake(self, t):
        dx = dy = 0.0
        for te, amp in self.shakes:
            u = t - te
            if 0 < u < 0.45:
                k = amp * math.exp(-u * 11)
                dx += k * math.sin(u * 83)
                dy += k * math.cos(u * 67)
        return dx, dy

    # ---------------------------------------------------------------- captions
    FUNCTION_WORDS = {norm(w) for w in ('ο η το οι τα τον την της του των τους τις στο στη στην στον στα στους στις '
                                       'σε με από για και κι να θα που μια ένα ένας μιας ενός αν ή δεν μην έχει είχε έχουν είχαν').split()}

    def caption_tokens(self, li):
        """Words of one VO line as caption tokens; multi-word replacements merge ('δύο χιλιάδες οκτώ' -> '2008')."""
        base, src, words = self.vo_starts[li], self.line_text[li], self.vo[li][1]
        reps = sorted(((tuple(norm(x) for x in k.split()), v) for k, v in self.cfg.get('caption_replace', {}).items()),
                      key=lambda kv: -len(kv[0]))
        brk, pos = [], 0                  # does punctuation follow the word in the script?
        for w, a, b in words:
            j = src.find(w, pos)
            if j >= 0:
                pos = j + len(w)
            brk.append(j >= 0 and pos < len(src) and src[pos] in ',.;!?·:…')
        toks, i = [], 0
        while i < len(words):
            for key, val in reps:
                n = len(key)
                if tuple(norm(w[0]) for w in words[i:i + n]) == key:
                    toks.append(dict(text=val, t0=base + words[i][1], t1=base + words[i + n - 1][2],
                                     norms=list(key), brk=brk[i + n - 1], fw=False))
                    i += n
                    break
            else:
                w, a, b = words[i]
                shown = caps(w) if self.cfg.get('caption_case', 'upper') == 'upper' else w
                toks.append(dict(text=shown, t0=base + a, t1=base + b, norms=[norm(w)], brk=brk[i],
                                 fw=norm(w) in self.FUNCTION_WORDS))
                i += 1
        if toks and is_question(src):                     # show the question mark on screen too
            toks[-1]['text'] += ';'
        return toks

    @classmethod
    def chunk(cls, toks):
        """Split a phrase into 1-3 token captions: prefer 2-3 words, never end on an article/preposition."""
        n = len(toks)
        best = [0.0] + [1e9] * n
        back = [0] * (n + 1)
        for j in range(1, n + 1):
            for i in range(max(0, j - 4), j):
                part = toks[i:j]
                m = len(part)
                chars = sum(len(t['text']) for t in part) + m - 1
                c = 0.6 * (m - 2.4) ** 2 + 0.3 * max(0, chars - 16) + (10 if chars > 24 else 0) + (10 if m > 3 else 0)
                if m == 1 and chars < 6:
                    c += 1.5
                if part[-1]['fw'] and j < n:
                    c += 4
                if all(t['fw'] for t in part) and j < n:
                    c += 5
                if best[i] + c < best[j]:
                    best[j], back[j] = best[i] + c, i
        out, j = [], n
        while j > 0:
            out.append(toks[back[j]:j])
            j = back[j]
        return out[::-1]

    def build_captions(self):
        """CapCut-style captions: 1-3 words at a time, the word being spoken lit up in lime."""
        if not self.cfg.get('captions', True):
            self.captions = []
            return
        size = self.cfg.get('caption_size', 84)
        emo = {norm(k): v for k, v in self.cfg.get('emoji', {}).items()}
        chunks = []
        for li in range(len(self.vo)):
            phrase = []
            for tk in self.caption_tokens(li):
                phrase.append(tk)
                if tk['brk']:
                    chunks += self.chunk(phrase)
                    phrase = []
            if phrase:
                chunks += self.chunk(phrase)
        self.captions = []
        for ci, ch in enumerate(chunks):
            t0 = ch[0]['t0'] - 0.04
            nxt = chunks[ci + 1][0]['t0'] - 0.04 if ci + 1 < len(chunks) else 1e9
            emoji = next((emo[n] for tk in ch for n in tk['norms'] if n in emo), None)
            imgs = [self.caption_img([tk['text'] for tk in ch], k, size, emoji) for k in range(len(ch))]
            self.captions.append(dict(t0=t0, t1=min(nxt, ch[-1]['t1'] + 0.45), starts=[tk['t0'] for tk in ch], imgs=imgs))

    def caption_img(self, words, active, size, emoji):
        while True:
            f = fnt('FiraSansExtraCondensed-Black', size)
            fa = fnt('FiraSansExtraCondensed-Black', int(size * 1.12))
            st = max(5, int(size * 0.1))
            ims = [plain_text(w, fa if i == active else f, LIME if i == active else (255, 255, 255),
                              stroke=st, stroke_col=(0, 0, 0)) for i, w in enumerate(words)]
            if emoji:
                ims.append(emoji_img(emoji, int(size * 1.05)))
            gap = int(size * 0.22)
            tw = sum(im.width for im in ims) + gap * (len(ims) - 1)
            if tw <= TEXT_W or size <= 44:
                break
            size -= 4
        hh = max(im.height for im in ims)
        line = Image.new('RGBA', (tw + 40, hh + 40), (0, 0, 0, 0))
        x = 20
        for im in ims:
            line.alpha_composite(im, (x, 20 + (hh - im.height) // 2))
            x += im.width + gap
        sh = Image.new('RGBA', line.size, (0, 0, 0, 0))
        sh.putalpha(line.getchannel('A').filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.55)))
        out = Image.new('RGBA', (line.width, line.height + 8), (0, 0, 0, 0))
        out.alpha_composite(sh, (0, 8))
        out.alpha_composite(line, (0, 0))
        return out

    def draw_captions(self, fr, t):
        for c in self.captions:
            if c['t0'] <= t < c['t1']:
                k = 0
                for i, s in enumerate(c['starts']):
                    if t >= s - 0.03:
                        k = i
                u = t - c['t0']
                place(fr, c['imgs'][k], XC, getattr(self, 'cap_y', CAP_Y), 0.82 + 0.18 * ease_out_back(u / 0.14, 2.0),
                      min(1, u / 0.06))
                return

    # ---------------------------------------------------------------- scene: date
    def build_date(self, sc, line, T):
        tD = self.at(line, sc.get('day_at', 0.0))
        month = fit_text(sc['month'], 'yellow', TEXT_W - 260, 150) if sc.get('month') else None
        tM = self.at(line, sc.get('month_at', {'word': sc['month']})) if month is not None else None
        tY0, tY1 = self.at(line, sc['year_at']), self.at(line, sc['year_end'])
        day = fit_text(sc['day'], 'white', TEXT_W, sc.get('day_size', 360))
        dglow, _ = glow_of(day, 30, LIME)
        icon = calendar_icon(100)
        chars = sc['year']
        nd = sum(c.isdigit() for c in chars)
        gap = 16
        tw = int(min(150, (TEXT_W + 40 - gap * (len(chars) - 1)) / (nd + 0.45 * (len(chars) - nd))))
        th = int(tw * 4 / 3)
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', int(th * 0.85)), tw, th, LIME)
        bg, ov = tile_parts(tw, th)
        gf = fnt('FiraSansExtraCondensed-Black', int(th * 0.7))
        widths = [tw if c.isdigit() else int(tw * 0.45) for c in chars]
        x = XC - (sum(widths) + gap * (len(chars) - 1)) / 2
        items, di = [], 0
        for c, w in zip(chars, widths):
            if c.isdigit():
                items.append(dict(digit=True, target=int(c), t0=tY0 + 0.06 * di, t1=tY1 + 0.04 * di, spins=1 + di, cx=x + w / 2))
                di += 1
            else:                                         # static glyph between the tiles, e.g. the dash in 2005–06
                items.append(dict(digit=False, im=plain_text(c, gf, LIME), cx=x + w / 2))
            x += w + gap
        self.events += [(tD, 'thud'), (tY0 - 0.35, 'pop')] + ([(tM, 'pop')] if tM is not None else [])
        self.shakes.append((tD, 14))
        pcard = None                                       # optional polaroid, e.g. the founder's portrait
        if sc.get('photo'):
            pcard = self.photo_card(sc.get('photo_width', 300), sc.get('photo_max_h', 300), self.load_photo(sc['photo']))
            tPh = self.at(line, sc.get('photo_at', 0.0))
            pxy = (sc.get('photo_x', XC + 300), sc.get('photo_y', 600), sc.get('photo_rot', 6))
            self.events.append((tPh, 'whoosh'))
        for r in items:
            if r['digit']:
                self.add_ticks(lambda tt, r=r: roll(tt, r['target'], r['t0'], r['t1'], r['spins']), r['t0'], r['t1'])
        Yi, Yd, Ym = 450, 690, 935
        Yy = 1140 if month is not None else 950

        def draw(fr, t):
            if pcard is not None:
                self.draw_card(fr, pcard, t, tPh, pxy[0], pxy[1], rot_end=pxy[2])
            u = t - (tD - 0.25)
            if u > 0:
                place(fr, icon, XC, Yi, ease_out_back(u / 0.4, 2.0), min(1, u / 0.15))
            u = t - tD
            if u > 0:
                k = 1 + 0.55 * (1 - ease_out(u / 0.22, 3))
                place(fr, dglow, XC, Yd, k, 0.55 * min(1, u / 0.2))
                place(fr, day, XC, Yd, k, min(1, u / 0.1))
            if month is not None and t > tM:
                u = t - tM
                q = ease_out(u / 0.35)
                place(fr, month, XC, Ym + 40 * (1 - q), 1, min(1, u / 0.2))
                L = 100 * q
                if L > 2:
                    d = ImageDraw.Draw(fr)
                    half = month.width / 2 + 12
                    d.rounded_rectangle((XC - half - L, Ym - 5, XC - half, Ym + 5), 5, fill=LIME + (255,))
                    d.rounded_rectangle((XC + half, Ym - 5, XC + half + L, Ym + 5), 5, fill=LIME + (255,))
            u = t - (tY0 - 0.35)
            if u > 0:
                k = ease_out_back(u / 0.4, 1.8)
                for r in items:
                    im = digit_tile(strip, bg, ov, roll(t, r['target'], r['t0'], r['t1'], r['spins'])) if r['digit'] else r['im']
                    place(fr, im, r['cx'], Yy, k, min(1, u / 0.15))
        return draw

    # ---------------------------------------------------------------- scene: stats
    def stat_digits(self, value, t0, t1, strip, tbg, tov, dw, gap=6):
        """Multi-digit odometer number that lands on `value` between t0 and t1."""
        ds = str(value)
        rolls = [dict(target=int(c), t0=t0 + 0.06 * j, t1=t1 + 0.06 * j, spins=1 + j) for j, c in enumerate(ds)]

        def img(t):
            out = Image.new('RGBA', (len(ds) * dw + gap * (len(ds) - 1), tbg.height), (0, 0, 0, 0))
            for j, r in enumerate(rolls):
                out.alpha_composite(digit_tile(strip, tbg, tov, roll(t, r['target'], r['t0'], r['t1'], r['spins'])),
                                    (j * (dw + gap), 0))
            return out
        for r in rolls:
            self.add_ticks(lambda tt, r=r: roll(tt, r['target'], r['t0'], r['t1'], r['spins']), r['t0'], r['t1'])
        return img

    def pill_img(self, text, size=40):
        ptxt = plain_text(text, fnt('FiraSansExtraCondensed-Bold', size), (6, 30, 16))
        h = int(size * 1.55)
        pill = Image.new('RGBA', (ptxt.width + 50, h), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, h - 1), h // 2, fill=LIME + (255,))
        pill.alpha_composite(ptxt, (25, int(h / 2 - ptxt.height / 2)))
        return pill

    def build_stats(self, sc, line, T):
        """Photo card + a row of stat boxes whose numbers roll in on the spoken words (19 / 7 / 0)."""
        card = None if sc.get('no_card') else self.photo_card(sc.get('card_width', 980), sc.get('card_max_h', 520),
                                                              self.load_photo(sc.get('photo')))
        tP = T + 0.12
        pill = self.pill_img(sc['pill']) if sc.get('pill') else None
        tPl = self.at(line, sc.get('pill_at', 0.2)) if pill is not None else None
        items = sc['items']
        n, gap = len(items), 22
        bw, bh = int((TEXT_W - gap * (n - 1)) / n), 236
        dw = int(min(76, (bw - 46) / max(len(str(it['value'])) for it in items)))
        dh = int(dw * 1.45)
        cols = {'lime': LIME, 'yellow': YELLOW, 'white': (255, 255, 255)}
        strips = {}
        tbg, tov = tile_parts(dw, dh, border=None, radius=14)
        boxes = []
        x0 = XC - (n * bw + (n - 1) * gap) / 2 + bw / 2
        for i, it in enumerate(items):
            col = cols.get(it.get('color', 'lime'), LIME)
            if col not in strips:
                strips[col] = odometer_strip(fnt('FiraSansExtraCondensed-Black', int(dh * 0.86)), dw, dh, col)
            ta = self.at(line, it['at'])
            hero = it.get('hero', False)
            box = Image.new('RGBA', (bw + 60, bh + 60), (0, 0, 0, 0))
            if hero:
                gl = Image.new('RGBA', box.size, (0, 0, 0, 0))
                ImageDraw.Draw(gl).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 28, outline=LIME + (255,), width=14)
                box.alpha_composite(gl.filter(ImageFilter.GaussianBlur(12)))
            ImageDraw.Draw(box).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 28, fill=(8, 20, 36, 242),
                                                  outline=(LIME if hero else (70, 96, 124)) + (255,), width=5 if hero else 3)
            lab = plain_text(it['label'], fnt('FiraSansExtraCondensed-Bold', 38))
            box.alpha_composite(lab, (int(box.width / 2 - lab.width / 2), int(30 + bh - 22 - lab.height)))
            boxes.append(dict(box=box, t=ta, hero=hero, cx=x0 + i * (bw + gap),
                              num=self.stat_digits(it['value'], ta - 0.6, ta + 0.05, strips[col], tbg, tov, dw)))
            self.events.append((ta - 0.6, 'pop'))
            if hero:
                self.events.append((ta + 0.05, 'thud'))
                self.shakes.append((ta + 0.05, 12))
        self.events.append((tP, 'whoosh'))
        if tPl is not None:
            self.events.append((tPl, 'pop'))
        Yc, Ypill, Yb = 690, 1002, 1162

        def draw(fr, t):
            if card is not None:
                self.draw_card(fr, card, t, tP, XC, Yc)
            if tPl is not None and t > tPl:
                v = t - tPl
                place(fr, pill, XC, Ypill, 0.6 + 0.4 * ease_out_back(v / 0.35, 2.0), min(1, v / 0.12))
            for b in boxes:
                u = t - (b['t'] - 0.7)
                if u <= 0:
                    continue
                im = b['box'].copy()
                num = b['num'](t)
                im.alpha_composite(num, (int(im.width / 2 - num.width / 2), 30 + 22))
                k = 0.3 + 0.7 * ease_out_back(u / 0.4, 2.0)
                if b['hero'] and t > b['t']:
                    k *= 1 + 0.08 * (1 - ease_out((t - b['t']) / 0.35))
                place(fr, im, b['cx'], Yb, k, min(1, u / 0.12))
        return draw

    # ---------------------------------------------------------------- scene: table
    def build_table(self, sc, line, T):
        """Standings snippet (pos · crest · team · points) under a photo stack, with a '+1' style badge."""
        card = self.photo_card(sc.get('card_width', 980), sc.get('card_max_h', 520), self.load_photo(sc.get('photo')))
        card2 = self.photo_card(360, 240, self.load_photo(sc['photo2'])) if sc.get('photo2') else None
        tP = T + 0.12
        title = self.pill_img(sc['title'], 36) if sc.get('title') else None
        tT = self.at(line, sc.get('title_at', 0.3)) if title is not None else None
        tR = self.at(line, sc.get('rows_at', 0.4))
        rw, rh = TEXT_W + 20, 104
        dw, dh = 56, 80
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 70), dw, dh, LIME)
        tbg, tov = tile_parts(dw, dh, border=None, radius=12)
        rows = []
        for i, r in enumerate(sc['rows']):
            hl = r.get('highlight', False)
            col = tuple(r.get('color', self.tcol))
            base = Image.new('RGBA', (rw + 50, rh + 50), (0, 0, 0, 0))
            if hl:
                gl = Image.new('RGBA', base.size, (0, 0, 0, 0))
                ImageDraw.Draw(gl).rounded_rectangle((25, 25, 25 + rw, 25 + rh), 24, outline=LIME + (255,), width=12)
                base.alpha_composite(gl.filter(ImageFilter.GaussianBlur(10)))
            d = ImageDraw.Draw(base)
            d.rounded_rectangle((25, 25, 25 + rw, 25 + rh), 24, fill=(8, 20, 36, 244),
                                outline=(LIME if hl else (70, 96, 124)) + (255,), width=4 if hl else 3)
            d.rounded_rectangle((25, 25, 25 + 16, 25 + rh), 8, fill=col + (255,))          # team colour strip
            cx, cy = 25 + 66, 25 + rh / 2
            d.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=(LIME if hl else (60, 80, 104)) + (255,))
            pos = plain_text(str(r['pos']), fnt('FiraSansExtraCondensed-Black', 44), (6, 30, 16) if hl else (255, 255, 255))
            base.alpha_composite(pos, (int(cx - pos.width / 2), int(cy - pos.height / 2)))
            x = 25 + 112
            if r.get('crest'):
                c = Image.open(os.path.join(HERE, r['crest'])).convert('RGBA')
                c = c.resize((int(c.width * (rh - 22) / c.height), rh - 22), Image.LANCZOS)
                base.alpha_composite(c, (x, 25 + 11))
                x += c.width + 16
            name = plain_text(r['name'], fnt('FiraSansExtraCondensed-Black', 58), stroke=3)
            base.alpha_composite(name, (x, int(cy - name.height / 2)))
            tp = self.at(line, r['points_at'])
            rows.append(dict(base=base, hl=hl, t=tR + 0.15 * i, side=-1 if i % 2 == 0 else 1,
                             num=self.stat_digits(r['points'], tp - 0.6, tp + 0.05, strip, tbg, tov, dw)))
            self.events += [(tR + 0.15 * i, 'whoosh'), (tp + 0.05, 'pop')]
        badge = None
        if sc.get('badge'):
            b = sc['badge']
            bimg = fit_text(b['text'], b.get('color', 'yellow'), 420, b.get('max_size', 96))
            badge = dict(im=bimg, glow=glow_of(bimg, 16, LIME)[0], t=self.at(line, b['at']),
                         x=b.get('x', XC + 250), y=b.get('y', 1000), rot=b.get('rotate', 10))
            self.events.append((badge['t'], 'thud'))
            self.shakes.append((badge['t'], 12))
        self.events.append((tP, 'whoosh'))
        Yc, Yt, Yr = 690, 985, 1095

        def draw(fr, t):
            self.draw_card(fr, card, t, tP, XC, Yc)
            if card2 is not None:
                self.draw_card(fr, card2, t, tP + 0.35, XC + 250, Yc + 140, rot_end=7)
            if title is not None and t > tT:
                v = t - tT
                place(fr, title, XC, Yt, 0.6 + 0.4 * ease_out_back(v / 0.35, 2.0), min(1, v / 0.12))
            for i, r in enumerate(rows):
                u = t - r['t']
                if u <= 0:
                    continue
                im = r['base'].copy()
                num = r['num'](t)
                im.alpha_composite(num, (int(25 + rw - 24 - num.width), int(25 + (rh - num.height) / 2)))
                place(fr, im, XC + r['side'] * 700 * (1 - ease_out_back(u / 0.45, 1.3)), Yr + i * (rh + 16), 1,
                      min(1, u / 0.12))
            if badge is not None and t > badge['t']:
                u = t - badge['t']
                k = 1 + 1.2 * (1 - ease_out(u / 0.18, 3))
                place(fr, badge['glow'], badge['x'], badge['y'], k, 0.8 * min(1, u / 0.1), rot=badge['rot'])
                place(fr, badge['im'], badge['x'], badge['y'], k, min(1, u / 0.06), rot=badge['rot'])
        return draw

    # ---------------------------------------------------------------- scene: score
    def photo_card(self, width, max_h, src=None):
        src = self.photo if src is None else src
        b = 14
        h = int(min(width * src.height / src.width, max_h))
        frame = Image.new('RGBA', (width + 2 * b, h + 2 * b), (0, 0, 0, 0))
        ImageDraw.Draw(frame).rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), 30, fill=(246, 246, 240, 255))
        mask = Image.new('L', (width, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, h - 1), 22, fill=255)
        glow, _ = glow_of(frame, 22, LIME)
        return dict(src=src, frame=frame, mask=mask, glow=glow, b=b, w=width, h=h)

    def draw_card(self, fr, P, t, t0, cx, cy, rot_end=-2.5):
        u = t - t0
        if u <= 0:
            return
        src, w, h = P['src'], P['w'], P['h']
        z = 1 + 0.1 * ease(u / 5)
        cw = min(src.width, src.height * w / h) / z
        ch = cw * h / w
        x0 = (src.width - cw) / 2 + (src.width - cw) / 2 * 0.6 * math.sin(u * 0.35)
        y0 = (src.height - ch) / 2
        card = P['frame'].copy()
        card.paste(src.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)), (P['b'], P['b']), P['mask'])
        lv = (u - 0.3) / 0.75                                   # light-leak sweep across the photo
        if 0 < lv < 1:
            band = Image.new('L', card.size, 0)
            xx = -0.4 * card.width + 1.8 * card.width * ease(lv)
            ImageDraw.Draw(band).polygon([(xx, 0), (xx + 140, 0), (xx - 90, card.height), (xx - 230, card.height)], fill=130)
            band = ImageChops.multiply(band.filter(ImageFilter.GaussianBlur(28)), card.getchannel('A'))
            wl = Image.new('RGBA', card.size, (255, 252, 235, 0))
            wl.putalpha(band)
            card.alpha_composite(wl)
        e = ease_out_back(u / 0.55, 1.5)
        rot = rot_end - 9 * (1 - ease_out(u / 0.55))
        s = 0.55 + 0.45 * e
        dy = 5 * math.sin(t * 1.5)
        place(fr, P['glow'], cx, cy + dy, s, 0.75 * min(1, u / 0.3), rot=rot)
        place(fr, card, cx, cy + dy, s, min(1, u / 0.12), rot=rot)

    def plate(self, name, color, crest=None, pw=330, ph=118, skew=24, mirror=False):
        im = Image.new('RGBA', (pw, ph), (0, 0, 0, 0))
        m = Image.new('L', (pw, ph), 0)
        poly = [(skew, 0), (pw, 0), (pw - skew, ph), (0, ph)]
        ImageDraw.Draw(m).polygon(poly, fill=255)
        g = hgrad((pw, ph), shade(color, 1.25) if not mirror else shade(color, 0.7),
                  shade(color, 0.7) if not mirror else shade(color, 1.25)).convert('RGBA')
        g.putalpha(m)
        im.alpha_composite(g)
        ImageDraw.Draw(im).line(poly + [poly[0]], fill=(255, 255, 255, 120), width=3)
        x = skew + 20 if not mirror else skew + 44
        if crest is not None:
            c = crest.resize((int(crest.width * (ph - 24) / crest.height), ph - 24), Image.LANCZOS)
            im.alpha_composite(c, (x, 12))
            x += c.width + 12
        avail = pw - x - skew - (44 if not mirror else 20)
        lines = name.split('\n')
        size = 58 if len(lines) == 1 else 50
        while size > 28:
            parts = [plain_text(lines[0], fnt('FiraSansExtraCondensed-Black', size), stroke=3)]
            if len(lines) > 1:                       # second line smaller, e.g. ΟΛΥΜΠΙΑΚΟΣ / ΠΕΙΡΑΙΩΣ
                parts.append(plain_text(lines[1], fnt('FiraSansExtraCondensed-Bold', int(size * 0.62)), stroke=2))
            if max(pi.width for pi in parts) <= avail:
                break
            size -= 2
        txt = Image.new('RGBA', (max(pi.width for pi in parts), sum(pi.height for pi in parts) - 10 * (len(parts) - 1)),
                        (0, 0, 0, 0))
        yy = 0
        for pi in parts:
            txt.alpha_composite(pi, ((txt.width - pi.width) // 2, yy))
            yy += pi.height - 10
        tx = x if crest is not None else x + (avail - txt.width) / 2
        im.alpha_composite(txt, (int(tx), int(ph / 2 - txt.height / 2)))
        return im

    def build_score(self, sc, line, T):
        def crest_of(key, default):
            path = sc.get(key, default)
            return Image.open(os.path.join(HERE, path)).convert('RGBA') if path else None
        crest = crest_of('home_crest', self.team['crest'])            # left plate (home side)
        crest_away = crest_of('away_crest', None)                     # right plate, e.g. our team playing away
        card = self.photo_card(sc.get('card_width', 980), sc.get('card_max_h', 600), self.load_photo(sc.get('photo')))
        tP = T + 0.12
        tHo, tAw, tBox = self.at(line, sc['home_at']), self.at(line, sc['away_at']), self.at(line, sc['score_at'])
        card2 = self.photo_card(330, 220, self.load_photo(sc['photo2'])) if sc.get('photo2') else None   # polaroid
        tP2 = self.at(line, sc.get('photo2_at', 0.6)) if card2 is not None else None
        if tP2 is not None:
            self.events.append((tP2, 'whoosh'))
        badge = None
        if sc.get('badge'):                       # sticker on the photo, e.g. «2 ΑΠΟΚΡΟΥΣΕΙΣ!»
            bd_ = sc['badge']
            bimg = fit_text(bd_['text'], bd_.get('color', 'yellow'), 420, bd_.get('max_size', 90))
            badge = dict(im=bimg, glow=glow_of(bimg, 16, LIME)[0], t=self.at(line, bd_['at']),
                         x=bd_.get('x', XC + 250), y=bd_.get('y', 520), rot=bd_.get('rotate', 10))
            self.events.append((badge['t'], 'thud'))
            self.shakes.append((badge['t'], 12))
        if 'steps' in sc:
            steps = [dict(value=s['value'], t=self.at(line, s['at']), label=s.get('label', ''),
                          t_label=self.at(line, s.get('label_at', s['at']))) for s in sc['steps']]
        else:                                     # single final score (older configs)
            steps = [dict(value=sc['score'], t=self.at(line, sc['roll_at']), label=sc.get('label', 'ΣΥΝΟΛΙΚΟ ΣΚΟΡ'),
                          t_label=self.at(line, sc['roll_at']))]
        home = self.plate(sc['home'], tuple(sc.get('home_color', self.tcol)), crest)
        away = self.plate(sc['away'], tuple(sc.get('away_color', (90, 90, 100))), crest_away, mirror=True)
        bw, bh = 230, 160
        box = Image.new('RGBA', (bw + 60, bh + 60), (0, 0, 0, 0))
        gl = Image.new('RGBA', box.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, outline=LIME + (255,), width=12)
        box.alpha_composite(gl.filter(ImageFilter.GaussianBlur(11)))
        ImageDraw.Draw(box).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, fill=(8, 20, 36, 250), outline=LIME + (255,), width=5)
        dw, dh = 80, 118
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 110), dw, dh, LIME)
        tbg, tov = tile_parts(dw, dh, border=None, radius=16)
        dash = plain_text('–', fnt('FiraSansExtraCondensed-Black', 80))
        digit_steps = [[(s['t'], s['value'][k]) for s in steps] for k in (0, 1)]
        # "land_at": keep the digits spinning (slot-machine style) and land on that word
        spin = max(0.75, self.at(line, sc['land_at']) - steps[0]['t']) if sc.get('land_at') else 0.75
        for k in (0, 1):
            ds = digit_steps[k]
            self.add_ticks(lambda tt, ds=ds: step_value(tt, ds, spin), ds[0][0], ds[-1][0] + spin + 0.05)
        pills = []
        for s in steps:
            ptxt = plain_text(s['label'], fnt('FiraSansExtraCondensed-Bold', 36), (6, 30, 16))
            pill = Image.new('RGBA', (ptxt.width + 50, 56), (0, 0, 0, 0))
            ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, 55), 28, fill=LIME + (255,))
            pill.alpha_composite(ptxt, (25, int(28 - ptxt.height / 2)))
            pills.append((s['t_label'], pill))
        self.events += [(tP, 'whoosh'), (tHo, 'pop'), (tAw, 'pop'), (tBox, 'thud')]
        self.events += [(s['t_label'], 'pop') for s in steps[1:]]
        self.shakes.append((tBox, 8))
        Yc, Ys = 742, 1150
        xl, xr = XC - bw / 2 - home.width / 2 + 16, XC + bw / 2 + away.width / 2 - 16

        def draw(fr, t):
            self.draw_card(fr, card, t, tP, XC, Yc)
            if card2 is not None:
                self.draw_card(fr, card2, t, tP2, XC + 240, Yc + 170, rot_end=7)
            if badge is not None and t > badge['t']:
                u = t - badge['t']
                k = 1 + 1.2 * (1 - ease_out(u / 0.18, 3))
                place(fr, badge['glow'], badge['x'], badge['y'], k, 0.8 * min(1, u / 0.1), rot=badge['rot'])
                place(fr, badge['im'], badge['x'], badge['y'], k, min(1, u / 0.06), rot=badge['rot'])
            u = t - tHo
            if u > 0:
                place(fr, home, xl - 560 * (1 - ease_out_back(u / 0.5, 1.3)), Ys, 1, min(1, u / 0.15))
            u = t - tAw
            if u > 0:
                place(fr, away, xr + 560 * (1 - ease_out_back(u / 0.5, 1.3)), Ys, 1, min(1, u / 0.15))
            u = t - tBox
            if u > 0:
                b = box.copy()
                for k in (0, 1):
                    v = step_value(t, digit_steps[k], spin) if t > digit_steps[k][0][0] else digit_steps[k][0][1] + 15
                    tile = digit_tile(strip, tbg, tov, v)
                    b.alpha_composite(tile, (int(30 + 14 + k * (bw - 28 - dw)), int(30 + (bh - dh) / 2)))
                b.alpha_composite(dash, (int(box.width / 2 - dash.width / 2), int(box.height / 2 - dash.height / 2)))
                place(fr, b, XC, Ys, 0.3 + 0.7 * ease_out_back(u / 0.45, 2.0), min(1, u / 0.12))
                cur = [p for p in pills if t >= p[0]]
                if cur:
                    tl, pill = cur[-1]
                    v = t - tl
                    q = ease_out_back(v / 0.35, 2.0)
                    place(fr, pill, XC, Ys + 125, 0.6 + 0.4 * q, min(1, v / 0.15))
        return draw

    # ---------------------------------------------------------------- scene: trip
    def build_trip(self, sc, line, T):
        """Away trip: pins for the two cities, a dashed flight path drawing itself and a ✈️ flying along it."""
        A, B = sc['from'], sc['to']
        pA, pB = (XC - 255, 1120), (XC + 245, 660)
        pC = (XC - 300, 600)                                     # control point: the path bulges up-left
        t0, t1 = self.at(line, sc['fly_at']), self.at(line, sc['land_at'])
        plane = emoji_img('✈️', 140)
        pin = emoji_img('📍', 120)

        def label(city):
            txt = plain_text(city['name'], fnt('FiraSansExtraCondensed-Black', 64), stroke=3)
            fl = emoji_img(city['flag'], 58) if city.get('flag') else None
            w = txt.width + 52 + (fl.width + 14 if fl else 0)
            im = Image.new('RGBA', (w, 96), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle((0, 0, w - 1, 95), 26, fill=(8, 20, 36, 240), outline=LIME + (255,), width=4)
            x = 26
            if fl:
                im.alpha_composite(fl, (x, int(48 - fl.height / 2)))
                x += fl.width + 14
            im.alpha_composite(txt, (x, int(48 - txt.height / 2)))
            return im
        labA, labB = label(A), label(B)
        gA, gB = glow_of(labA, 14, LIME)[0], glow_of(labB, 14, LIME)[0]

        def bez(u):
            x = (1 - u) ** 2 * pA[0] + 2 * (1 - u) * u * pC[0] + u ** 2 * pB[0]
            y = (1 - u) ** 2 * pA[1] + 2 * (1 - u) * u * pC[1] + u ** 2 * pB[1]
            return x, y
        pill = self.pill_img(sc['pill'], 38) if sc.get('pill') else None
        tPl = self.at(line, sc.get('pill_at', 0.3)) if pill is not None else None
        stk = None
        if sc.get('sticker'):
            st = sc['sticker']
            simg = fit_text(st['text'], st.get('color', 'yellow'), st.get('max_w', 420), st.get('max_size', 100))
            stk = dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(line, st['at']),
                       x=st.get('x', XC + 120), y=st.get('y', 900), rot=st.get('rotate', -8))
            self.events.append((stk['t'], 'thud'))
            self.shakes.append((stk['t'], 12))
        self.events += [(T + 0.15, 'pop'), (t0, 'whoosh'), (t1, 'thud'), (t1 + 0.05, 'pop')]
        if tPl is not None:
            self.events.append((tPl, 'pop'))
        self.shakes.append((t1, 10))

        def draw(fr, t):
            if pill is not None and t > tPl:
                v = t - tPl
                place(fr, pill, XC, 470, 0.6 + 0.4 * ease_out_back(v / 0.35, 2.0), min(1, v / 0.12))
            u = t - (T + 0.15)
            if u > 0:                                           # origin pin + label
                k = ease_out_back(u / 0.4, 2.0)
                place(fr, pin, pA[0], pA[1] - 50, k, min(1, u / 0.1))
                place(fr, gA, pA[0], pA[1] + 70, k, 0.6)
                place(fr, labA, pA[0], pA[1] + 70, k, min(1, u / 0.1))
            q = 0.07 + 0.93 * ease(min(1, max(0, (t - t0) / max(t1 - t0, 0.3))))   # plane starts clear of the pin
            if t > t0:                                          # dashed path drawn up to the plane
                d = ImageDraw.Draw(fr)
                n = 60
                for i in range(n):
                    a0, a1 = i / n, (i + 0.55) / n
                    if a0 > q:
                        break
                    (x0, y0), (x1, y1) = bez(a0), bez(min(a1, q))
                    d.line((x0, y0, x1, y1), fill=(255, 255, 255, 230), width=7)
                if q < 1 or t - t1 < 0.25:
                    x, y = bez(q)
                    dx, dy = (lambda a, b: (b[0] - a[0], b[1] - a[1]))(bez(max(0, q - 0.02)), bez(min(1, q + 0.02)))
                    ang = math.degrees(math.atan2(-dy, dx))       # screen y points down
                    sc_ = 1 if q < 1 else 1 - (t - t1) / 0.25
                    place(fr, plane, x, y, sc_, min(1, (t - t0) / 0.1), rot=ang - 45)
            u = t - t1
            if u > 0:                                           # destination pin pops, ring pulses
                k = ease_out_back(u / 0.4, 2.2)
                r = 40 + 160 * ease_out((u % 1.2) / 1.2)
                lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                ImageDraw.Draw(lay).ellipse((pB[0] - r, pB[1] + 10 - r * 0.45, pB[0] + r, pB[1] + 10 + r * 0.45),
                                            outline=LIME + (int(220 * (1 - (u % 1.2) / 1.2)),), width=6)
                fr.alpha_composite(lay)
                place(fr, pin, pB[0], pB[1] - 50, k, min(1, u / 0.1))
                place(fr, gB, pB[0], pB[1] + 70, k, 0.6)
                place(fr, labB, pB[0], pB[1] + 70, k, min(1, u / 0.1))
            if stk is not None and t > stk['t']:
                v = t - stk['t']
                k = 1 + 1.3 * (1 - ease_out(v / 0.18, 3))
                place(fr, stk['glow'], stk['x'], stk['y'], k, 0.8 * min(1, v / 0.1), rot=stk['rot'])
                place(fr, stk['im'], stk['x'], stk['y'], k, min(1, v / 0.06), rot=stk['rot'])
        return draw

    # ---------------------------------------------------------------- scene: streak
    def build_streak(self, sc, line, T):
        """Season chips (🏆 1973–74 …) pop one after another on the voice while a big counter climbs 1→N."""
        seasons = sc['seasons']
        n = len(seasons)
        t0, t1 = self.at(line, sc['start_at']), self.at(line, sc['end_at'])
        times = [t0 + (t1 - t0) * i / max(n - 1, 1) for i in range(n)]
        dw, dh = 168, 226
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 196), dw, dh, LIME)
        tbg, tov = tile_parts(dw, dh)
        tglow, _ = glow_of(tbg, 22, LIME)
        pill = self.pill_img(sc.get('label', 'ΣΥΝΕΧΟΜΕΝΑ ΠΡΩΤΑΘΛΗΜΑΤΑ'), 40)
        cw, ch, gx, gy = 384, 108, 22, 18
        trophy = emoji_img('🏆', 70)
        f = fnt('FiraSansExtraCondensed-Black', 70)
        chips = []
        for i, lab in enumerate(seasons):
            chip = Image.new('RGBA', (cw + 40, ch + 40), (0, 0, 0, 0))
            d = ImageDraw.Draw(chip)
            d.rounded_rectangle((20, 20, 20 + cw, 20 + ch), 26, fill=(8, 20, 36, 244), outline=LIME + (255,), width=4)
            chip.alpha_composite(trophy, (20 + 22, int(20 + ch / 2 - trophy.height / 2)))
            txt = plain_text(lab, f, stroke=3)
            chip.alpha_composite(txt, (int(20 + 22 + trophy.width + 18), int(20 + ch / 2 - txt.height / 2)))
            r, c = divmod(i, 2)
            x = XC if (n % 2 and i == n - 1) else XC + (c - 0.5) * (cw + gx)      # odd count: centre the last chip
            chips.append(dict(img=chip, glow=glow_of(chip, 14, LIME)[0], t=times[i], x=x, y=815 + r * (ch + gy)))
            self.events += [(times[i], 'pop'), (times[i] + 0.02, 'tick')]
        self.events += [(T + 0.15, 'pop'), (times[-1], 'thud')]
        self.shakes.append((times[-1], 12))
        stk = None
        if sc.get('stamp'):
            st = sc['stamp']
            simg = fit_text(st['text'], st.get('color', 'yellow'), st.get('max_w', 460), st.get('max_size', 104))
            stk = dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(line, st['at']),
                       x=st.get('x', XC + 225), y=st.get('y', 445), rot=st.get('rotate', 10))
            self.events.append((stk['t'], 'thud'))
            self.shakes.append((stk['t'], 14))
        Yt, Yp = 525, 700

        def draw(fr, t):
            u = t - (T + 0.15)
            if u > 0:
                k = sum(1 for tt in times if t >= tt)
                v = float(k) if k == 0 else (k - 1) + ease_out(min(1, (t - times[k - 1]) / 0.2), 3)
                tile = digit_tile(strip, tbg, tov, v)
                sc_ = 0.3 + 0.7 * ease_out_back(u / 0.45, 1.8)
                if k and t - times[k - 1] < 0.25:          # little bump on every new title
                    sc_ *= 1 + 0.08 * (1 - (t - times[k - 1]) / 0.25)
                place(fr, tglow, XC, Yt, sc_, 0.35 + 0.5 * (k / n))
                place(fr, tile, XC, Yt, sc_, min(1, u / 0.12))
                place(fr, pill, XC, Yp, 0.6 + 0.4 * ease_out_back((u - 0.2) / 0.35, 2.0), min(1, max(0, u - 0.2) / 0.12))
            for c in chips:
                u = t - c['t']
                if u <= 0:
                    continue
                k = 0.3 + 0.7 * ease_out_back(u / 0.32, 2.4)
                if u < 0.5:
                    place(fr, c['glow'], c['x'], c['y'], k, 0.9 * (1 - u / 0.5))
                place(fr, c['img'], c['x'], c['y'], k, min(1, u / 0.08), rot=6 * math.sin(u * 14) * math.exp(-u * 6))
            if stk is not None and t > stk['t']:
                u = t - stk['t']
                k = 1 + 1.3 * (1 - ease_out(u / 0.18, 3))
                place(fr, stk['glow'], stk['x'], stk['y'], k, 0.8 * min(1, u / 0.1), rot=stk['rot'])
                place(fr, stk['im'], stk['x'], stk['y'], k, min(1, u / 0.06), rot=stk['rot'])
        return draw

    # ---------------------------------------------------------------- scene: gallery
    def build_gallery(self, sc, line, T):
        """Several real photos pop in one after another as a tilted stack, plus an optional sticker."""
        layout = [(-60, 660, -6), (60, 870, 5), (-30, 1075, -3), (50, 780, 4)]
        cards = []
        for i, it in enumerate(sc['photos']):
            card = self.photo_card(it.get('width', 820), it.get('max_h', 520), self.load_photo(it['photo']))
            dx, y, rot = layout[i % len(layout)]
            dx, y, rot = it.get('dx', dx), it.get('y', y), it.get('rot', rot)
            t0 = self.at(line, it['at'])
            cards.append(dict(card=card, t=t0, x=XC + dx, y=y, rot=rot))
            self.events += [(t0, 'whoosh'), (t0 + 0.2, 'pop')]
        stks = []                                          # 'sticker' (one) and/or 'stickers' (several)
        for st in ([sc['sticker']] if sc.get('sticker') else []) + sc.get('stickers', []):
            simg = fit_text(st['text'], st.get('color', 'yellow'), st.get('max_w', 520), st.get('max_size', 120))
            stks.append(dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(line, st['at']),
                             x=st.get('x', XC + 180), y=st.get('y', 470), rot=st.get('rotate', 8)))
            self.events.append((stks[-1]['t'], 'thud'))
            self.shakes.append((stks[-1]['t'], 12))

        def draw(fr, t):
            for c in cards:
                self.draw_card(fr, c['card'], t, c['t'], c['x'], c['y'], rot_end=c['rot'])
            for stk in stks:
                if t > stk['t']:
                    u = t - stk['t']
                    k = 1 + 1.3 * (1 - ease_out(u / 0.18, 3))
                    place(fr, stk['glow'], stk['x'], stk['y'], k, 0.8 * min(1, u / 0.1), rot=stk['rot'])
                    place(fr, stk['im'], stk['x'], stk['y'], k, min(1, u / 0.06), rot=stk['rot'])
        return draw

    # ---------------------------------------------------------------- scene: fact
    def build_fact(self, sc, line, T):
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        crest = crest.resize((int(crest.width * 250 / crest.height), 250), Image.LANCZOS)
        cglow, _ = glow_of(crest, 20, (150, 255, 110))
        tC = self.at(line, sc.get('crest_at', 0.0))
        R = 560
        rays = Image.new('L', (R, R), 0)
        dr = ImageDraw.Draw(rays)
        for i in range(16):
            a0 = i / 16 * 2 * math.pi
            dr.polygon([(R / 2, R / 2)] + [(R / 2 + R * math.cos(a), R / 2 + R * math.sin(a)) for a in (a0, a0 + math.pi / 16)],
                       fill=120 if i % 2 else 70)
        yy, xx = np.mgrid[0:R, 0:R]
        fall = np.clip(1 - np.hypot(xx - R / 2, yy - R / 2) / (R / 2), 0, 1) ** 1.2
        rays = Image.fromarray((np.asarray(rays.filter(ImageFilter.GaussianBlur(2))) * fall).astype(np.uint8))
        ray_col = tuple(min(255, int(c * 1.3 + 50)) for c in self.tcol)
        Yc = 560
        words, y = [], 712
        for i, wd in enumerate(sc['words']):
            im = fit_text(wd['text'], wd.get('color', 'white'), TEXT_W, wd.get('max_size', 150))
            tw = self.at(line, wd['at'])
            words.append(dict(im=im, t=tw, cy=y + im.height / 2))
            self.events.append((tw, 'thud'))
            self.shakes.append((tw, 16 if i == 0 else 6))
            y += im.height - 18
        mascot = None
        if self.team.get('mascot'):
            m = Image.open(os.path.join(HERE, self.team['mascot'])).convert('RGBA')
            mascot = m.resize((int(m.width * 280 / m.height), 280), Image.LANCZOS)
            tMa = self.at(line, sc.get('mascot_at', 0.5))
            self.events += [(tMa, 'whoosh'), (tMa + 0.35, 'pop')]
        stamp = None
        if sc.get('stamp'):
            st = sc['stamp']
            simg = fit_text(st['text'], st.get('color', 'yellow'), 400, st.get('max_size', 96))
            sg, _ = glow_of(simg, 18, LIME)
            stamp = dict(im=simg, glow=sg, t=self.at(line, st['at']), x=st.get('x', XC + 290), y=st.get('y', 640),
                         rot=st.get('rotate', 12))
            self.events.append((stamp['t'], 'thud'))
            self.shakes.append((stamp['t'], 12))
        tCf = self.at(line, sc['confetti_at']) if sc.get('confetti_at') else None
        if tCf is not None:
            self.events.append((tCf, 'confetti'))
        self.events += [(tC, 'whoosh'), (tC + 0.3, 'pop')]
        rnd = random.Random(9)
        light = tuple(min(255, int(c * 1.3 + 60)) for c in self.tcol)
        cols = [LIME, (255, 255, 255), YELLOW, light]
        conf = []
        for i in range(160):
            burst = i < 100
            ang = rnd.uniform(-math.pi * 0.92, -math.pi * 0.08)
            sp = rnd.uniform(800, 1700)
            conf.append(dict(burst=burst, x0=XC + rnd.uniform(-80, 80) if burst else rnd.uniform(0, W),
                             y0=words[min(2, len(words) - 1)]['cy'] if burst else rnd.uniform(-900, -40),
                             vx=math.cos(ang) * sp if burst else rnd.uniform(-40, 40),
                             vy=math.sin(ang) * sp if burst else rnd.uniform(120, 260),
                             d=rnd.uniform(0, 0.06) if burst else rnd.uniform(0, 0.4),
                             w=rnd.uniform(13, 24), h=rnd.uniform(7, 12), r0=rnd.uniform(0, 6.28),
                             rv=rnd.uniform(-7, 7), fv=rnd.uniform(5, 11), ph=rnd.uniform(0, 6.28), c=rnd.choice(cols)))

        def draw(fr, t):
            u = t - tC
            if u > 0:
                k = min(1, u / 0.5)
                rr = rays.rotate(t * 16, resample=Image.BILINEAR).resize((960, 960), Image.BILINEAR)
                lay = Image.new('RGBA', rr.size, ray_col + (0,))
                lay.putalpha(rr.point(lambda v: int(v * k)))
                place(fr, lay, XC, Yc, 0.6 + 0.4 * ease_out(u / 0.6))
                e = ease_out_back(u / 0.6, 1.6)
                im = crest
                sv = u - 0.8
                if 0 < sv < 0.6:
                    im = crest.copy()
                    band = Image.new('L', im.size, 0)
                    xx = -im.width * 0.6 + im.width * 2.2 * ease(sv / 0.6)
                    ImageDraw.Draw(band).polygon([(xx, 0), (xx + 70, 0), (xx - 90, im.height), (xx - 160, im.height)], fill=160)
                    band = ImageChops.multiply(band.filter(ImageFilter.GaussianBlur(14)), im.getchannel('A'))
                    wl = Image.new('RGBA', im.size, (255, 255, 255, 0))
                    wl.putalpha(band)
                    im.alpha_composite(wl)
                fl = 7 * math.sin(2 * math.pi * 0.5 * u)
                place(fr, cglow, XC, Yc + fl, max(e, 0.15), 0.7 * min(1, u / 0.3))
                place(fr, im, XC, Yc + fl, max(e, 0.15), min(1, u / 0.15), rot=30 * (1 - ease_out(u / 0.6)))
            if tCf is not None and t > tCf:               # confetti behind the words
                d = ImageDraw.Draw(fr)
                for p in conf:
                    tt = t - tCf - p['d']
                    if tt <= 0:
                        continue
                    if p['burst']:
                        kk = 2.4
                        x = p['x0'] + p['vx'] * (1 - math.exp(-kk * tt)) / kk
                        y = p['y0'] + p['vy'] * (1 - math.exp(-kk * tt)) / kk + 0.5 * 520 * tt * tt
                    else:
                        x = p['x0'] + p['vx'] * tt
                        y = p['y0'] + p['vy'] * tt + 0.5 * 160 * tt * tt
                    x += 22 * math.sin(tt * 3 + p['ph'])
                    if y > H + 40 or y < -60:
                        continue
                    a = p['r0'] + p['rv'] * tt
                    f = abs(math.cos(p['fv'] * tt + p['ph']))
                    hw, hh = p['w'] / 2, p['h'] / 2 * (0.25 + 0.75 * f)
                    ca, sa = math.cos(a), math.sin(a)
                    pts = [(x + ca * dx - sa * dy, y + sa * dx + ca * dy) for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
                    d.polygon(pts, fill=shade(p['c'], 0.55 + 0.45 * f) + (255,))
            for wd in words:
                u = t - wd['t']
                if u > 0:
                    s = 1 + 0.65 * (1 - ease_out(u / 0.2, 3))
                    place(fr, wd['im'], XC, wd['cy'], s, min(1, u / 0.08))
            if stamp is not None and t > stamp['t']:
                u = t - stamp['t']
                sc_ = 1 + 1.4 * (1 - ease_out(u / 0.18, 3))
                place(fr, stamp['glow'], stamp['x'], stamp['y'], sc_, 0.8 * min(1, u / 0.1), rot=stamp['rot'])
                place(fr, stamp['im'], stamp['x'], stamp['y'], sc_, min(1, u / 0.06), rot=stamp['rot'])
            if mascot is not None and t > tMa:
                u = t - tMa
                e = ease_out_back(u / 0.55, 1.5)
                place(fr, mascot, XC - 330 - 420 * (1 - e), Yc + 40 + 260 * (1 - e) + 10 * math.sin(2 * math.pi * 1.1 * u),
                      1, min(1, u / 0.2), rot=-16 * (1 - e) + 3 * math.sin(3.4 * u))
        return draw

    # ---------------------------------------------------------------- end card / frame
    def build_end_card(self):
        txt = plain_text(self.cfg.get('cta_badge', "ΓΡΑΨ' ΤΟ ΣΤΑ ΣΧΟΛΙΑ"), fnt('FiraSansExtraCondensed-Black', 50), (6, 30, 16))
        ic = bubble_icon(58)
        em = emoji_img('👇', 56)
        bw = 30 + ic.width + 14 + txt.width + 14 + em.width + 30
        badge = Image.new('RGBA', (bw, 86), (0, 0, 0, 0))
        ImageDraw.Draw(badge).rounded_rectangle((0, 0, bw - 1, 85), 43, fill=LIME + (255,))
        x = 30
        for im in (ic, txt, em):
            badge.alpha_composite(im, (x, int(43 - im.height / 2)))
            x += im.width + 14
        self.badge = badge
        self.badge_glow, _ = glow_of(badge, 20, LIME)

    def end_card(self, fr, t):
        k = ease((t - self.t_end) / 0.5)
        if k <= 0:
            return fr
        fr = Image.alpha_composite(fr, Image.new('RGBA', fr.size, (3, 10, 22, int(215 * k))))
        p = ease_out_back((t - self.t_end - 0.05) / 0.55)
        if p > 0.02:
            fr = self.intro.draw_sticker(fr, 0, W / 2, 560, 0.62 * p, glow=k)
        p = ease_out_back((t - self.t_end - 0.25) / 0.55)
        if p > 0.02:
            g, _ = glow_of(self.k_big, 26, (70, 220, 50))
            place(fr, g, XC, 885, p, 0.55 * k)
            place(fr, self.k_big, XC, 885, p, 1)
        p = ease_out_back((t - self.t_end - 0.55) / 0.5, 2.0)
        if p > 0.02:
            pulse = 1 + 0.035 * math.sin(2 * math.pi * 1.6 * (t - self.t_end))
            place(fr, self.badge_glow, XC, 1035, p * pulse, 0.6)
            place(fr, self.badge, XC, 1035, p * pulse, 1)
        return fr

    def intro_zoom(self, t):
        return 1 + 0.08 * ease((t - 1.0) / max(self.t_intro - 1.0, 0.1))

    def frame(self, n):
        t = n / FPS
        if t < self.t_intro:
            fr = self.intro.frame(t)
            z = self.intro_zoom(t)
            if z > 1.001:
                fr = fr.resize((W, H), Image.BILINEAR, box=(W / 2 - W / 2 / z, H / 2 - H / 2 / z, W / 2 + W / 2 / z, H / 2 + H / 2 / z))
            fr = self.particles(fr.convert('RGBA'), t, 0.45)
            self.draw_captions(fr, t)
            return fr.convert('RGB')
        fr = self.scene_backdrop(t)
        x = (t - self.t_intro) / 0.55
        if x < 1:
            fr = Image.blend(self.intro.background(t).convert('RGBA'), fr, ease(x))
        fr.paste((0, 0, 0), (0, 0, W, H), self.vig)
        dx, dy = self.shake(t)
        for i, sc in enumerate(self.scenes):
            T0 = sc['T']
            T1 = self.scenes[i + 1]['T'] if i + 1 < len(self.scenes) else 1e9
            if t < T0 or t > T1 + 0.35:
                continue
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            sc['draw'](lay, t)
            a, s = 1.0, 1.0
            if i > 0 and t < T0 + 0.35:
                q = ease((t - T0) / 0.35)
                a, s = q, 1.1 - 0.1 * q
            if t > T1:
                q = ease((t - T1) / 0.35)
                a, s = a * (1 - q), s * (1 + 0.25 * q)
            place(fr, lay, W / 2 + dx, H / 2 + dy, s, a)
        # header: logo + the sticker flying up from the intro
        u = t - (self.t_intro + 0.35)
        if u > 0:
            place(fr, self.k_small, 60 + self.k_small.width / 2, LOGO_Y - 120 * (1 - ease_out(u / 0.5)), 1, min(1, u / 0.3))
        x = ease((t - self.t_intro) / 0.7)
        ze = self.intro_zoom(self.t_intro)
        s0 = self.intro.logo_state(self.t_intro)[0] * ze
        y0 = H / 2 + (880 - H / 2) * ze
        s = s0 + (STICKER_S - s0) * x if x < 1 else STICKER_S * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t))
        fr = self.intro.draw_sticker(fr, t, W / 2, y0 + (STICKER_Y - y0) * x, s, glow=0.9)
        fr = self.end_card(fr, t)
        fr = self.particles(fr, t)
        self.draw_captions(fr, t)
        fr = fr.convert('RGB')
        for tf in self.flashes:
            v = abs(t - tf - 0.05)
            if v < 0.15:
                fr = Image.blend(fr, Image.new('RGB', fr.size, FLASH), 0.4 * (1 - v / 0.15))
        return fr

    # ---------------------------------------------------------------- audio / encode
    def audio(self):
        n = int((self.total + 2) * SR)
        vo_track, sfx_track = np.zeros(n, np.float32), np.zeros(n, np.float32)

        def add(t, x, g, dst=None):
            dst = sfx_track if dst is None else dst
            i = int(max(t, 0) * SR)
            x = x[:max(0, n - i)]
            dst[i:i + len(x)] += x * g

        for t, x, g in self.intro.sfx():
            add(t, x, g * 0.75)                           # keep the intro hits under the spoken hook
        lib = {'pop': (sfx_pop, 0.22), 'thud': (sfx_thud, 0.42), 'whoosh': (lambda: sfx_whoosh(0.6), 0.22),
               'boom_soft': (lambda: sfx_boom(1.2), 0.32), 'tick': (sfx_tick, 0.09), 'confetti': (sfx_confetti, 0.5)}
        for t, kind in self.events:
            f, g = lib[kind]
            add(t, f(), g)
        for t, (v, _) in zip(self.vo_starts, self.vo):
            add(t, v, 1.0, vo_track)

        def smooth(x, k):
            c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
            y = (c[k:] - c[:-k]) / k
            return np.concatenate([np.full(k // 2, y[0]), y, np.full(len(x) - len(y) - k // 2, y[-1])]).astype(np.float32)

        # sound effects duck under the voice so it stays clear and in front
        rms = np.sqrt(np.maximum(smooth(vo_track ** 2, int(0.06 * SR)), 0))
        duck = smooth(1 - 0.5 * np.clip(rms / 0.06, 0, 1), int(0.12 * SR))
        out = (vo_track * 1.1 + sfx_track * duck)[:int(self.total * SR)]
        fade = int(0.12 * SR)                             # no fade to black: TikTok loops the video
        out[-fade:] *= np.linspace(1, 0, fade)
        out = np.tanh(out * 1.1) / np.tanh(1.1) * 0.95
        path = os.path.join(CACHE, 'story_mix.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            s = (np.clip(out, -1, 1) * 32767).astype(np.int16)
            w.writeframes(np.repeat(s[:, None], 2, axis=1).tobytes())
        return path

    def render(self, out):
        mix = self.audio()
        nf = int(round(self.total * FPS))
        cmd = ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
               '-i', '-', '-i', mix, '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
               '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
               '-shortest', out]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for n in range(nf):
            p.stdin.write(self.frame(n).tobytes())
        p.stdin.close()
        p.wait()
        print(f'{out}: {self.total:.2f}s, {nf} frames')


if __name__ == '__main__':
    st = Story(sys.argv[1])
    if sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(st.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else os.path.join(CACHE, 'preview.png'))
        print('vo starts', [round(x, 2) for x in st.vo_starts], 'scenes', [round(x, 2) for x in st.scene_t],
              'end card', round(st.t_end, 2), 'total', round(st.total, 2))
        for i, (_, words) in enumerate(st.vo):
            print(i, ' '.join(f'{w}@{st.vo_starts[i] + a:.2f}' for w, a, b in words))
    else:
        st.render(sys.argv[2])
