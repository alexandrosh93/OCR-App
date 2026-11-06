#!/usr/bin/env python3
"""'Ήξερες ότι;' reel generator (Kouponaki).

    python3 make_video.py configs/apoel.json out.mp4
    python3 make_video.py configs/apoel.json --preview 0.6,1.8,4,8,12

Builds a 1080x1920 video: animated 'Ήξερες ότι;' intro (generated from the
sticker image, synthetic SFX), the post with camera moves that follow a Greek
voiceover (edge-tts), an optional pop-out 'callout' of a region, and an end
card with the kouponaki.com logo.

Config (JSON):
  post   : path to the post image (relative to this folder)
  lines  : VO sentences spoken over the post, one camera shot per line
  shots  : [{"from": [cx, cy, zoom], "to": [cx, cy, zoom], "callout": [x0, y0, x1, y1]?}]
           coordinates in post pixels; zoom 1 = post width fills the screen.
           Missing shots default to a slow push on the full post.
  intro_line, cta, voice, rate : optional overrides
"""
import sys, os, json, math, random, hashlib, subprocess, wave, ssl, asyncio
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '.cache')
W, H, FPS, SR = 1080, 1920, 30, 48000
F = 2  # scene supersampling
FONTS = ['/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
FLASH = (215, 255, 200)
T_INTRO = 2.6


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (x * 6 - 15) + 10)


def ease_out(x, p=3):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** p


def ease_out_back(x, s=1.7):
    x = min(max(x, 0.0), 1.0) - 1
    return x * x * ((s + 1) * x + s) + 1


def font(size):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def with_alpha(im, k):
    """Scale an RGBA image's opacity by k."""
    if k >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel('A').point(lambda v: int(v * k)))
    return im


def glow_of(im, radius, color):
    """Soft halo following the alpha of im; padded so the blur never clips. Returns (glow, pad)."""
    pad = int(radius * 3)
    a = Image.new('L', (im.width + 2 * pad, im.height + 2 * pad), 0)
    a.paste(im.getchannel('A'), (pad, pad))
    g = Image.new('RGBA', a.size, color + (0,))
    g.putalpha(a.filter(ImageFilter.GaussianBlur(radius)))
    return g, pad


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
    X *= ((f > lo) & (f < hi)) * 1.0
    y = np.fft.irfft(X, n)
    return y / (np.abs(y).max() + 1e-9)


def env_t(dur):
    return np.arange(int(dur * SR)) / SR


def sfx_riser(dur=0.55):
    t = env_t(dur)
    sweep = np.sin(2 * np.pi * (200 * t + 700 / (2 * dur) * t ** 2))
    return (band_noise(dur, 300, 6000) * 0.8 + 0.15 * sweep) * (t / dur) ** 2.5


def sfx_boom(dur=1.4, gain=1.0):
    t = env_t(dur)
    boom = np.sin(2 * np.pi * (45 * t + 10 * (1 - np.exp(-9 * t)))) * np.exp(-3.5 * t)
    hit = band_noise(dur, 60, 2500) * np.exp(-25 * t) * 0.55
    sparkle = band_noise(dur, 5000, 12000) * np.exp(-3 * t) * 0.07
    return (boom + hit + sparkle) * gain


def sfx_ding(dur=1.3):
    t = env_t(dur)
    att = np.clip(t / 0.005, 0, 1)
    a = sum(g * np.sin(2 * np.pi * f * t) for f, g in [(1568, 1), (2349, .5), (3136, .3), (4700, .12)])
    b = np.zeros_like(t)
    o = int(0.12 * SR)
    b[o:] = sum(g * np.sin(2 * np.pi * f * t[:-o]) for f, g in [(2093, 1), (3136, .4), (4186, .2)]) * np.exp(-4.5 * t[:-o])
    return (a * np.exp(-4.5 * t) * att * 0.3 + b * 0.2)


def sfx_whoosh(dur=0.7):
    t = env_t(dur)
    return band_noise(dur, 400, 5000) * np.sin(np.pi * t / dur) ** 2


def sfx_pop(dur=0.25):
    t = env_t(dur)
    return np.sin(2 * np.pi * (650 * t - 700 * t ** 2)) * np.exp(-28 * t)


