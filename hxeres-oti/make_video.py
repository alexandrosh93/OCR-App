#!/usr/bin/env python3
"""'Ήξερες ότι;' reel generator (Kouponaki) — motion-graphics template.

    python3 make_video.py configs/apoel.json ../videos/apoel.mp4
    python3 make_video.py configs/apoel.json --preview 2.8,5,8,12 preview.png

The design is rebuilt as animated layers (not a still image):
  intro   : the 'Ήξερες ότι;' sticker reveal + synthetic SFX, then the sticker flies to the top
  header  : kouponaki.com logo + optional pill (e.g. CHAMPIONS LEAGUE)
  hero    : headline lines (white / yellow / green), club crest (+ stars), subtitle
  middle  : mascot + stat cards (numbers count up)
  panel   : date card, title, body text with **highlighted** words
  end     : sticker + kouponaki.com + 'Ακολούθησε για περισσότερα'
Background is the post's own stadium photo with the design elements painted out.
Each element appears on a beat: "at": [line, seconds] = N seconds after VO line `line` starts
(line 0 = the moment the intro hands over to the main part).
"""
import sys, os, json, math, random, hashlib, subprocess, wave, ssl, asyncio
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache')
W, H, FPS, SR = 1080, 1920, 30, 48000
T_INTRO = 2.6
NAVY = (4, 12, 24)
INK = (9, 20, 40)
COLORS = {'white': ((255, 255, 255), (214, 222, 232)), 'yellow': ((255, 222, 40), (255, 168, 0)),
          'green': ((178, 255, 74), (104, 222, 30))}
LIME = (132, 236, 46)


def fnt(name, size):
    return ImageFont.truetype(os.path.join(HERE, 'fonts', name + '.ttf'), size)


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (x * 6 - 15) + 10)


def ease_out(x, p=3):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** p


def ease_out_back(x, s=1.7):
    x = min(max(x, 0.0), 1.0) - 1
    return x * x * ((s + 1) * x + s) + 1


def with_alpha(im, k):
    if k >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel('A').point(lambda v: int(v * max(k, 0))))
    return im


def glow_of(im, radius, color):
    """Soft halo following im's alpha, padded so the blur never clips. Returns (glow, pad)."""
    pad = int(radius * 3)
    a = Image.new('L', (im.width + 2 * pad, im.height + 2 * pad), 0)
    a.paste(im.getchannel('A'), (pad, pad))
    g = Image.new('RGBA', a.size, color + (0,))
    g.putalpha(a.filter(ImageFilter.GaussianBlur(radius)))
    return g, pad


def place(fr, im, cx, cy, scale=1.0, alpha=1.0, rot=0.0):
    """Composite im centred at (cx, cy) with scale / opacity / rotation."""
    if scale <= 0.01 or alpha <= 0.01:
        return
    if abs(scale - 1) > 1e-3:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    if rot:
        im = im.rotate(rot, expand=True, resample=Image.BILINEAR)
    im = with_alpha(im, alpha)
    x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    if x >= W or y >= H or x + im.width <= 0 or y + im.height <= 0:
        return
    fr.alpha_composite(im, (max(x, 0), max(y, 0)), (max(-x, 0), max(-y, 0)))


def vgrad(size, top, bot, y0=0, y1=None):
    w, h = size
    y1 = h if y1 is None else y1
    t = np.clip((np.arange(h) - y0) / max(y1 - y0, 1), 0, 1)[:, None, None]
    g = np.array(top)[None, None] * (1 - t) + np.array(bot)[None, None] * t
    return Image.fromarray(np.repeat(g, w, axis=1).astype(np.uint8), 'RGB')


