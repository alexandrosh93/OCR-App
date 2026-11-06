#!/usr/bin/env python3
"""'Ήξερες ότι;' story generator — a reel built from scratch from a real photo + a fact (no pre-made post).

    python3 make_story.py configs/anorthosis_story.json ../videos/anorthosis_story.mp4
    python3 make_story.py configs/anorthosis_story.json --preview 3,5,8,12 preview.png

One scene per VO line, cut together with zoom transitions and flashes:
  date  : big day + month, year rolls in on flip-clock odometer tiles
  score : the real photo in a framed card + broadcast-style scoreboard with rolling digits
  fact  : crest on rotating rays, headline words slam in, mascot, confetti burst
then the branded end card. The backdrop is the real photo, blurred and tinted, with light beams and bokeh.

Timings can be seconds after the line starts, or {"word": "πρώτη"} = the moment the voice says that word
(edge-tts word boundaries; add "edge": "end" for the end of the word, "offset" to nudge).
"""
import sys, os, json, math, random, hashlib, subprocess, wave, ssl, asyncio, unicodedata
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from make_video import (HERE, CACHE, W, H, FPS, SR, T_INTRO, NAVY, INK, LIME, fnt, ease, ease_out, ease_out_back,
                        with_alpha, glow_of, place, vgrad, sticker_text, calendar_icon, Intro, band_noise, env_t,
                        sfx_pop, sfx_thud, sfx_whoosh, sfx_boom)

FLASH = (215, 255, 200)
STICKER_Y, STICKER_S = 235, 0.42


def norm(w):
    w = unicodedata.normalize('NFD', w.lower())
    return ''.join(c for c in w if not unicodedata.combining(c) and c.isalnum())


# energetic "sports presenter" voice: presence boost, tighter dynamics
VOICE_FX = ('highpass=f=80,equalizer=f=180:t=q:w=1:g=-2,equalizer=f=3300:t=q:w=1.4:g=4,'
            'equalizer=f=8000:t=q:w=1:g=2,acompressor=threshold=-22dB:ratio=3.5:attack=4:release=80:makeup=5')


def tts_words(text, voice, rate, pitch='+0Hz', fx=True):
    """Greek TTS + per-word timings. Returns (mono float audio at SR, [[word, start, end], ...])."""
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(f'words|{voice}|{rate}|{pitch}|{fx}|{text}'.encode()).hexdigest()[:16]
    wav, js = os.path.join(CACHE, f'{key}.wav'), os.path.join(CACHE, f'{key}.json')
    if not (os.path.exists(wav) and os.path.exists(js)):
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

        for attempt in range(5):                     # the free TTS endpoint fails now and then: retry
            try:
                audio, words = asyncio.run(run())
                if audio and words:
                    break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f'tts retry ({e.__class__.__name__})', file=sys.stderr)
            import time
            time.sleep(2 * (attempt + 1))
        mp3 = wav[:-4] + '.mp3'
        open(mp3, 'wb').write(audio)
        t0, t1 = max(0.0, words[0][1] - 0.04), words[-1][2] + 0.3
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-ss', f'{t0:.3f}', '-to', f'{t1:.3f}']
                       + (['-af', VOICE_FX] if fx else []) + ['-ar', str(SR), '-ac', '1', '-c:a', 'pcm_s16le', wav], check=True)
        os.remove(mp3)
        json.dump([[w, a - t0, b - t0] for w, a, b in words], open(js, 'w', encoding='utf-8'), ensure_ascii=False)
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    n = len(x)
    x[:int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    x[n - int(0.08 * SR):] *= np.linspace(1, 0, int(0.08 * SR))
    return x / max(np.abs(x).max(), 1e-3) * 0.89, json.load(open(js, encoding='utf-8'))


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


def fit_text(text, color, maxw, max_size, min_size=36, step=6):
    size = max_size
    while True:
        im = sticker_text(text, fnt('FiraSansExtraCondensed-Black', size), color,
                          stroke=int(max(6, size * 0.075)), depth=int(max(5, size * 0.055)))
        if im.width <= maxw or size <= min_size:
            return im
        size -= step


def plain_text(text, font, color=(255, 255, 255), stroke=0):
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, t, r, b = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
    im = Image.new('RGBA', (r - l + 8, b - t + 8), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4 - l, 4 - t), text, font=font, fill=color + (255,), stroke_width=stroke,
                            stroke_fill=INK + (255,))
    return im