# --------------------------------------------------------------------- intro
class Intro:
    """Animated 'Ήξερες ότι;' sticker reveal on a navy background."""

    def __init__(self):
        self.logo = Image.open(os.path.join(HERE, 'assets', 'hxeres_logo.png')).convert('RGBA')
        self.base_w = 930
        k = self.base_w / self.logo.width
        self.logo = self.logo.resize((self.base_w, int(self.logo.height * k)), Image.LANCZOS)
        g, pad = glow_of(self.logo.resize((self.logo.width // 2, self.logo.height // 2)), 16, (90, 255, 40))
        self.glow = g.resize((self.logo.width + 4 * pad, self.logo.height + 4 * pad), Image.BILINEAR)
        self.glow_pad = 2 * pad
        self.bulb = (int(905 * k), int(152 * k))       # bulb centre in logo px
        self.center = (W // 2, 880)
        self.t_hit = 0.55
        self.t_bulb = 1.7
        # background: radial navy gradient
        yy, xx = np.mgrid[0:H, 0:W]
        d = np.sqrt(((xx - W / 2) / (W * 0.8)) ** 2 + ((yy - 880) / (H * 0.55)) ** 2)
        d = np.clip(d, 0, 1)[..., None]
        c0, c1 = np.array([12, 44, 70]), np.array([2, 8, 18])
        self.bg = Image.fromarray((c0 * (1 - d) + c1 * d).astype(np.uint8), 'RGB')
        # light rays, half resolution, rotated per frame
        R = 1200
        rays = Image.new('L', (R, R), 0)
        dr = ImageDraw.Draw(rays)
        rnd = random.Random(5)
        for i in range(22):
            a0 = i / 22 * 2 * math.pi + rnd.uniform(-0.05, 0.05)
            wdt = rnd.uniform(0.03, 0.08)
            pts = [(R / 2, R / 2)] + [(R / 2 + R * math.cos(a), R / 2 + R * math.sin(a)) for a in (a0 - wdt, a0 + wdt)]
            dr.polygon(pts, fill=rnd.randint(90, 200))
        rd = np.asarray(rays.filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
        yy, xx = np.mgrid[0:R, 0:R]
        fall = np.clip(1 - np.sqrt((xx - R / 2) ** 2 + (yy - R / 2) ** 2) / (R * 0.55), 0, 1) ** 1.4
        self.rays = Image.fromarray((rd * fall).astype(np.uint8))
        rnd = random.Random(11)
        self.burst = [dict(a=rnd.uniform(0, 2 * math.pi), v=rnd.uniform(500, 1500), r=rnd.uniform(3, 8),
                           c=rnd.choice([(150, 255, 90), (240, 255, 240), (255, 220, 80)])) for _ in range(60)]

    def frame(self, t):
        fr = self.bg.copy().convert('RGBA')
        cx, cy = self.center
        u = t - self.t_hit
        # rays: build up before the hit, flare at the hit, settle
        k = 0.35 * ease(t / self.t_hit) if u < 0 else 0.25 + 0.55 * math.exp(-u * 4)
        rot = self.rays.rotate(t * 12, resample=Image.BILINEAR).resize((2400, 2400), Image.BILINEAR)
        rot = rot.crop((1200 - cx, 1200 - cy, 1200 - cx + W, 1200 - cy + H)).point(lambda v: int(v * k))
        ray_layer = Image.new('RGBA', (W, H), (110, 255, 70, 0))
        ray_layer.putalpha(rot)
        fr = Image.alpha_composite(fr, ray_layer)
        # energy ribbons behind the logo
        if u > 0:
            rk = ease(u / 0.6)
            lay = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            for j, (amp, lam, sp, dy) in enumerate([(60, 380, 2.2, -10), (45, 300, -1.7, 25), (75, 460, 1.3, 5)]):
                pts = [(x, cy / 2 + dy + amp * math.sin(2 * math.pi * x / lam * 2 + t * sp + j) *
                        math.sin(math.pi * x / (W / 2))) for x in range(0, W // 2 + 6, 6)]
                d.line(pts, fill=(120, 255, 80, int(200 * rk)), width=3)
            g = lay.filter(ImageFilter.GaussianBlur(5))
            lay = Image.alpha_composite(g, lay).resize((W, H), Image.BILINEAR)
            fr = Image.alpha_composite(fr, lay)
        # shockwave ring
        if 0 < u < 0.7:
            q = ease_out(u / 0.7)
            r = 160 + 1000 * q
            lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(lay).ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8),
                                        outline=(170, 255, 120, int(230 * (1 - q))), width=max(2, int(22 * (1 - q))))
            fr = Image.alpha_composite(fr, lay.filter(ImageFilter.GaussianBlur(3)))
        # logo
        if t > 0.15:
            p = (t - 0.15) / (self.t_hit - 0.15)
            s = 0.15 + 0.85 * ease_out_back(p, 2.2) if p < 1 else 1 + 0.012 * math.sin(2 * math.pi * 0.8 * (t - 0.9))
            ang = -14 * (1 - ease_out(p)) if p < 1 else 0
            shake = 16 * math.exp(-u * 9) * math.sin(u * 70) if u > 0 else 0
            lw, lh = int(self.logo.width * s), int(self.logo.height * s)
            if lw > 8:
                gk = 0.75 + 0.25 * math.sin(t * 3) if u > 0 else 0.6
                gp = int(self.glow_pad * s)
                g = with_alpha(self.glow, min(1, p) * gk).resize((lw + 2 * gp, lh + 2 * gp), Image.BILINEAR)
                lg = with_alpha(self.logo, min(1, p * 2.5)).resize((lw, lh), Image.BILINEAR)
                if ang:
                    g = g.rotate(ang, expand=True, resample=Image.BILINEAR)
                    lg = lg.rotate(ang, expand=True, resample=Image.BILINEAR)
                ox, oy = int(cx - lg.width / 2 + shake), int(cy - lg.height / 2 + shake * 0.5)
                fr.alpha_composite(g, (int(cx - g.width / 2 + shake), int(cy - g.height / 2 + shake * 0.5)))
                # bulb lights up ('idea!'): warm glow behind the sticker, faint bloom in front
                b = t - self.t_bulb
                bx = ox + (self.bulb[0] - self.logo.width / 2) * s + lg.width / 2
                by = oy + (self.bulb[1] - self.logo.height / 2) * s + lg.height / 2
                bloom = None
                if b > -0.05:
                    bk = min(1, math.exp(-max(b, 0) * 2.0) * 0.8 + 0.4) if b > 0 else 0.15
                    lay = Image.new('RGBA', (W // 4, H // 4), (0, 0, 0, 0))
                    rr = (80 + 110 * ease_out(max(b, 0) / 0.4)) / 4
                    ImageDraw.Draw(lay).ellipse((bx / 4 - rr, by / 4 - rr, bx / 4 + rr, by / 4 + rr),
                                                fill=(255, 215, 70, int(255 * bk)))
                    lay = lay.filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BILINEAR)
                    fr = Image.alpha_composite(fr, lay)
                    bloom = with_alpha(lay, 0.28 * bk)
                fr.alpha_composite(lg, (ox, oy))
                if bloom is not None:
                    fr = Image.alpha_composite(fr, bloom)
                if b > -0.05:
                    if b > 0:
                        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                        d = ImageDraw.Draw(lay)
                        q = ease_out(b / 0.45)
                        for i in range(7):
                            a = -math.pi / 2 + (i - 3) * 0.42
                            r0, r1 = 95 + 60 * q, 120 + 110 * q
                            d.line((bx + r0 * math.cos(a), by + r0 * math.sin(a), bx + r1 * math.cos(a),
                                    by + r1 * math.sin(a)), fill=(255, 230, 110, int(255 * (1 - ease(b / 0.7)))), width=9)
                        fr = Image.alpha_composite(fr, lay)
        # particle burst from the hit
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
        fr = fr.convert('RGB')
        if 0 < u < 0.2:
            fr = Image.blend(fr, Image.new('RGB', fr.size, (255, 255, 255)), 0.55 * (1 - u / 0.2))
        return fr

    def sfx(self):
        return [(0.0, sfx_riser(self.t_hit), 0.35), (self.t_hit, sfx_boom(), 0.85),
                (self.t_bulb, sfx_ding(), 0.9)]


# ---------------------------------------------------------------------- reel
class Reel:
    def __init__(self, cfg_path):
        cfg = json.load(open(cfg_path, encoding='utf-8'))
        self.cfg = cfg
        voice, rate = cfg.get('voice', 'el-GR-NestorasNeural'), cfg.get('rate', '+10%')
        self.post = Image.open(os.path.join(HERE, cfg['post'])).convert('RGB')
        self.Wp, self.Hp = self.post.size
        lines = [cfg.get('intro_line', 'Ήξερες ότι;')] + cfg['lines'] + \
                [cfg.get('cta', 'Ακολούθησε το Κουπονάκι για περισσότερα!')]
        self.vo = [tts(l, voice, rate) for l in lines]
        shots = cfg.get('shots', [])
        full = [self.Wp / 2, self.Hp / 2]
        self.shots = [shots[i] if i < len(shots) else {'from': full + [1.0], 'to': full + [1.06]}
                      for i in range(len(cfg['lines']))]
        self.intro = Intro()
        self.build_scene()
        self.build_timeline()
        self.kouponaki = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        kw = 860
        self.kouponaki = self.kouponaki.resize((kw, int(self.kouponaki.height * kw / self.kouponaki.width)), Image.LANCZOS)
        self.sticker = self.intro.logo.resize((640, int(self.intro.logo.height * 640 / self.intro.logo.width)), Image.LANCZOS)
        self.font = font(56)
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.5),
                           v=rnd.uniform(18, 60), ph=rnd.uniform(0, 6.28), g=rnd.random() < 0.75)
                      for _ in range(70)]

    def build_scene(self):
        """The post centred in a 9:16 canvas filled with a blurred, darkened copy of itself (supersampled)."""
        self.post_hi = self.post.resize((self.Wp * F, self.Hp * F), Image.LANCZOS)
        self.Ws, self.Hs = self.Wp, int(self.Wp * 16 / 9) + 40
        self.oy = (self.Hs - self.Hp) / 2
        sw, sh = self.Ws * F, self.Hs * F
        k = max(sw / self.Wp, sh / self.Hp) * 1.15
        bg = self.post.resize((int(self.Wp * k / 4), int(self.Hp * k / 4)), Image.BILINEAR)
        bg = bg.filter(ImageFilter.GaussianBlur(26)).resize((int(self.Wp * k), int(self.Hp * k)), Image.BILINEAR)
        x0, y0 = (bg.width - sw) // 2, (bg.height - sh) // 2
        bg = Image.blend(bg.crop((x0, y0, x0 + sw, y0 + sh)), Image.new('RGB', (sw, sh), (4, 14, 28)), 0.62)
        yy = np.arange(self.Hp * F)[:, None] * np.ones((1, self.Wp * F))
        fe = 60 * F
        ramp = np.minimum(np.clip(yy / fe, 0, 1), np.clip((self.Hp * F - 1 - yy) / fe, 0, 1))
        bg.paste(self.post_hi, (0, int(self.oy * F)), Image.fromarray((ramp * 255).astype(np.uint8)))
        self.scene = bg

    def build_timeline(self):
        d = [len(v) / SR for v in self.vo]
        self.t_intro = T_INTRO
        starts = [self.intro.t_hit + 0.3]
        t = self.t_intro + 0.35
        for i in range(1, len(self.vo) - 1):
            starts.append(t)
            t += d[i] + 0.35
        self.t_end = t - 0.25
        starts.append(t)
        self.vo_starts = starts
        self.total = starts[-1] + d[-1] + 1.1
        n = len(self.shots)
        self.seg = [(starts[i + 1], starts[i + 2] if i < n - 1 else self.t_end) for i in range(n)]
        full = (self.Wp / 2, self.Hp / 2, 1.0)
        kf = [(self.t_intro, *full), (self.t_intro + 0.25, *full)]
        for i, sh in enumerate(self.shots):
            s0, s1 = self.seg[i]
            kf.append((s0 - 0.15 + (0.9 if i == 0 else 0.75), *sh['from']))
            kf.append((s1 - 0.2, *sh['to']))
        kf.append((self.t_end + 0.9, *full))
        kf.append((self.total, self.Wp / 2, self.Hp / 2, 1.03))
        self.kf = kf

    def camera(self, t):
        kf = self.kf
        if t <= kf[0][0]:
            return kf[0][1:]
        for (t0, *a), (t1, *b) in zip(kf, kf[1:]):
            if t <= t1:
                e = ease((t - t0) / max(t1 - t0, 1e-6))
                z = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * e)
                return a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e, z
        return kf[-1][1:]

    def cam_box(self, t):
        cx, cy, z = self.camera(t)
        vw = self.Wp / z
        vh = vw * H / W
        cx = min(max(cx, vw / 2), self.Ws - vw / 2)
        cy = min(max(cy + self.oy, vh / 2), self.Hs - vh / 2)
        return cx - vw / 2, cy - vh / 2, vw, vh

    def to_screen(self, box, cam):
        L, T, vw, vh = cam
        sx, sy = W / vw, H / vh
        x0, y0, x1, y1 = box
        return (x0 - L) * sx, (y0 + self.oy - T) * sy, (x1 - L) * sx, (y1 + self.oy - T) * sy

    def particles(self, fr, t, alpha=0.55):
        lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        for p in self.parts:
            y = (p['y'] - p['v'] * t) % H
            x = p['x'] + 14 * math.sin(t * 0.8 + p['ph'])
            a = int(alpha * 255 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2.3 + p['ph']))))
            r = p['r']
            d.ellipse((x - r, y - r, x + r, y + r), fill=((140, 255, 90) if p['g'] else (235, 255, 235)) + (a,))
        return Image.alpha_composite(fr.convert('RGBA'), lay.filter(ImageFilter.GaussianBlur(0.8))).convert('RGB')

    def vignette(self):
        if not hasattr(self, '_vig'):
            yy, xx = np.mgrid[0:H, 0:W]
            d = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.68)) ** 2)
            self._vig = Image.fromarray((np.clip((d - 0.55) * 1.3, 0, 0.6) * 255).astype(np.uint8))
        return self._vig

    def callout(self, fr, t, cam):
        for i, sh in enumerate(self.shots):
            box = sh.get('callout')
            if not box:
                continue
            s0, s1 = self.seg[i]
            k = min(ease((t - (s0 + 0.55)) / 0.45), 1 - ease((t - (s1 - 0.1)) / 0.4))
            if k <= 0:
                continue
            fr = Image.blend(fr, Image.new('RGB', fr.size, (2, 8, 16)), 0.55 * k)
            x0, y0, x1, y1 = self.to_screen(box, cam)
            pop = 1 + 0.07 * ease_out_back((t - (s0 + 0.55)) / 0.6) * (1 - ease((t - (s1 - 0.1)) / 0.4))
            w, h = (x1 - x0) * pop, (y1 - y0) * pop
            px, py = int((x0 + x1) / 2 - w / 2), int((y0 + y1) / 2 - h / 2)
            crop = self.post_hi.crop(tuple(int(v * F) for v in box)).resize((int(w), int(h)), Image.LANCZOS)
            glow = Image.new('RGBA', fr.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle((px - 6, py - 6, px + w + 6, py + h + 6), 34,
                                                   outline=(110, 255, 60, int(230 * k)), width=8)
            fr = Image.alpha_composite(fr.convert('RGBA'), glow.filter(ImageFilter.GaussianBlur(14))).convert('RGB')
            m = Image.new('L', crop.size, 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, crop.width - 1, crop.height - 1), 30, fill=int(255 * k))
            fr.paste(crop, (px, py), m)
        return fr

    def end_card(self, fr, t):
        k = ease((t - self.t_end) / 0.5)
        if k <= 0:
            return fr
        fr = Image.blend(fr, Image.new('RGB', fr.size, (3, 10, 22)), 0.78 * k).convert('RGBA')
        for img, cy, delay in [(self.sticker, 650, 0.05), (self.kouponaki, 1010, 0.25)]:
            p = ease_out_back((t - self.t_end - delay) / 0.55)
            if p <= 0.02:
                continue
            w, h = int(img.width * p), int(img.height * p)
            im = img.resize((w, h), Image.BILINEAR)
            g, gp = glow_of(im, 26, (70, 220, 50))
            pos = (W // 2 - w // 2, cy - h // 2)
            fr.alpha_composite(with_alpha(g, 0.55 * k), (pos[0] - gp, pos[1] - gp))
            fr.alpha_composite(im, pos)
        q = ease((t - self.t_end - 0.6) / 0.45)
        if q > 0:
            lay = Image.new('RGBA', fr.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(lay)
            txt = 'Ακολούθησε για περισσότερα'
            tw = d.textlength(txt, font=self.font)
            d.text((W / 2 - tw / 2, 1130 + 30 * (1 - q)), txt, font=self.font, fill=(255, 255, 255, int(255 * q)))
            fr = Image.alpha_composite(fr, lay)
        return fr.convert('RGB')

    def frame(self, n):
        t = n / FPS
        if t < self.t_intro:
            fr = self.intro.frame(t)
            fr = self.particles(fr, t, 0.45)
            f = ease((t - (self.t_intro - 0.2)) / 0.2)
            return Image.blend(fr, Image.new('RGB', fr.size, FLASH), 0.75 * f) if f > 0 else fr
        cam = self.cam_box(t)
        L, T, vw, vh = cam
        fr = self.scene.resize((W, H), Image.BILINEAR, box=(L * F, T * F, (L + vw) * F, (T + vh) * F))
        fr = self.callout(fr, t, cam)
        fr.paste((0, 0, 0), (0, 0, W, H), self.vignette())
        fr = self.end_card(fr, t)
        fr = self.particles(fr, t)
        f = 1 - ease((t - self.t_intro) / 0.3)
        if f > 0:
            fr = Image.blend(fr, Image.new('RGB', fr.size, FLASH), 0.75 * f)
        fo = ease((t - (self.total - 0.35)) / 0.35)
        return Image.blend(fr, Image.new('RGB', fr.size, (0, 0, 0)), fo) if fo > 0 else fr

    def audio(self):
        out = np.zeros(int((self.total + 1) * SR), np.float32)

        def add(t, x, g):
            i = int(t * SR)
            x = x[:max(0, len(out) - i)]
            out[i:i + len(x)] += x * g

        for t, x, g in self.intro.sfx():
            add(t, x, g)
        add(self.t_intro - 0.35, sfx_whoosh(0.7), 0.3)
        add(self.t_end - 0.1, sfx_whoosh(0.8), 0.3)
        add(self.t_end + 0.2, sfx_boom(1.2), 0.35)
        for i, sh in enumerate(self.shots):
            if sh.get('callout'):
                add(self.seg[i][0] + 0.55, sfx_pop(), 0.3)
        for t, v in zip(self.vo_starts, self.vo):
            add(t, v, 1.0)
        out = out[:int(self.total * SR)]
        fade = int(0.35 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        out = np.tanh(out * 1.1) / np.tanh(1.1) * 0.95       # soft limiter
        path = os.path.join(CACHE, 'mix.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            s = (np.clip(out, -1, 1) * 32767).astype(np.int16)
            w.writeframes(np.repeat(s[:, None], 2, axis=1).tobytes())
        return path

    def render(self, out):
        mix = self.audio()
        nf = int(round(self.total * FPS))
        cmd = ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
               '-r', str(FPS), '-i', '-', '-i', mix, '-map', '0:v', '-map', '1:a',
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-profile:v', 'high',
               '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', out]
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
        g = Image.new('RGB', (270 * len(ts), 480))
        for i, t in enumerate(ts):
            g.paste(r.frame(int(t * FPS)).resize((270, 480)), (270 * i, 0))
        dst = sys.argv[4] if len(sys.argv) > 4 else os.path.join(CACHE, 'preview.png')
        g.save(dst)
        print('vo starts', [round(x, 2) for x in r.vo_starts], 'end card', round(r.t_end, 2), 'total', round(r.total, 2))
    else:
        r.render(sys.argv[2])