def sticker_text(text, font, color='white', stroke=12, depth=9):
    """Bold display text in the design's style: gradient fill, thick navy outline, 3D drop."""
    top, bot = COLORS[color]
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, t, r, b = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
    pad = stroke + depth + 24
    w, h = r - l + 2 * pad, b - t + 2 * pad
    o = (pad - l, pad - t)
    outline = Image.new('L', (w, h), 0)
    ImageDraw.Draw(outline).text(o, text, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    fill = Image.new('L', (w, h), 0)
    ImageDraw.Draw(fill).text(o, text, font=font, fill=255)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    sh = Image.new('L', (w, h), 0)
    sh.paste(outline, (0, depth + 8))
    out.alpha_composite(Image.merge('RGBA', [Image.new('L', (w, h), 0)] * 3 + [sh.filter(ImageFilter.GaussianBlur(9)).point(lambda v: v * 0.7)]))
    for k in range(depth, 0, -1):
        m = Image.new('L', (w, h), 0)
        m.paste(outline, (0, k))
        lay = Image.new('RGBA', (w, h), (3, 8, 18, 255))
        lay.putalpha(m)
        out.alpha_composite(lay)
    lay = Image.new('RGBA', (w, h), INK + (255,))
    lay.putalpha(outline)
    out.alpha_composite(lay)
    fb = fill.getbbox() or (0, 0, w, h)
    g = vgrad((w, h), top, bot, fb[1], fb[3]).convert('RGBA')
    g.putalpha(fill)
    out.alpha_composite(g)
    return out.crop(out.getbbox())


def parse_marks(s):
    """'a **b c** d' -> [('a', False), ('b', True), ('c', True), ('d', False)] per line."""
    lines = []
    for raw in s.split('\n'):
        toks, hl = [], False
        for i, part in enumerate(raw.split('**')):
            hl = i % 2 == 1
            for j, w in enumerate(part.split()):
                # punctuation right after a highlight glues to the previous word (no space)
                toks.append((w, hl, j == 0 and toks and not part[:1].isspace() and w[0] in ',.;:!?)·'))
        lines.append(toks)
    return lines


def rich_lines(s, font, maxw, color=(255, 255, 255), accent=LIME, stroke=0):
    """Wrap marked-up text into RGBA line images."""
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    sp = d.textlength(' ', font=font)
    out = []
    for toks in parse_marks(s):
        cur, cw = [], 0
        rows = []
        for w, hl, glue in toks:
            tw = d.textlength(w, font=font)
            gap = 0 if glue else sp
            if cur and not glue and cw + gap + tw > maxw:
                rows.append(cur)
                cur, cw = [], 0
            cur.append((w, hl, tw, glue and len(cur) > 0))
            cw += (gap if len(cur) > 1 else 0) + tw
        if cur:
            rows.append(cur)
        for row in rows:
            asc, desc = font.getmetrics()
            lw = int(sum(t[2] for t in row) + sp * sum(1 for t in row[1:] if not t[3])) + 2 * stroke + 4
            im = Image.new('RGBA', (lw, asc + desc + 2 * stroke + 4), (0, 0, 0, 0))
            dr = ImageDraw.Draw(im)
            x = stroke + 2
            for k, (w, hl, tw, glue) in enumerate(row):
                if glue:
                    x -= sp
                dr.text((x, stroke + 2), w, font=font, fill=(accent if hl else color) + (255,),
                        stroke_width=stroke, stroke_fill=INK + (255,))
                x += tw + sp
            out.append(im)
    return out


def star(size, color=(255, 200, 40)):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    c, R, r = size / 2, size * 0.46, size * 0.19
    pts = [(c + (R if i % 2 == 0 else r) * math.cos(-math.pi / 2 + i * math.pi / 5),
            c + 2 + (R if i % 2 == 0 else r) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)]
    ImageDraw.Draw(im).polygon(pts, fill=color + (255,), outline=(120, 80, 0, 255))
    return im


def calendar_icon(size, color=LIME):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((s * .06, s * .16, s * .94, s * .94), s * .12, outline=color, width=max(3, s // 14))
    d.rectangle((s * .06, s * .16, s * .94, s * .36), fill=color)
    for x in (.3, .7):
        d.rounded_rectangle((s * x - s * .05, s * .04, s * x + s * .05, s * .26), s * .04, fill=color)
    for i in range(4):
        for j in range(3):
            cx, cy = s * (.24 + .17 * i), s * (.5 + .14 * j)
            d.rounded_rectangle((cx - s * .05, cy - s * .045, cx + s * .05, cy + s * .045), 2, fill=color)
    return im


# --------------------------------------------------------------------- voice
def tts(text, voice, rate):
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(f'{voice}|{rate}|{text}'.encode()).hexdigest()[:16]
    wav = os.path.join(CACHE, f'{key}.wav')
    if not os.path.exists(wav):
        import edge_tts, edge_tts.communicate as c
        ca = os.environ.get('SSL_CERT_FILE') or ('/root/.ccr/ca-bundle.crt' if os.path.exists('/root/.ccr/ca-bundle.crt') else None)
        if ca:
            c._SSL_CTX = ssl.create_default_context(cafile=ca)
        mp3 = wav[:-4] + '.mp3'
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(mp3))
        trim = ('silenceremove=start_periods=1:start_threshold=-45dB,areverse,'
                'silenceremove=start_periods=1:start_threshold=-45dB,areverse')
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', mp3, '-af', trim, '-ar', str(SR), '-ac', '1',
                        '-c:a', 'pcm_s16le', wav], check=True)
        os.remove(mp3)
    with wave.open(wav) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return x / max(np.abs(x).max(), 1e-3) * 0.89


# ----------------------------------------------------------------------- sfx
_rng = np.random.default_rng(3)