def hgrad(size, c0, c1):
    w, h = size
    t = np.linspace(0, 1, w)[None, :, None]
    g = np.array(c0)[None, None] * (1 - t) + np.array(c1)[None, None] * t
    return Image.fromarray(np.repeat(g, h, axis=0).astype(np.uint8), 'RGB')


def shade(c, k):
    return tuple(int(max(0, min(255, v * k))) for v in c)


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
    m = Image.new('L', tile.size, 0)                 # keep digits inside the rounded tile
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), 24, fill=255)
    tile.putalpha(ImageChops.multiply(tile.getchannel('A'), m))
    return tile


def roll(t, target, t0, t1, spins):
    """Odometer value: spins down onto `target` between t0 and t1."""
    span = 10 * spins + 5
    if t <= t0:
        return target + span
    return target + span * (1 - ease_out(min(1, (t - t0) / max(t1 - t0, 0.05)), 3))


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
        voice = cfg.get('voice', 'el-GR-NestorasNeural')
        rate, pitch, fx = cfg.get('rate', '+18%'), cfg.get('pitch', '+10Hz'), cfg.get('voice_fx', True)
        lines = [cfg.get('intro_line', 'Ήξερες ότι;')] + cfg['lines'] + [cfg.get('cta', 'Ακολούθησε το Κουπονάκι για περισσότερα!')]
        lines = [l if isinstance(l, dict) else {'text': l} for l in lines]      # a line may override rate / pitch
        mp = cfg.get('max_pause', 0.22)
        self.vo = [tighten(*tts_words(l['text'], l.get('voice', voice), l.get('rate', rate), l.get('pitch', pitch), fx),
                           max_pause=mp) for l in lines]
        self.intro = Intro()
        self.team = cfg['team']
        self.tcol = tuple(self.team['color'])
        self.photo = Image.open(os.path.join(HERE, cfg['photo'])).convert('RGB')
        self.events, self.shakes, self.flashes = [], [], []
        self.timeline()
        self.build_backdrop()
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((380, int(kl.height * 380 / kl.width)), Image.LANCZOS)
        self.k_big = kl.resize((860, int(kl.height * 860 / kl.width)), Image.LANCZOS)
        self.font_cta = fnt('FiraSans-SemiBold', 56)
        self.scenes = []
        for i, sc in enumerate(cfg['scenes']):
            line, T = i + 1, self.scene_t[i]
            self.scenes.append(dict(T=T, draw=getattr(self, 'build_' + sc['type'])(sc, line, T)))
            if i:
                self.events.append((T - 0.2, 'whoosh'))
                self.flashes.append(T)
        self.events += [(T_INTRO - 0.15, 'whoosh'), (self.t_end - 0.1, 'whoosh'), (self.t_end + 0.2, 'boom_soft')]
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.0), v=rnd.uniform(18, 60),
                           ph=rnd.uniform(0, 6.28)) for _ in range(60)]

    # ---------------------------------------------------------------- timing
    def timeline(self):
        d = [len(a) / SR for a, _ in self.vo]
        starts = [self.intro.t_hit + 0.3]
        t = T_INTRO + 0.35
        for i in range(1, len(self.vo) - 1):
            starts.append(t)
            t += d[i] + 0.45
        t += self.cfg.get('hold', 0.8)
        self.t_end = t - 0.3
        starts.append(t)
        self.vo_starts = starts
        self.total = t + d[-1] + 1.1
        self.scene_t = [T_INTRO] + [starts[i] - 0.3 for i in range(2, len(self.vo) - 1)]

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

    def roll_ticks(self, t0, t1, target, spins):
        last, out = None, []
        for tt in np.arange(t0, t1 + 0.001, 0.004):
            k = math.floor(roll(tt, target, t0, t1, spins) + 0.5)
            if last is not None and k != last:
                out.append(tt)
            last = k
        return out

    def add_ticks(self, times):
        times = sorted(times)
        kept = []
        for tt in times:
            if not kept or tt - kept[-1] > 0.035:
                kept.append(tt)
        self.events += [(tt, 'tick') for tt in kept]

    # ---------------------------------------------------------------- backdrop
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

    def backdrop(self, t):
        z = 1 + 0.08 * ease(t / self.total)
        ww, wh = self.bd.width / z, self.bd.height / z
        cx = self.bd.width / 2 + (self.bd.width - ww) / 2 * math.sin(t * 0.3)
        cy = self.bd.height / 2
        fr = self.bd.resize((W, H), Image.BILINEAR, box=(cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2)).convert('RGBA')
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

    # ---------------------------------------------------------------- scene: date
    def build_date(self, sc, line, T):
        tD = self.at(line, sc.get('day_at', 0.0))
        tM = self.at(line, sc.get('month_at', {'word': sc['month']}))
        tY0, tY1 = self.at(line, sc['year_at']), self.at(line, sc['year_end'])
        day = fit_text(sc['day'], 'white', 940, 440)
        dglow, gp = glow_of(day, 30, LIME)
        month = fit_text(sc['month'], 'yellow', 900, 170)
        icon = calendar_icon(118)
        tw, th, gap = 176, 236, 20
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 200), tw, th, LIME)
        bg, ov = tile_parts(tw, th)
        n = len(sc['year'])
        x0 = W / 2 - (n * tw + (n - 1) * gap) / 2 + tw / 2
        rolls = [dict(target=int(c), t0=tY0 + 0.08 * i, t1=tY1 + 0.1 * i, spins=1 + i, cx=x0 + i * (tw + gap))
                 for i, c in enumerate(sc['year'])]
        self.events += [(tD, 'thud'), (tM, 'pop'), (tY0 - 0.35, 'pop')]
        self.shakes.append((tD, 16))
        ticks = []
        for r in rolls:
            ticks += self.roll_ticks(r['t0'], r['t1'], r['target'], r['spins'])
        self.add_ticks(ticks)
        Yd, Ym, Yy = 870, 1160, 1410

        def draw(fr, t):
            u = t - (tD - 0.25)
            if u > 0:
                place(fr, icon, W / 2, Yd - 290, ease_out_back(u / 0.4, 2.0), min(1, u / 0.15))
            u = t - tD
            if u > 0:
                s = 1 + 0.55 * (1 - ease_out(u / 0.22, 3))
                place(fr, dglow, W / 2, Yd, s, 0.55 * min(1, u / 0.2))
                place(fr, day, W / 2, Yd, s, min(1, u / 0.1))
            u = t - tM
            if u > 0:
                q = ease_out(u / 0.35)
                place(fr, month, W / 2, Ym + 40 * (1 - q), 1, min(1, u / 0.2))
                L = 120 * q
                if L > 2:
                    d = ImageDraw.Draw(fr)
                    half = month.width / 2 + 14
                    d.rounded_rectangle((W / 2 - half - L, Ym - 5, W / 2 - half, Ym + 5), 5, fill=LIME + (255,))
                    d.rounded_rectangle((W / 2 + half, Ym - 5, W / 2 + half + L, Ym + 5), 5, fill=LIME + (255,))
            u = t - (tY0 - 0.35)
            if u > 0:
                s = ease_out_back(u / 0.4, 1.8)
                for r in rolls:
                    tile = digit_tile(strip, bg, ov, roll(t, r['target'], r['t0'], r['t1'], r['spins']))
                    place(fr, tile, r['cx'], Yy, s, min(1, u / 0.15))
        return draw

    # ---------------------------------------------------------------- scene: score
    def photo_card(self, width, max_h):
        src = self.photo
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

    def plate(self, name, color, crest=None, pw=400, ph=128, skew=26, mirror=False):
        im = Image.new('RGBA', (pw, ph), (0, 0, 0, 0))
        m = Image.new('L', (pw, ph), 0)
        poly = [(skew, 0), (pw, 0), (pw - skew, ph), (0, ph)]
        ImageDraw.Draw(m).polygon(poly, fill=255)
        g = hgrad((pw, ph), shade(color, 1.25) if not mirror else shade(color, 0.7),
                  shade(color, 0.7) if not mirror else shade(color, 1.25)).convert('RGBA')
        g.putalpha(m)
        im.alpha_composite(g)
        ImageDraw.Draw(im).line(poly + [poly[0]], fill=(255, 255, 255, 120), width=3)
        x = skew + 26
        if crest is not None:
            c = crest.resize((int(crest.width * (ph - 24) / crest.height), ph - 24), Image.LANCZOS)
            im.alpha_composite(c, (x, 12))
            x += c.width + 16
        avail = pw - x - skew - 46
        size = 62
        while size > 30:
            txt = plain_text(name, fnt('FiraSansExtraCondensed-Black', size), stroke=3)
            if txt.width <= avail:
                break
            size -= 2
        tx = x if crest is not None else (pw - txt.width) / 2
        im.alpha_composite(txt, (int(tx), int(ph / 2 - txt.height / 2)))
        return im

    def build_score(self, sc, line, T):
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        card = self.photo_card(980, 720)
        tP = T + 0.12
        tHo, tAw = self.at(line, sc['home_at']), self.at(line, sc['away_at'])
        tBox, tR0, tR1 = self.at(line, sc['score_at']), self.at(line, sc['roll_at']), self.at(line, sc['roll_end'])
        home = self.plate(sc['home'], self.tcol, crest)
        away = self.plate(sc['away'], tuple(sc.get('away_color', (90, 90, 100))), None, mirror=True)
        bw, bh = 270, 176
        box = Image.new('RGBA', (bw + 60, bh + 60), (0, 0, 0, 0))
        gl = Image.new('RGBA', box.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, outline=LIME + (255,), width=12)
        box.alpha_composite(gl.filter(ImageFilter.GaussianBlur(11)))
        ImageDraw.Draw(box).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, fill=(8, 20, 36, 250), outline=LIME + (255,), width=5)
        dw, dh = 92, 132
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 122), dw, dh, LIME)
        tbg, tov = tile_parts(dw, dh, border=None, radius=16)
        dash = plain_text('–', fnt('FiraSansExtraCondensed-Black', 90))
        goals = [dict(target=sc['score'][0], t0=tR0, t1=tR0 + 0.75, spins=1),
                 dict(target=sc['score'][1], t0=tR1 - 0.45, t1=tR1 + 0.3, spins=1)]
        pill_f = fnt('FiraSansExtraCondensed-Bold', 40)
        ptxt = plain_text(sc.get('label', 'ΣΥΝΟΛΙΚΟ ΣΚΟΡ'), pill_f, (6, 30, 16))
        pill = Image.new('RGBA', (ptxt.width + 56, 64), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, 63), 32, fill=LIME + (255,))
        pill.alpha_composite(ptxt, (28, int(32 - ptxt.height / 2)))
        sub = plain_text(sc.get('sub', ''), fnt('FiraSans-SemiBold', 38)) if sc.get('sub') else None
        self.events += [(tP, 'whoosh'), (tHo, 'pop'), (tAw, 'pop'), (tBox, 'thud')]
        self.shakes.append((tBox, 8))
        for g in goals:
            self.add_ticks(self.roll_ticks(g['t0'], g['t1'], g['target'], g['spins']))
        Yc, Ys = 790, 1395

        def draw(fr, t):
            self.draw_card(fr, card, t, tP, W / 2, Yc)
            u = t - tHo
            if u > 0:
                place(fr, home, 30 + home.width / 2 - 560 * (1 - ease_out_back(u / 0.5, 1.3)), Ys, 1, min(1, u / 0.15))
            u = t - tAw
            if u > 0:
                place(fr, away, W - 30 - away.width / 2 + 560 * (1 - ease_out_back(u / 0.5, 1.3)), Ys, 1, min(1, u / 0.15))
            u = t - tBox
            if u > 0:
                b = box.copy()
                for i, g in enumerate(goals):
                    tile = digit_tile(strip, tbg, tov, roll(t, g['target'], g['t0'], g['t1'], g['spins']))
                    b.alpha_composite(tile, (int(30 + 16 + i * (bw - 32 - dw)), int(30 + (bh - dh) / 2)))
                b.alpha_composite(dash, (int(box.width / 2 - dash.width / 2), int(box.height / 2 - dash.height / 2)))
                place(fr, b, W / 2, Ys, 0.3 + 0.7 * ease_out_back(u / 0.45, 2.0), min(1, u / 0.12))
                v = u - 0.35
                if v > 0:
                    q = ease_out(v / 0.4)
                    place(fr, pill, W / 2, Ys + 165 + 30 * (1 - q), 1, min(1, v / 0.25))
                    if sub is not None:
                        place(fr, sub, W / 2, Ys + 240 + 30 * (1 - q), 1, min(1, (v - 0.1) / 0.3))
        return draw

    # ---------------------------------------------------------------- scene: fact
    def build_fact(self, sc, line, T):
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        crest = crest.resize((int(crest.width * 330 / crest.height), 330), Image.LANCZOS)
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
        words, y = [], 870
        for i, wd in enumerate(sc['words']):
            im = fit_text(wd['text'], wd.get('color', 'white'), 980, wd.get('max_size', 220))
            tw = self.at(line, wd['at'])
            words.append(dict(im=im, t=tw, cy=y + im.height / 2))
            self.events.append((tw, 'thud'))
            self.shakes.append((tw, 18 if i == 0 else 7))
            y += im.height - 18
        mascot = None
        if self.team.get('mascot'):
            m = Image.open(os.path.join(HERE, self.team['mascot'])).convert('RGBA')
            hgt = int(min(430, H - 40 - y + 60))
            mascot = m.resize((int(m.width * hgt / m.height), hgt), Image.LANCZOS)
            tMa = self.at(line, sc.get('mascot_at', 0.5))
            self.events += [(tMa, 'whoosh'), (tMa + 0.35, 'pop')]
        stamp = None
        if sc.get('stamp'):
            st = sc['stamp']
            simg = fit_text(st['text'], st.get('color', 'yellow'), 560, st.get('max_size', 120))
            sg, _ = glow_of(simg, 18, LIME)
            stamp = dict(im=simg, glow=sg, t=self.at(line, st['at']), x=st.get('x', 770), y=st.get('y', 760),
                         rot=st.get('rotate', 12))
            self.events.append((stamp['t'], 'thud'))
            self.shakes.append((stamp['t'], 14))
        tCf = self.at(line, sc['confetti_at']) if sc.get('confetti_at') else None
        if tCf is not None:
            self.events.append((tCf, 'confetti'))
        self.events += [(tC, 'whoosh'), (tC + 0.3, 'pop')]
        rnd = random.Random(9)
        light = tuple(min(255, int(c * 1.3 + 60)) for c in self.tcol)
        cols = [LIME, (255, 255, 255), (255, 214, 30), light]
        conf = []
        for i in range(160):
            burst = i < 100
            ang = rnd.uniform(-math.pi * 0.92, -math.pi * 0.08)
            sp = rnd.uniform(800, 1700)
            conf.append(dict(burst=burst, x0=W / 2 + rnd.uniform(-80, 80) if burst else rnd.uniform(0, W),
                             y0=words[min(2, len(words) - 1)]['cy'] if burst else rnd.uniform(-900, -40),
                             vx=math.cos(ang) * sp if burst else rnd.uniform(-40, 40),
                             vy=math.sin(ang) * sp if burst else rnd.uniform(120, 260),
                             d=rnd.uniform(0, 0.06) if burst else rnd.uniform(0, 0.4),
                             w=rnd.uniform(13, 24), h=rnd.uniform(7, 12), r0=rnd.uniform(0, 6.28),
                             rv=rnd.uniform(-7, 7), fv=rnd.uniform(5, 11), ph=rnd.uniform(0, 6.28), c=rnd.choice(cols)))
        Yc = 640

        def draw(fr, t):
            u = t - tC
            if u > 0:
                k = min(1, u / 0.5)
                rr = rays.rotate(t * 16, resample=Image.BILINEAR).resize((1150, 1150), Image.BILINEAR)
                lay = Image.new('RGBA', rr.size, ray_col + (0,))
                lay.putalpha(rr.point(lambda v: int(v * k)))
                place(fr, lay, W / 2, Yc, 0.6 + 0.4 * ease_out(u / 0.6))
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
                place(fr, cglow, W / 2, Yc + fl, max(e, 0.15), 0.7 * min(1, u / 0.3))
                place(fr, im, W / 2, Yc + fl, max(e, 0.15), min(1, u / 0.15), rot=30 * (1 - ease_out(u / 0.6)))
            if tCf is not None and t > tCf:
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
                    place(fr, wd['im'], W / 2, wd['cy'], s, min(1, u / 0.08))
            if stamp is not None and t > stamp['t']:
                u = t - stamp['t']
                sc_ = 1 + 1.4 * (1 - ease_out(u / 0.18, 3))
                place(fr, stamp['glow'], stamp['x'], stamp['y'], sc_, 0.8 * min(1, u / 0.1), rot=stamp['rot'])
                place(fr, stamp['im'], stamp['x'], stamp['y'], sc_, min(1, u / 0.06), rot=stamp['rot'])
            if mascot is not None and t > tMa:
                u = t - tMa
                e = ease_out_back(u / 0.55, 1.5)
                place(fr, mascot, 30 + mascot.width / 2 - 420 * (1 - e), H - 30 - mascot.height / 2 + 320 * (1 - e)
                      + 10 * math.sin(2 * math.pi * 1.1 * u), 1, min(1, u / 0.2), rot=-16 * (1 - e) + 3 * math.sin(3.4 * u))
        return draw

    # ---------------------------------------------------------------- end card / frame
    def end_card(self, fr, t):
        k = ease((t - self.t_end) / 0.5)
        if k <= 0:
            return fr
        fr = Image.alpha_composite(fr, Image.new('RGBA', fr.size, (3, 10, 22, int(210 * k))))
        p = ease_out_back((t - self.t_end - 0.05) / 0.55)
        if p > 0.02:
            fr = self.intro.draw_sticker(fr, 0, W / 2, 650, 0.7 * p, glow=k)
        p = ease_out_back((t - self.t_end - 0.25) / 0.55)
        if p > 0.02:
            g, _ = glow_of(self.k_big, 26, (70, 220, 50))
            place(fr, g, W / 2, 1010, p, 0.55 * k)
            place(fr, self.k_big, W / 2, 1010, p, 1)
        q = ease((t - self.t_end - 0.6) / 0.45)
        if q > 0:
            lay = Image.new('RGBA', fr.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            txt = 'Ακολούθησε για περισσότερα'
            tw = d.textlength(txt, font=self.font_cta)
            d.text((W / 2 - tw / 2, 1120 + 30 * (1 - q)), txt, font=self.font_cta, fill=(255, 255, 255, int(255 * q)))
            fr = Image.alpha_composite(fr, lay)
        return fr

    def frame(self, n):
        t = n / FPS
        if t < T_INTRO:
            fr = self.particles(self.intro.frame(t).convert('RGBA'), t, 0.45)
            return fr.convert('RGB')
        fr = self.backdrop(t)
        x = (t - T_INTRO) / 0.55
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
        u = t - (T_INTRO + 0.35)
        if u > 0:
            place(fr, self.k_small, 50 + self.k_small.width / 2, 92 - 120 * (1 - ease_out(u / 0.5)), 1, min(1, u / 0.3))
        x = ease((t - T_INTRO) / 0.7)
        s0 = self.intro.logo_state(T_INTRO)[0]
        s = s0 + (STICKER_S - s0) * x if x < 1 else STICKER_S * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t))
        fr = self.intro.draw_sticker(fr, t, W / 2, 880 + (STICKER_Y - 880) * x, s, glow=0.9)
        fr = self.end_card(fr, t)
        fr = self.particles(fr, t)
        fr = fr.convert('RGB')
        for tf in self.flashes:
            v = abs(t - tf - 0.05)
            if v < 0.15:
                fr = Image.blend(fr, Image.new('RGB', fr.size, FLASH), 0.4 * (1 - v / 0.15))
        fo = ease((t - (self.total - 0.35)) / 0.35)
        return Image.blend(fr, Image.new('RGB', fr.size, (0, 0, 0)), fo) if fo > 0 else fr

    # ---------------------------------------------------------------- audio / encode
    def audio(self):
        out = np.zeros(int((self.total + 2) * SR), np.float32)

        def add(t, x, g):
            i = int(max(t, 0) * SR)
            x = x[:max(0, len(out) - i)]
            out[i:i + len(x)] += x * g

        for t, x, g in self.intro.sfx():
            add(t, x, g)
        lib = {'pop': (sfx_pop, 0.22), 'thud': (sfx_thud, 0.42), 'whoosh': (lambda: sfx_whoosh(0.6), 0.22),
               'boom_soft': (lambda: sfx_boom(1.2), 0.32), 'tick': (sfx_tick, 0.09), 'confetti': (sfx_confetti, 0.5)}
        for t, kind in self.events:
            f, g = lib[kind]
            add(t, f(), g)
        for t, (v, _) in zip(self.vo_starts, self.vo):
            add(t, v, 1.0)
        out = out[:int(self.total * SR)]
        fade = int(0.35 * SR)
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