def band_noise(dur, lo, hi):
    n = int(dur * SR)
    X = np.fft.rfft(_rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    y = np.fft.irfft(X * ((f > lo) & (f < hi)), n)
    return y / (np.abs(y).max() + 1e-9)


def env_t(dur):
    return np.arange(int(dur * SR)) / SR


def sfx_riser(dur=0.55):
    t = env_t(dur)
    return (band_noise(dur, 300, 6000) * 0.8 + 0.15 * np.sin(2 * np.pi * (200 * t + 700 / (2 * dur) * t ** 2))) * (t / dur) ** 2.5


def sfx_boom(dur=1.4):
    t = env_t(dur)
    return (np.sin(2 * np.pi * (45 * t + 10 * (1 - np.exp(-9 * t)))) * np.exp(-3.5 * t)
            + band_noise(dur, 60, 2500) * np.exp(-25 * t) * 0.55 + band_noise(dur, 5000, 12000) * np.exp(-3 * t) * 0.07)


def sfx_ding(dur=1.3):
    t = env_t(dur)
    a = sum(g * np.sin(2 * np.pi * f * t) for f, g in [(1568, 1), (2349, .5), (3136, .3), (4700, .12)])
    b = np.zeros_like(t)
    o = int(0.12 * SR)
    b[o:] = sum(g * np.sin(2 * np.pi * f * t[:-o]) for f, g in [(2093, 1), (3136, .4), (4186, .2)]) * np.exp(-4.5 * t[:-o])
    return a * np.exp(-4.5 * t) * np.clip(t / 0.005, 0, 1) * 0.3 + b * 0.2


def sfx_whoosh(dur=0.7):
    t = env_t(dur)
    return band_noise(dur, 400, 5000) * np.sin(np.pi * t / dur) ** 2


def sfx_pop(dur=0.25, f0=650):
    t = env_t(dur)
    return np.sin(2 * np.pi * (f0 * t - f0 * 1.1 * t ** 2)) * np.exp(-28 * t)


def sfx_thud(dur=0.6):
    t = env_t(dur)
    return np.sin(2 * np.pi * (60 * t + 6 * (1 - np.exp(-14 * t)))) * np.exp(-7 * t) + band_noise(dur, 80, 1800) * np.exp(-35 * t) * 0.5


# --------------------------------------------------------------------- intro
class Intro:
    """Animated 'Ήξερες ότι;' sticker reveal on a navy background."""

    def __init__(self):
        logo = Image.open(os.path.join(HERE, 'assets', 'hxeres_logo.png')).convert('RGBA')
        self.base_w = 930
        k = self.base_w / logo.width
        self.logo = logo.resize((self.base_w, int(logo.height * k)), Image.LANCZOS)
        g, pad = glow_of(self.logo.resize((self.logo.width // 2, self.logo.height // 2)), 16, (90, 255, 40))
        self.glow = g.resize((self.logo.width + 4 * pad, self.logo.height + 4 * pad), Image.BILINEAR)
        self.bulb = (905 * k, 152 * k)
        self.center = (W // 2, 880)
        self.t_hit, self.t_bulb = 0.55, 1.7
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.clip(np.sqrt(((xx - W / 2) / (W * 0.8)) ** 2 + ((yy - 880) / (H * 0.55)) ** 2), 0, 1)[..., None]
        self.bg = Image.fromarray((np.array([12, 44, 70]) * (1 - d) + np.array([2, 8, 18]) * d).astype(np.uint8), 'RGB')
        R = 1200
        rays = Image.new('L', (R, R), 0)
        dr = ImageDraw.Draw(rays)
        rnd = random.Random(5)
        for i in range(22):
            a0, wd = i / 22 * 2 * math.pi + rnd.uniform(-0.05, 0.05), rnd.uniform(0.03, 0.08)
            dr.polygon([(R / 2, R / 2)] + [(R / 2 + R * math.cos(a), R / 2 + R * math.sin(a)) for a in (a0 - wd, a0 + wd)],
                       fill=rnd.randint(90, 200))
        rd = np.asarray(rays.filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
        yy, xx = np.mgrid[0:R, 0:R]
        self.rays = Image.fromarray((rd * np.clip(1 - np.hypot(xx - R / 2, yy - R / 2) / (R * .55), 0, 1) ** 1.4).astype(np.uint8))
        rnd = random.Random(11)
        self.burst = [dict(a=rnd.uniform(0, 2 * math.pi), v=rnd.uniform(500, 1500), r=rnd.uniform(3, 8),
                           c=rnd.choice([(150, 255, 90), (240, 255, 240), (255, 220, 80)])) for _ in range(60)]

    def logo_state(self, t):
        """(scale, rotation, shake) of the sticker at time t."""
        p = (t - 0.15) / (self.t_hit - 0.15)
        u = t - self.t_hit
        s = 0.15 + 0.85 * ease_out_back(p, 2.2) if p < 1 else 1 + 0.012 * math.sin(2 * math.pi * 0.8 * (t - 0.9))
        ang = -14 * (1 - ease_out(p)) if p < 1 else 0
        shake = 16 * math.exp(-u * 9) * math.sin(u * 70) if u > 0 else 0
        return s, ang, shake, p

    def background(self, t):
        fr = self.bg.copy().convert('RGBA')
        cx, cy = self.center
        u = t - self.t_hit
        k = 0.35 * ease(t / self.t_hit) if u < 0 else 0.25 + 0.55 * math.exp(-u * 4)
        rot = self.rays.rotate(t * 12, resample=Image.BILINEAR).resize((2400, 2400), Image.BILINEAR)
        rot = rot.crop((1200 - cx, 1200 - cy, 1200 - cx + W, 1200 - cy + H)).point(lambda v: int(v * k))
        lay = Image.new('RGBA', (W, H), (110, 255, 70, 0))
        lay.putalpha(rot)
        fr = Image.alpha_composite(fr, lay)
        if u > 0:
            rk = ease(u / 0.6)
            lay = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            for j, (amp, lam, sp, dy) in enumerate([(60, 380, 2.2, -10), (45, 300, -1.7, 25), (75, 460, 1.3, 5)]):
                d.line([(x, cy / 2 + dy + amp * math.sin(4 * math.pi * x / lam + t * sp + j) * math.sin(math.pi * x / (W / 2)))
                        for x in range(0, W // 2 + 6, 6)], fill=(120, 255, 80, int(200 * rk)), width=3)
            lay = Image.alpha_composite(lay.filter(ImageFilter.GaussianBlur(5)), lay).resize((W, H), Image.BILINEAR)
            fr = Image.alpha_composite(fr, lay)
        if 0 < u < 0.7:
            q = ease_out(u / 0.7)
            r = 160 + 1000 * q
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(lay).ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8),
                                        outline=(170, 255, 120, int(230 * (1 - q))), width=max(2, int(22 * (1 - q))))
            fr = Image.alpha_composite(fr, lay.filter(ImageFilter.GaussianBlur(3)))
        if 0 < u < 1.2:
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            dist = 1 - math.exp(-u * 3)
            for p in self.burst:
                x = cx + math.cos(p['a']) * p['v'] * dist * 0.6
                y = cy + math.sin(p['a']) * p['v'] * dist * 0.6
                r = p['r'] * (1 - u / 1.2)
                d.ellipse((x - r, y - r, x + r, y + r), fill=p['c'] + (int(255 * (1 - u / 1.2)),))
            fr = Image.alpha_composite(fr, lay)
        return fr

    def draw_sticker(self, fr, t, cx, cy, s, ang=0.0, glow=1.0):
        """Sticker + glow + bulb light at an arbitrary position/scale (used by intro and main part)."""
        lw, lh = int(self.logo.width * s), int(self.logo.height * s)
        if lw < 8:
            return fr
        g = with_alpha(self.glow, glow * (0.75 + 0.25 * math.sin(t * 3))).resize(
            (int(self.glow.width * s), int(self.glow.height * s)), Image.BILINEAR)
        lg = self.logo.resize((lw, lh), Image.BILINEAR)
        if ang:
            g = g.rotate(ang, expand=True, resample=Image.BILINEAR)
            lg = lg.rotate(ang, expand=True, resample=Image.BILINEAR)
        fr.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
        ox, oy = cx - lg.width / 2, cy - lg.height / 2
        bx = ox + (self.bulb[0] - self.logo.width / 2) * s + lg.width / 2
        by = oy + (self.bulb[1] - self.logo.height / 2) * s + lg.height / 2
        b = t - self.t_bulb
        bloom = None
        if b > -0.05:
            bk = min(1, math.exp(-max(b, 0) * 2.0) * 0.8 + 0.4) if b > 0 else 0.15
            lay = Image.new('RGBA', (W // 4, H // 4), (0, 0, 0, 0))
            rr = (80 + 110 * ease_out(max(b, 0) / 0.4)) * s / 4
            ImageDraw.Draw(lay).ellipse((bx / 4 - rr, by / 4 - rr, bx / 4 + rr, by / 4 + rr), fill=(255, 215, 70, int(255 * bk)))
            lay = lay.filter(ImageFilter.GaussianBlur(10 * s + 1)).resize((W, H), Image.BILINEAR)
            fr = Image.alpha_composite(fr, lay)
            bloom = with_alpha(lay, 0.28 * bk)
        fr.alpha_composite(lg, (int(ox), int(oy)))
        if bloom is not None:
            fr = Image.alpha_composite(fr, bloom)
        if 0 < b < 0.7:
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            q = ease_out(b / 0.45)
            for i in range(7):
                a = -math.pi / 2 + (i - 3) * 0.42
                r0, r1 = (95 + 60 * q) * s, (120 + 110 * q) * s
                d.line((bx + r0 * math.cos(a), by + r0 * math.sin(a), bx + r1 * math.cos(a), by + r1 * math.sin(a)),
                       fill=(255, 230, 110, int(255 * (1 - ease(b / 0.7)))), width=max(3, int(9 * s)))
            fr = Image.alpha_composite(fr, lay)
        return fr

    def frame(self, t):
        fr = self.background(t)
        if t > 0.15:
            s, ang, shake, p = self.logo_state(t)
            cx, cy = self.center
            fr = self.draw_sticker(fr, t, cx + shake, cy + shake * 0.5, s, ang, glow=min(1, p))
        fr = fr.convert('RGB')
        u = t - self.t_hit
        if 0 < u < 0.2:
            fr = Image.blend(fr, Image.new('RGB', fr.size, (255, 255, 255)), 0.55 * (1 - u / 0.2))
        return fr

    def sfx(self):
        return [(0.0, sfx_riser(self.t_hit), 0.35), (self.t_hit, sfx_boom(), 0.85), (self.t_bulb, sfx_ding(), 0.9)]


# ---------------------------------------------------------------- background
def make_plate(cfg):
    """Stadium photo from the post with the design elements painted out, fitted to the top of a 9:16 frame."""
    import cv2
    key = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]
    path = os.path.join(CACHE, f'plate_{key}.png')
    if os.path.exists(path):
        return Image.open(path).convert('RGB')
    os.makedirs(CACHE, exist_ok=True)
    img = np.asarray(Image.open(os.path.join(HERE, cfg['post'])).convert('RGB'))[:cfg.get('crop_bottom', 10 ** 6)].copy()
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for x0, y0, x1, y1 in cfg.get('clear', []):
        mask[y0:y1, x0:x1] = 255
    small = cv2.resize(img, (w // 3, h // 3), interpolation=cv2.INTER_AREA)
    ms = cv2.resize(mask, (w // 3, h // 3), interpolation=cv2.INTER_NEAREST)
    inp = cv2.resize(cv2.inpaint(small, ms, 12, cv2.INPAINT_TELEA), (w, h), interpolation=cv2.INTER_CUBIC)
    inp = cv2.GaussianBlur(inp, (0, 0), 22)
    soft = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 30)[..., None]
    soft = np.clip(soft * 1.6, 0, 1)
    plate = img * (1 - soft) + inp * soft
    plate = cv2.GaussianBlur(plate.astype(np.uint8), (0, 0), 1.2)
    ph = 1500
    k = ph / h
    pw = int(w * k)
    pl = Image.fromarray(plate).resize((pw, ph), Image.LANCZOS)
    fx = int(cfg.get('focus_x', w / 2) * k)
    x0 = min(max(fx - W // 2, 0), max(pw - W, 0))
    pl = pl.crop((x0, 0, x0 + W, ph))
    canvas = Image.new('RGB', (W, H), NAVY)
    fade = np.clip((np.arange(ph) - (ph - 360)) / 360, 0, 1)[:, None]
    m = Image.fromarray(((1 - fade) * 255 * np.ones((1, W))).astype(np.uint8))
    canvas.paste(pl, (0, 0), m)
    a = np.asarray(canvas).astype(np.float32)
    yy = np.arange(H)[:, None, None]
    dark = 0.18 + 0.32 * np.clip(1 - yy / 650, 0, 1)        # darker at the top for the header / sticker
    a = a * (1 - dark) + np.array(NAVY) * dark
    out = Image.fromarray(a.astype(np.uint8))
    out.save(path)
    return out


# ---------------------------------------------------------------------- reel
class Reel:
    def __init__(self, cfg_path):
        self.cfg = cfg = json.load(open(cfg_path, encoding='utf-8'))
        voice, rate = cfg.get('voice', 'el-GR-NestorasNeural'), cfg.get('rate', '+10%')
        lines = [cfg.get('intro_line', 'Ήξερες ότι;')] + cfg['lines'] + [cfg.get('cta', 'Ακολούθησε το Κουπονάκι για περισσότερα!')]
        self.vo = [tts(l, voice, rate) for l in lines]
        self.intro = Intro()
        self.plate = make_plate(cfg['background'])
        self.timeline()
        self.build()
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.5), v=rnd.uniform(18, 60),
                           ph=rnd.uniform(0, 6.28), g=rnd.random() < 0.75) for _ in range(70)]
        self.sfx_events = []

    # ------------------------------------------------------------ timing
    def timeline(self):
        d = [len(v) / SR for v in self.vo]
        starts = [self.intro.t_hit + 0.3]
        t = T_INTRO + 0.45
        for i in range(1, len(self.vo) - 1):
            starts.append(t)
            t += d[i] + 0.4
        self.t_end = t - 0.3
        starts.append(t)
        self.vo_starts = starts
        self.total = starts[-1] + d[-1] + 1.1

    def at(self, spec):
        line, off = spec
        base = T_INTRO if line == 0 else self.vo_starts[min(line, len(self.vo_starts) - 2)]
        return base + off

    # ------------------------------------------------------------ layout
    def build(self):
        cfg = self.cfg
        self.events = []                                   # (time, kind) for SFX
        # header
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((380, int(kl.height * 380 / kl.width)), Image.LANCZOS)
        self.k_big = kl.resize((860, int(kl.height * 860 / kl.width)), Image.LANCZOS)
        self.pill = None
        if cfg.get('pill'):
            f = fnt('FiraSansExtraCondensed-Bold', 38)
            txt = cfg['pill']['text']
            tw = int(ImageDraw.Draw(Image.new('L', (1, 1))).textlength(txt, font=f))
            im = Image.new('RGBA', (tw + 56, 60), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((0, 0, im.width - 1, 59), 30, fill=LIME + (255,), outline=(220, 255, 180, 255), width=2)
            d.text((28, 6), txt, font=f, fill=(6, 30, 16, 255))
            self.pill = (im, self.at(cfg['pill'].get('at', [0, 0.5])))
            self.events.append((self.pill[1], 'pop'))
        # hero: crest on the right, headline on the left
        hero_top = 555
        crest = cfg.get('crest')
        col_w = 640 if crest else 980
        self.crest = None
        if crest:
            im = Image.open(os.path.join(HERE, crest['image'])).convert('RGBA')
            k = min(290 / im.width, 330 / im.height)
            im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
            t0 = self.at(crest['at'])
            stars = [star(64) for _ in range(crest.get('stars', 0))]
            self.crest = dict(im=im, t=t0, cx=870, cy=hero_top + 50 + im.height / 2 + (40 if stars else 0), stars=stars)
            self.events += [(t0, 'whoosh'), (t0 + 0.35, 'thud')] + [(t0 + 0.55 + 0.15 * i, 'pop') for i in range(len(stars))]
        self.heads = []
        y = hero_top
        hx = 60 + col_w / 2 if crest else W / 2
        for hl in cfg.get('headline', []):
            size = hl.get('max_size', 170)
            while size > 40:
                im = sticker_text(hl['text'], fnt('FiraSansExtraCondensed-Black', size), hl.get('color', 'white'),
                                  stroke=int(max(6, size * 0.075)), depth=int(max(5, size * 0.055)))
                if im.width <= col_w:
                    break
                size -= 6
            t0 = self.at(hl['at'])
            self.heads.append(dict(im=im, t=t0, cx=hx, cy=y + im.height / 2, dashes=hl.get('dashes')))
            self.events.append((t0 + 0.12, 'thud'))
            y += im.height - 22
        hero_bottom = max(y + 22, (self.crest['cy'] + self.crest['im'].height / 2 + 10) if self.crest else 0)
        self.subs = []
        if cfg.get('subtitle'):
            f = fnt('FiraSans-SemiBold', 46)
            t0 = self.at(cfg['subtitle']['at'])
            yy = hero_bottom + 18
            for i, im in enumerate(rich_lines(cfg['subtitle']['text'], f, 980, stroke=3)):
                self.subs.append(dict(im=im, t=t0 + 0.18 * i, cx=W / 2, cy=yy + im.height / 2))
                yy += im.height - 4
            hero_bottom = yy
        # panel (anchored to the bottom)
        self.build_panel(cfg['panel'])
        # middle zone: mascot + stats between hero and panel
        mid_top, mid_bot = hero_bottom + 10, self.panel['y0'] - 10
        self.mascot = None
        if cfg.get('mascot'):
            im = Image.open(os.path.join(HERE, cfg['mascot']['image'])).convert('RGBA')
            hgt = int(min(540, mid_bot + 60 - mid_top - 10))
            im = im.resize((int(im.width * hgt / im.height), hgt), Image.LANCZOS)
            t0 = self.at(cfg['mascot']['at'])
            self.mascot = dict(im=im, t=t0, cx=30 + im.width / 2, cy=mid_bot + 60 - hgt / 2)
            self.events += [(t0, 'whoosh'), (t0 + 0.4, 'pop')]
        self.stats = []
        if cfg.get('stats'):
            items = cfg['stats']['items']
            x0 = (self.mascot['cx'] + self.mascot['im'].width / 2 - 10) if self.mascot else 60
            x1 = W - 40
            gap, n = 18, len(items)
            cols = n if n <= 2 or (x1 - x0 - gap * (n - 1)) / n >= 190 else math.ceil(n / 2)
            rows = math.ceil(n / cols)
            cw = min(300, (x1 - x0 - gap * (cols - 1)) / cols)
            ch = 210 if rows == 1 else min(200, (mid_bot - mid_top - gap * (rows - 1)) / rows)
            gh = ch * rows + gap * (rows - 1)
            gy = (mid_top + mid_bot) / 2 - gh / 2
            sx = x0 + (x1 - x0 - (cw * cols + gap * (cols - 1))) / 2
            fl = fnt('FiraSansExtraCondensed-Bold', 34 if cw > 200 else 28)
            fv = fnt('FiraSansExtraCondensed-Black', int(min(118, ch * 0.56)))
            meas = ImageDraw.Draw(Image.new('L', (1, 1)))
            for i, it in enumerate(items):
                r, c = divmod(i, cols)
                t0 = self.at(it['at'])
                ls = fl.size
                while ls > 18 and meas.textlength(it['label'], font=fnt('FiraSansExtraCondensed-Bold', ls)) > cw - 28:
                    ls -= 2
                self.stats.append(dict(value=it['value'], label=it['label'], t=t0, cx=sx + cw * (c + .5) + gap * c,
                                       cy=gy + ch * (r + .5) + gap * r, w=int(cw), h=int(ch),
                                       fl=fnt('FiraSansExtraCondensed-Bold', ls), fv=fv))
                self.events.append((t0, 'pop'))
        # real photo card (pops in over the middle zone, replaces the stat cards)
        self.photo = None
        if cfg.get('photo'):
            ph = cfg['photo']
            src = Image.open(os.path.join(HERE, ph['image'])).convert('RGB')
            b = 12
            pw = ph.get('width', 860)
            phh = int(min(pw * src.height / src.width, mid_bot - mid_top + 40))
            frame = Image.new('RGBA', (pw + 2 * b, phh + 2 * b), (0, 0, 0, 0))
            ImageDraw.Draw(frame).rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), 30, fill=(246, 246, 240, 255))
            mask = Image.new('L', (pw, phh), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, phh - 1), 22, fill=255)
            glow, gp = glow_of(frame, 18, LIME)
            t0 = self.at(ph['at'])
            self.photo = dict(src=src, frame=frame, mask=mask, glow=glow, b=b, w=pw, h=phh, t=t0,
                              cx=W / 2 + 20, cy=(mid_top + mid_bot) / 2, rot=ph.get('rotate', -3))
            self.events += [(t0, 'whoosh'), (t0 + 0.3, 'thud')]
        # end card
        self.font_cta = fnt('FiraSans-SemiBold', 56)
        self.events += [(T_INTRO - 0.15, 'whoosh'), (self.t_end - 0.1, 'whoosh'), (self.t_end + 0.2, 'boom_soft')]

    def build_panel(self, p):
        x0, x1, y1 = 34, W - 34, H - 40
        pad = 34
        f_day, f_year = fnt('FiraSans-SemiBold', 36), fnt('FiraSansExtraCondensed-Black', 88)
        icon = calendar_icon(92)
        dw = 330
        title_w = (x1 - x0) - 2 * pad - dw - 40
        size = 96
        while True:
            f_t = fnt('FiraSansExtraCondensed-Black', size)
            tl = rich_lines(p['title'], f_t, 10 ** 5)
            if max(im.width for im in tl) <= title_w or size < 40:
                break
            size -= 4
        th = sum(im.height for im in tl) - 14 * (len(tl) - 1)
        row_h = max(150, th + 10)
        body = rich_lines(p.get('body', ''), fnt('FiraSans-Medium', 37), (x1 - x0) - 2 * pad) if p.get('body') else []
        body_h = sum(im.height + 4 for im in body)
        y0 = y1 - (pad + row_h + (24 + body_h if body else 0) + pad)
        self.panel = dict(x0=x0, x1=x1, y0=y0, y1=y1, xc=x0 + 2 * pad + dw, yc=y1 - (2 * pad + row_h), pad=pad, icon=icon,
                          dw=dw, row_h=row_h, f_day=f_day, f_year=f_year, day=p['day'], year=p['year'], title=tl, body=body,
                          t=self.at(p['at']), t_title=self.at(p.get('title_at', p['at'])), t_body=self.at(p.get('body_at', p['at'])))
        self.events += [(self.panel['t'], 'whoosh'), (self.panel['t_title'] - 0.3, 'whoosh'), (self.panel['t_title'], 'pop')]

    # ------------------------------------------------------------ drawing
    def particles(self, fr, t, alpha=0.55):
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for p in self.parts:
            y = (p['y'] - p['v'] * t) % H
            x = p['x'] + 14 * math.sin(t * 0.8 + p['ph'])
            a = int(alpha * 255 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2.3 + p['ph']))))
            r = p['r']
            d.ellipse((x - r, y - r, x + r, y + r), fill=((140, 255, 90) if p['g'] else (235, 255, 235)) + (a,))
        return Image.alpha_composite(fr, lay.filter(ImageFilter.GaussianBlur(0.8)))

    def beams(self, fr, t, k):
        if not hasattr(self, '_beam'):
            b = Image.new('L', (W // 2, H // 2), 0)
            ImageDraw.Draw(b).polygon([(0, 0), (W // 2, H * 0.32), (W * 0.32, H // 2)], fill=110)
            self._beam = b.filter(ImageFilter.GaussianBlur(40))
        for side in (0, 1):
            ang = 8 * math.sin(t * 0.6 + side * 2.0)
            m = self._beam.rotate(ang, center=(0, 0), resample=Image.BILINEAR)
            if side:
                m = m.transpose(Image.FLIP_LEFT_RIGHT)
            m = m.resize((W, H), Image.BILINEAR).point(lambda v: int(v * k * (0.75 + 0.25 * math.sin(t * 1.7 + side))))
            lay = Image.new('RGBA', (W, H), (225, 255, 215, 0))
            lay.putalpha(m)
            fr = Image.alpha_composite(fr, lay)
        return fr

    def draw_panel(self, fr, t):
        """Panel starts as a compact date card, widens for the title, grows upward for the body."""
        P = self.panel
        u = t - P['t']
        if u <= 0:
            return
        slide = (1 - ease_out(u / 0.6)) * 420
        wb = ease((t - (P['t_title'] - 0.35)) / 0.45)
        hb = ease((t - (P['t_body'] - 0.35)) / 0.45) if P['body'] else 0
        x0, xr = P['x0'], P['xc'] + (P['x1'] - P['xc']) * wb
        top, bot = P['yc'] + (P['y0'] - P['yc']) * hb + slide, P['y1'] + slide
        if top >= H:
            return
        a = min(1, u / 0.25)
        c = 46
        poly = [(x0, top), (xr - c, top), (xr, top + c), (xr, bot), (x0 + c, bot), (x0, bot - c)]
        g = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
        ImageDraw.Draw(g).line([(x / 2, y / 2) for x, y in poly + [poly[0]]], fill=LIME + (int(255 * a),), width=7, joint='curve')
        fr.alpha_composite(g.filter(ImageFilter.GaussianBlur(8)).resize((W, H), Image.BILINEAR))
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.polygon(poly, fill=(7, 18, 32, 242))
        d.line(poly + [poly[0]], fill=LIME + (255,), width=5, joint='curve')
        pad, dw, rh = P['pad'], P['dw'], P['row_h']
        dy0 = top + pad
        d.rounded_rectangle((x0 + pad, dy0, x0 + pad + dw, dy0 + rh), 22, fill=(14, 30, 48, 255), outline=(52, 74, 98, 255), width=2)
        if wb > 0.3:
            d.line((x0 + pad + dw + 20, dy0 + 6, x0 + pad + dw + 20, dy0 + rh - 6), fill=LIME + (int(255 * min(1, (wb - .3) / .4)),), width=4)
        v = u - 0.25
        if v > 0:
            ic = P['icon']
            lay.alpha_composite(with_alpha(ic, min(1, v / 0.3)), (int(x0 + pad + 22), int(dy0 + rh / 2 - ic.height / 2)))
            y = int(P['year'])
            yv = int(round(y - 25 * (1 - ease_out((v - 0.05) / 0.9)))) if v < 1.0 else y
            tx = x0 + pad + 22 + ic.width + 18
            al = int(255 * min(1, v / 0.3))
            d.text((tx, dy0 + rh / 2 - 62), P['day'], font=P['f_day'], fill=(255, 255, 255, al))
            d.text((tx - 3, dy0 + rh / 2 - 26), str(yv), font=P['f_year'], fill=LIME + (al,))
        fr.alpha_composite(with_alpha(lay, a))
        tx0 = x0 + pad + dw + 44
        yy = dy0 + rh / 2 - (sum(im.height for im in P['title']) - 14 * (len(P['title']) - 1)) / 2
        for i, im in enumerate(P['title']):
            v = t - P['t_title'] - 0.15 * i
            if v > 0:
                sc = 0.55 + 0.45 * ease_out_back(v / 0.4, 2.0)
                place(fr, im, tx0 + im.width / 2 * sc, yy + im.height / 2, sc, min(1, v / 0.15))
            yy += im.height - 14
        by = dy0 + rh + 24
        for i, im in enumerate(P['body']):
            v = t - P['t_body'] - 0.32 * i
            if v > 0:
                place(fr, im, x0 + pad + im.width / 2, by + im.height / 2 + 24 * (1 - ease_out(v / 0.4)), 1, min(1, v / 0.35))
            by += im.height + 4

    def draw_stat(self, fr, st, t):
        u = t - st['t']
        hide = 1 - ease((t - self.photo['t']) / 0.3) if self.photo else 1
        if u <= 0 or hide <= 0:
            return
        w, h = st['w'], st['h']
        card = Image.new('RGBA', (w + 60, h + 60), (0, 0, 0, 0))
        g = Image.new('RGBA', card.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).rounded_rectangle((30, 30, 30 + w, 30 + h), 28, outline=LIME + (255,), width=10)
        card.alpha_composite(g.filter(ImageFilter.GaussianBlur(10)))
        d = ImageDraw.Draw(card)
        d.rounded_rectangle((30, 30, 30 + w, 30 + h), 28, fill=(7, 18, 32, 236), outline=LIME + (255,), width=4)
        val = st['value']
        if val.isdigit():
            n = int(val)
            val = str(int(round(n * ease_out((u - 0.1) / 0.75)))) if u < 0.85 else val
        tw = d.textlength(val, font=st['fv'])
        d.text((30 + w / 2 - tw / 2, 30 + 6), val, font=st['fv'], fill=LIME + (255,))
        lw = d.textlength(st['label'], font=st['fl'])
        d.text((30 + w / 2 - lw / 2, 30 + h - 58), st['label'], font=st['fl'], fill=(255, 255, 255, 255))
        s = 0.3 + 0.7 * ease_out_back(u / 0.45, 2.0)
        place(fr, card, st['cx'], st['cy'] + 3 * math.sin(t * 2 + st['cx']), s, min(1, u / 0.15) * hide)

    def draw_photo(self, fr, t):
        P = self.photo
        u = t - P['t'] if P else -1
        if u <= 0:
            return
        src, w, h = P['src'], P['w'], P['h']
        z = 1 + 0.08 * ease(u / 6)                       # slow Ken Burns inside the frame
        cw = min(src.width, src.height * w / h) / z
        chh = cw * h / w
        x0, y0 = (src.width - cw) / 2 + 20 * ease(u / 6), (src.height - chh) / 2
        img = src.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + chh))
        card = P['frame'].copy()
        card.paste(img, (P['b'], P['b']), P['mask'])
        e = ease_out_back(u / 0.6, 1.6)
        rot = P['rot'] + 14 * (1 - ease_out(u / 0.6))
        s = 0.35 + 0.65 * e
        dy = 4 * math.sin(t * 1.6)
        place(fr, P['glow'], P['cx'], P['cy'] + dy, s, 0.8 * min(1, u / 0.3), rot=rot)
        place(fr, card, P['cx'], P['cy'] + dy, s, min(1, u / 0.15), rot=rot)

    def main_frame(self, t):
        z = 1 + 0.06 * ease((t - T_INTRO) / (self.total - T_INTRO))
        bw, bh = W / z, H / z
        bg = self.plate.resize((W, H), Image.BILINEAR, box=((W - bw) / 2, (H - bh) * 0.35, (W + bw) / 2, (H - bh) * 0.35 + bh))
        fr = bg.convert('RGBA')
        fr = self.beams(fr, t, 0.45)
        # cross-fade from the intro background
        x = (t - T_INTRO) / 0.55
        if x < 1:
            fr = Image.blend(self.intro.background(t).convert('RGBA'), fr, ease(x))
        for st in self.stats:
            self.draw_stat(fr, st, t)
        self.draw_photo(fr, t)
        # crest + stars + shine
        C = self.crest
        if C and t > C['t']:
            u = t - C['t']
            e = ease_out_back(u / 0.7, 1.4)
            fl = 8 * math.sin(2 * math.pi * 0.5 * u)
            im = C['im']
            sv = u - 0.9
            if 0 < sv < 0.7:
                im = im.copy()
                band = Image.new('L', im.size, 0)
                xx = -im.width * 0.6 + (im.width * 2.2) * ease(sv / 0.7)
                ImageDraw.Draw(band).polygon([(xx, 0), (xx + 70, 0), (xx - 90, im.height), (xx - 160, im.height)], fill=150)
                band = Image.fromarray(np.minimum(np.asarray(band.filter(ImageFilter.GaussianBlur(16))), np.asarray(im.getchannel('A'))))
                wl = Image.new('RGBA', im.size, (255, 255, 255, 0))
                wl.putalpha(band)
                im.alpha_composite(wl)
            gl, gp = glow_of(C['im'].resize((C['im'].width // 2, C['im'].height // 2)), 10, (120, 255, 80))
            gl = gl.resize((gl.width * 2, gl.height * 2), Image.BILINEAR)
            place(fr, gl, C['cx'] + 420 * (1 - e), C['cy'] + fl, max(e, 0.2), 0.6 * min(1, u / 0.3))
            place(fr, im, C['cx'] + 420 * (1 - e), C['cy'] + fl, max(e, 0.2), min(1, u / 0.2), rot=25 * (1 - e))
            for i, sim in enumerate(C['stars']):
                v = u - 0.55 - 0.15 * i
                if v > 0:
                    sx = C['cx'] + (i - (len(C['stars']) - 1) / 2) * 82
                    place(fr, sim, sx, C['cy'] - C['im'].height / 2 - 40 + fl, ease_out_back(v / 0.4, 2.5), 1,
                          rot=60 * (1 - ease_out(v / 0.5)))
        # headline
        for hd in self.heads:
            u = t - hd['t']
            if u <= 0:
                continue
            s = 0.25 + 0.75 * ease_out_back(u / 0.42, 2.2)
            place(fr, hd['im'], hd['cx'], hd['cy'], s, min(1, u / 0.12), rot=6 * (1 - ease_out(u / 0.4)))
            if hd.get('dashes') and u > 0.3:
                lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                d = ImageDraw.Draw(lay)
                q = ease_out((u - 0.3) / 0.35)
                for side in (-1, 1):
                    ex = hd['cx'] + side * (hd['im'].width / 2 + 8)
                    for j, a in enumerate((-0.45, 0, 0.45)):
                        r0, r1 = 14 + 20 * q, 30 + 50 * q
                        ang = (0 if side > 0 else math.pi) + a * side
                        d.line((ex + r0 * math.cos(ang), hd['cy'] + r0 * math.sin(ang),
                                ex + r1 * math.cos(ang), hd['cy'] + r1 * math.sin(ang)), fill=(255, 214, 30, 255), width=10)
                fr.alpha_composite(lay)
        for sb in self.subs:
            u = t - sb['t']
            if u > 0:
                place(fr, sb['im'], sb['cx'], sb['cy'] + 30 * (1 - ease_out(u / 0.45)), 1, min(1, u / 0.35))
        self.draw_panel(fr, t)
        # mascot
        M = self.mascot
        if M and t > M['t']:
            u = t - M['t']
            e = ease_out_back(u / 0.6, 1.5)
            bob = 10 * math.sin(2 * math.pi * 1.1 * u)
            place(fr, M['im'], M['cx'] - 360 * (1 - e), M['cy'] + 260 * (1 - e) + bob, 1, min(1, u / 0.2),
                  rot=-18 * (1 - e) + 3 * math.sin(2 * math.pi * 0.55 * u))
        # sticker flies from the intro position to the top
        x = ease((t - T_INTRO) / 0.7)
        s0, _, _, _ = self.intro.logo_state(T_INTRO)
        s = s0 + (0.56 - s0) * x
        if x >= 1:
            s = 0.56 * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t))
        fr = self.intro.draw_sticker(fr, t, W / 2, 880 + (325 - 880) * x, s, glow=0.9)
        # header
        u = t - (T_INTRO + 0.35)
        if u > 0:
            place(fr, self.k_small, 50 + self.k_small.width / 2, 92 - 120 * (1 - ease_out(u / 0.5)), 1, min(1, u / 0.3))
        if self.pill:
            u = t - self.pill[1]
            if u > 0:
                pim = self.pill[0]
                place(fr, pim, W - 44 - pim.width / 2 + 300 * (1 - ease_out_back(u / 0.5)), 92, 1, min(1, u / 0.2))
        return fr

    def end_card(self, fr, t):
        k = ease((t - self.t_end) / 0.5)
        if k <= 0:
            return fr
        fr = Image.alpha_composite(fr, Image.new('RGBA', fr.size, (3, 10, 22, int(205 * k))))
        p = ease_out_back((t - self.t_end - 0.05) / 0.55)
        if p > 0.02:
            fr = self.intro.draw_sticker(fr, 0, W / 2, 650, 0.7 * p, glow=k)
        p = ease_out_back((t - self.t_end - 0.25) / 0.55)
        if p > 0.02:
            g, gp = glow_of(self.k_big, 26, (70, 220, 50))
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
            fr = self.intro.frame(t).convert('RGBA')
            fr = self.particles(fr, t, 0.45)
        else:
            fr = self.main_frame(t)
            fr = self.end_card(fr, t)
            fr = self.particles(fr, t)
        fr = fr.convert('RGB')
        fo = ease((t - (self.total - 0.35)) / 0.35)
        return Image.blend(fr, Image.new('RGB', fr.size, (0, 0, 0)), fo) if fo > 0 else fr

    # ------------------------------------------------------------ audio / encode
    def audio(self):
        out = np.zeros(int((self.total + 1) * SR), np.float32)

        def add(t, x, g):
            i = int(t * SR)
            x = x[:max(0, len(out) - i)]
            out[i:i + len(x)] += x * g

        for t, x, g in self.intro.sfx():
            add(t, x, g)
        lib = {'pop': (sfx_pop, 0.22), 'thud': (sfx_thud, 0.45), 'whoosh': (lambda: sfx_whoosh(0.6), 0.22),
               'boom_soft': (lambda: sfx_boom(1.2), 0.32)}
        for t, kind in self.events:
            f, g = lib[kind]
            add(t, f(), g)
        for t, v in zip(self.vo_starts, self.vo):
            add(t, v, 1.0)
        out = out[:int(self.total * SR)]
        fade = int(0.35 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        out = np.tanh(out * 1.1) / np.tanh(1.1) * 0.95
        path = os.path.join(CACHE, 'mix.wav')
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
    r = Reel(sys.argv[1])
    if sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(r.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else os.path.join(CACHE, 'preview.png'))
        print('vo starts', [round(x, 2) for x in r.vo_starts], 'end card', round(r.t_end, 2), 'total', round(r.total, 2))
    else:
        r.render(sys.argv[2])
