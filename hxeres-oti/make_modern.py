#!/usr/bin/env python3
"""'Ήξερες ότι;' — MODERN theme (test). Same story engine as make_story.py, a completely different look.

    python3 make_modern.py configs/apollon_legia_modern.json ../videos/apollon_legia_modern.mp4
    python3 make_modern.py configs/apollon_legia_modern.json --preview 1,4,8 preview.png

Kept from make_story: the voice (word timings, rising questions), caption chunking, timings, audio ducking.
New look:
  * photos fill the top of the frame with slow push-ins and fade into a near-black base (no tilted cards)
  * Inter Display typography with tight tracking and masked slide-up reveals, timed to the spoken words
  * data-viz details: map with coordinates and a live distance counter, 0'-90' match timeline, rolling digits
  * pill-highlight captions, story-style progress bar, swipe-up transitions, subtle film grain
Scenes: date, trip, score, gallery, fact, plus the kinetic hook intro and the end card.
"""
import sys, os, json, math, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance, ImageChops
from make_video import (HERE, CACHE, W, H, FPS, SR, LIME, ease, ease_out, ease_out_back, with_alpha, place, glow_of,
                        sfx_pop, sfx_thud, sfx_whoosh, sfx_boom, sfx_riser)
from make_story import Story, norm, sfx_tick, odometer_strip, emoji_img, roll, step_value, fit_text, XC, CAP_Y

INTER = '/usr/share/fonts/opentype/inter/InterDisplay-{}.otf'
MONO = '/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-{}.ttf'
BG = (7, 9, 12)
WHITE = (255, 255, 255)
MUTED = (150, 158, 170)
ACC = (182, 255, 60)
INK = (8, 10, 14)
M = 80                       # side margin
TR = 0.42                    # swipe transition
_fonts = {}


def F(weight, size, mono=False):
    k = (weight, size, mono)
    if k not in _fonts:
        _fonts[k] = ImageFont.truetype((MONO if mono else INTER).format(weight), size)
    return _fonts[k]


def expo(x):
    x = min(max(x, 0.0), 1.0)
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def inout(x):
    x = min(max(x, 0.0), 1.0)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def text_img(text, font, color=WHITE, tracking=0, line_box=True):
    """Text on transparent. line_box keeps the font's full ascent/descent so words of a line share a baseline."""
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    asc, desc = font.getmetrics()
    ws = [d.textlength(ch, font=font) for ch in text] if tracking else None
    w = int(sum(ws) + tracking * max(len(text) - 1, 0)) if tracking else int(d.textlength(text, font=font))
    im = Image.new('RGBA', (w + 16, asc + desc + 8), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    if tracking:
        x = 4
        for ch, cw in zip(text, ws):
            dr.text((x, 4), ch, font=font, fill=color + (255,))
            x += cw + tracking
    else:
        dr.text((4, 4), text, font=font, fill=color + (255,))
    bb = im.getbbox()
    if bb is None:
        return im
    return im.crop(bb) if not line_box else im.crop((0, 0, bb[2] + 2, im.height))


def outline_img(text, font, color, width=4, alpha=1.0):
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, t, r, b = d.textbbox((0, 0), text, font=font, stroke_width=width)
    w, h = r - l + 8, b - t + 8
    a = Image.new('L', (w, h), 0)
    ImageDraw.Draw(a).text((4 - l, 4 - t), text, font=font, fill=255, stroke_width=width, stroke_fill=255)
    f = Image.new('L', (w, h), 0)
    ImageDraw.Draw(f).text((4 - l, 4 - t), text, font=font, fill=255)
    im = Image.new('RGBA', (w, h), color + (0,))
    im.putalpha(ImageChops.subtract(a, f).point(lambda v: int(v * alpha)))
    return im


def pill_img(text, size, fg=INK, bg=ACC, weight='Black', tracking=1, outline=False, mono=False):
    t = text_img(text, F(weight, size, mono), fg, tracking=tracking, line_box=False)
    px, py = int(size * 0.6), int(size * 0.45)
    im = Image.new('RGBA', (t.width + 2 * px, t.height + 2 * py), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if outline:
        d.rounded_rectangle((1, 1, im.width - 2, im.height - 2), im.height // 2, outline=bg + (255,), width=2)
    else:
        d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), im.height // 2, fill=bg + (255,))
    im.alpha_composite(t, (px, py))
    return im


def shadowed(im, radius=12, alpha=0.65):
    """Soft dark halo behind text for legibility over photos (box grows by the pad)."""
    pad = radius * 2
    out = Image.new('RGBA', (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    a = Image.new('L', out.size, 0)
    a.paste(im.getchannel('A'), (pad, pad))
    sh = Image.new('RGBA', out.size, (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: int(v * alpha)))
    out.alpha_composite(sh)
    out.alpha_composite(im, (pad, pad))
    return out, pad


def reveal(fr, im, x, y, p):
    """Masked slide-up: the image rises from behind the bottom edge of its own box."""
    e = expo(p)
    if e <= 0.002:
        return
    vis = int(round(im.height * e))
    if vis > 0:
        fr.alpha_composite(im.crop((0, 0, im.width, vis)), (int(x), int(y + im.height - vis)))


def dot_sprite(r, color, glow=0, glow_color=ACC):
    s = int((r + glow * 2) * 2 + 4)
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    if glow:
        g = Image.new('L', (s, s), 0)
        ImageDraw.Draw(g).ellipse((s / 2 - r - glow, s / 2 - r - glow, s / 2 + r + glow, s / 2 + r + glow), fill=150)
        lay = Image.new('RGBA', (s, s), glow_color + (0,))
        lay.putalpha(g.filter(ImageFilter.GaussianBlur(glow * 0.6)))
        im.alpha_composite(lay)
    ImageDraw.Draw(im).ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=color + (255,))
    return im


def digit_window(strip, ch, v, size, extra=26):
    """Rolling digit clipped to the glyph's own height, so neighbours never spill into other rows."""
    wh = int(0.74 * size) + extra
    y = int(round((v % 10) * ch + (ch - wh) / 2))
    return strip.crop((0, y, strip.width, y + wh)), (ch - wh) / 2


def haversine(a, b):
    p1, p2 = math.radians(a['lat']), math.radians(b['lat'])
    dp, dl = p2 - p1, math.radians(b['lon'] - a['lon'])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def project(a, b, box):
    """Two lat/lon points into a screen box, keeping their real relative direction (equirectangular)."""
    k = math.cos(math.radians((a['lat'] + b['lat']) / 2))
    pts = [(c['lon'] * k, -c['lat']) for c in (a, b)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / max(max(xs) - min(xs), 1e-6), (y1 - y0) / max(max(ys) - min(ys), 1e-6))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [((x0 + x1) / 2 + (px - mx) * s, (y0 + y1) / 2 + (py - my) * s) for px, py in pts]


def fmt_int(v):
    return f'{int(round(v)):,}'.replace(',', '.')


class Photo:
    """A photo pre-scaled to cover a W x ph region with a margin, for slow push-ins."""

    def __init__(self, img, ph, focus=(0.5, 0.45), margin=1.15):
        k = max(W * margin / img.width, ph * margin / img.height)
        c = img.resize((int(img.width * k) + 1, int(img.height * k) + 1), Image.LANCZOS)
        if k > 1.3:                                   # upscaled small photos: a touch of sharpening
            c = c.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        c = ImageEnhance.Contrast(ImageEnhance.Color(c).enhance(0.9)).enhance(1.05)
        self.c, self.ph, self.focus = c, ph, focus

    def at(self, u, z0=1.0, z1=1.07):
        z = z0 + (z1 - z0) * inout(min(max(u, 0), 1))
        cw, ch = self.c.size
        ww, wh = W / z, self.ph / z
        cx = min(max(self.focus[0] * cw, ww / 2), cw - ww / 2)
        cy = min(max(self.focus[1] * ch, wh / 2), ch - wh / 2)
        return self.c.resize((W, self.ph), Image.BILINEAR, box=(cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2))


class Modern(Story):
    def __init__(self, cfg_path):
        self.cfg = cfg = json.load(open(cfg_path, encoding='utf-8'))
        for k, v in getattr(self, 'CFG_DEFAULTS', {}).items():   # template defaults (template 3: the voice)
            cfg.setdefault(k, v)
        self.load_voice()
        self.team = cfg['team']
        self.tcol = tuple(self.team['color'])
        self.photo = Image.open(os.path.join(HERE, cfg['photo'])).convert('RGB')
        self.events, self.shakes, self.flashes = [], [], []
        self.timeline()
        self._shades, self._plates = {}, {}
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((int(kl.width * 40 / kl.height), 40), Image.LANCZOS)
        self.k_big = kl.resize((600, int(kl.height * 600 / kl.width)), Image.LANCZOS)
        self.series = self.series_tag()
        self.scenes = []
        for i, sc in enumerate(cfg['scenes']):
            line, T = i + 1, self.scene_t[i]
            self.scenes.append(dict(T=T, cfg=sc, draw=getattr(self, 'm_' + sc['type'])(sc, line, T)))
        self.intro_draw = self.m_intro()
        self.end_draw = self.m_end()
        self.starts = [0.0] + [s['T'] for s in self.scenes] + [self.t_end]
        self.events += [(s - 0.08, 'whoosh') for s in self.starts[1:]]
        self.build_captions()
        # soft, low-frequency grain that changes every 2nd frame: filmic, but still compresses well
        amp = cfg.get('grain', 3.0)
        self.noise = []
        for k in range(3) if amp else []:
            n = np.random.default_rng(k).normal(0, amp, (H // 2, W // 2)).astype(np.float32)
            n = np.asarray(Image.fromarray(n, 'F').resize((W, H), Image.BILINEAR))
            self.noise.append(np.round(n).astype(np.int16))

    # ---------------------------------------------------------------- shared pieces
    def seg_end(self, line):
        return self.scene_t[line] if line < len(self.scene_t) else self.t_end

    def shade_for(self, ph):
        """Top fade for the header, bottom fade from the photo into the base."""
        if ph not in self._shades:
            y = np.arange(H, dtype=np.float32)
            a = np.full(H, 0.10, np.float32)
            a = np.maximum(a, 0.70 * np.clip(1 - y / 380, 0, 1) ** 1.5)
            a = np.maximum(a, np.clip((y - (ph - 500)) / 500, 0, 1) ** 1.3)
            a[y >= ph] = 1.0
            im = Image.new('RGBA', (W, H), BG + (0,))
            im.putalpha(Image.fromarray((np.repeat(a[:, None], W, axis=1) * 255).astype(np.uint8)))
            self._shades[ph] = im
        return self._shades[ph]

    def dark_plate(self, path=None, opacity=0.2):
        """Near-black base: optional blurred photo, team-colour glow, dot grid, vignette."""
        key = (path, opacity)
        if key in self._plates:
            return self._plates[key]
        base = Image.new('RGB', (W, H), BG)
        if path:
            p = self.load_photo(path)
            k = max(W / p.width, H / p.height) * 1.05
            small = p.resize((max(1, int(p.width * k / 10)), max(1, int(p.height * k / 10))), Image.BILINEAR)
            big = small.filter(ImageFilter.GaussianBlur(4)).resize((int(p.width * k), int(p.height * k)), Image.BILINEAR)
            x0, y0 = (big.width - W) // 2, (big.height - H) // 2
            base = Image.blend(base, big.crop((x0, y0, x0 + W, y0 + H)), opacity)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        g = np.clip(1 - np.hypot((xx - W * 0.55) / (W * 0.95), (yy - H * 0.42) / (H * 0.5)), 0, 1) ** 2
        arr = np.asarray(base).astype(np.float32) + g[..., None] * np.array(self.tcol, np.float32) * 0.30
        v = np.clip(np.hypot((xx - W / 2) / (W * 0.8), (yy - H / 2) / (H * 0.7)) - 0.55, 0, 1)
        arr = arr * (1 - 0.6 * v[..., None])
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert('RGBA')
        dots = Image.new('L', (W, H), 0)
        d = ImageDraw.Draw(dots)
        for y in range(20, H, 40):
            for x in range(20, W, 40):
                d.ellipse((x - 1.4, y - 1.4, x + 1.4, y + 1.4), fill=34)
        lay = Image.new('RGBA', (W, H), WHITE + (0,))
        lay.putalpha(dots)
        im.alpha_composite(lay)
        self._plates[key] = im
        return im

    def photo_bg(self, fr, P, u, dim=0.0):
        img = P.at(u)
        if dim > 0:
            img = Image.blend(img, Image.new('RGB', img.size, BG), dim)
        fr.paste(img, (0, 0))
        fr.alpha_composite(self.shade_for(P.ph))

    def series_tag(self):
        txt = text_img(self.cfg.get('series', 'ΗΞΕΡΕΣ ΟΤΙ;'), F('SemiBold', 24, True), WHITE, tracking=4)
        im = Image.new('RGBA', (txt.width + 28, txt.height), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((0, txt.height // 2 - 7, 14, txt.height // 2 + 7), fill=ACC + (255,))
        im.alpha_composite(txt, (28, 0))
        return im

    def disp_words(self, li):
        """Spoken words of a line with the script's punctuation re-attached (e.g. 'Βαρσοβία;')."""
        src, base, pos, out = self.line_text[li], self.vo_starts[li], 0, []
        for w, a, b in self.vo[li][1]:
            j = src.find(w, pos)
            txt = w
            if j >= 0:
                k = j + len(w)
                while k < len(src) and src[k] in ',.;:!?·…':
                    k += 1
                txt, pos = src[j:k], k
            out.append((txt, base + a, base + b, norm(w)))
        return out

    def label_img(self, text, color=MUTED, size=26):
        return text_img(text, F('SemiBold', size, True), color, tracking=3)

    # ---------------------------------------------------------------- intro (kinetic hook)
    def m_intro(self):
        cfg = self.cfg
        P = Photo(self.load_photo(cfg.get('hook_photo')), cfg.get('hook_ph', 1120), tuple(cfg.get('hook_focus', (0.5, 0.45))))
        size = cfg.get('hook_size', 122)
        f, tr, sp = F('Black', size), -int(size * 0.025), int(size * 0.26)
        acc = {norm(w) for w in cfg.get('hook_accent', [])}
        words = self.disp_words(0)
        lines, cur, cw = [], [], 0
        for w, t0, t1, n in words:
            im = text_img(w, f, ACC if n in acc else WHITE, tracking=tr)
            im, pad = shadowed(im)
            if cur and cw + sp + im.width - 2 * pad > W - 2 * M:
                lines.append(cur)
                cur, cw = [], 0
            cur.append((im, t0))
            cw += (sp if len(cur) > 1 else 0) + im.width - 2 * pad
        if cur:
            lines.append(cur)
        pad = int(12 * 2)
        lh = int(size * 1.04)
        top = cfg.get('hook_bottom', 1330) - lh * len(lines) - int(size * 0.24)
        placed = []
        for li, row in enumerate(lines):
            x = M
            for im, t0 in row:
                placed.append((im, x - pad, top + li * lh - pad, t0))
                x += im.width - 2 * pad + sp
        T1 = self.t_intro
        self.events += [(0.0, 'riser')] + ([(words[0][1], 'thud')] if words else [])

        def draw(fr, t):
            self.photo_bg(fr, P, t / max(T1, 0.1), dim=cfg.get('hook_dim', 0.32))
            k = 1 - min(1, t / 0.6)
            if k > 0:
                fr.alpha_composite(Image.new('RGBA', (W, H), BG + (int(255 * k),)))
            for im, x, y, t0 in placed:
                reveal(fr, im, x, y, (t - (t0 - 0.06)) / 0.5)
        return draw

    # ---------------------------------------------------------------- date
    def m_date(self, sc, line, T):
        T1 = self.seg_end(line)
        P = Photo(self.load_photo(sc['photo']), sc.get('ph', 1150), tuple(sc.get('focus', (0.5, 0.45)))) if sc.get('photo') else None
        plate = None if P else self.dark_plate(sc.get('backdrop'), 0.18)
        tD, tM = self.at(line, sc.get('day_at', 0.0)), self.at(line, sc['month_at'])
        tY0, tY1 = self.at(line, sc['year_at']), self.at(line, sc['year_end'])
        lab = self.label_img(sc['label']) if sc.get('label') else None
        day = text_img(sc['day'], F('Black', sc.get('day_size', 300)), WHITE, tracking=-10, line_box=False)
        month = text_img(sc['month'], F('Black', 112), WHITE, tracking=-2)
        fy = F('Black', 112)
        cw = int(max(ImageDraw.Draw(Image.new('L', (1, 1))).textlength(str(d), font=fy) for d in range(10))) + 4
        ch = month.height
        strip = odometer_strip(fy, cw, ch, ACC)
        rolls = [dict(target=int(c), t0=tY0 + 0.07 * i, t1=tY1 + 0.05 * i, spins=1 + i) for i, c in enumerate(sc['year'])]
        y0 = sc.get('y', 760)
        ly, dy = y0, y0 + 44
        my = dy + day.height + 22
        yy = my + ch - 14
        for r in rolls:
            self.add_ticks(lambda tt, r=r: roll(tt, r['target'], r['t0'], r['t1'], r['spins']), r['t0'], r['t1'])
        self.events += [(tD, 'thud'), (tM, 'pop')]

        def draw(fr, t):
            u = (t - T) / max(T1 - T, 0.1)
            if P:
                self.photo_bg(fr, P, u)
            else:
                fr.paste(plate, (0, 0))
            if lab:
                reveal(fr, lab, M, ly, (t - (T + 0.12)) / 0.45)
            reveal(fr, day, M, dy, (t - (tD - 0.06)) / 0.55)
            reveal(fr, month, M, my, (t - (tM - 0.06)) / 0.5)
            a = min(1, max(0, (t - (tY0 - 0.3)) / 0.2))
            if a > 0:
                x = M
                for r in rolls:
                    dig, off = digit_window(strip, ch, roll(t, r['target'], r['t0'], r['t1'], r['spins']), 112)
                    fr.alpha_composite(with_alpha(dig, a), (x, int(yy + off)))
                    x += cw - 6
        return draw

    # ---------------------------------------------------------------- trip (map)
    def m_trip(self, sc, line, T):
        T1 = self.seg_end(line)
        A, B = sc['from'], sc['to']
        plate = self.dark_plate(sc.get('backdrop'), 0.16)
        (ax, ay), (bx, by) = project(A, B, tuple(sc.get('box', (170, 470, 910, 1040))))
        mx, my = (ax + bx) / 2, (ay + by) / 2
        L = math.hypot(bx - ax, by - ay)
        nx, ny = (by - ay) / L, -(bx - ax) / L
        if nx > 0:                                       # bulge to the left: keeps the labels clear
            nx, ny = -nx, -ny
        cx, cy = mx + nx * sc.get('bulge', 170), my + ny * sc.get('bulge', 170)

        def bez(q):
            return ((1 - q) ** 2 * ax + 2 * (1 - q) * q * cx + q * q * bx,
                    (1 - q) ** 2 * ay + 2 * (1 - q) * q * cy + q * q * by)
        N = 120
        pts = [bez(i / N) for i in range(N + 1)]
        faint = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(faint)
        for i in range(0, N, 3):
            x, y = pts[i]
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 255, 255, 70))
        t0, t1 = self.at(line, sc['fly_at']), self.at(line, sc['land_at'])
        dist = haversine(A, B)
        head = dot_sprite(8, WHITE, glow=22)
        cdot = dot_sprite(9, WHITE, glow=10)

        def city(c, side):
            name = text_img(c['name'], F('Black', 60), WHITE, tracking=-1)
            if c.get('flag'):                                # e.g. 🇨🇾 before the city name
                fl = emoji_img(c['flag'], 50)
                nm = Image.new('RGBA', (fl.width + 14 + name.width, name.height), (0, 0, 0, 0))
                cap_mid = int(4 + F('Black', 60).getmetrics()[0] - 0.36 * 60)
                nm.alpha_composite(fl, (0, max(0, cap_mid - fl.height // 2)))
                nm.alpha_composite(name, (fl.width + 14, 0))
                name = nm
            coord = text_img(f"{abs(c['lat']):.2f}°{'N' if c['lat'] >= 0 else 'S'}  {abs(c['lon']):.2f}°{'E' if c['lon'] >= 0 else 'W'}",
                             F('Medium', 24, True), MUTED, tracking=1)
            return dict(name=name, coord=coord, side=side)
        ca, cb = city(A, A.get('label', 'below')), city(B, B.get('label', 'right'))
        sub = text_img(B['sub'], F('Bold', 40), ACC) if B.get('sub') and sc.get('sub_style') != 'sticker' else None
        sub_st = None
        if B.get('sub') and sc.get('sub_style') == 'sticker':  # chunky sticker of the current style
            simg = fit_text(B['sub'], 'yellow', 420, 96)
            sx, sy = sc.get('sub_xy', (bx + 250, by + 190))
            sub_st = dict(im=simg, glow=glow_of(simg, 16, LIME)[0], x=sx, y=sy, rot=sc.get('sub_rot', -8))
        tSub = self.at(line, sc['sub_at']) if (sub is not None or sub_st is not None) else None
        plane = emoji_img(sc['plane'], sc.get('plane_size', 110)) if sc.get('plane') else None
        tag_y = sc.get('tag_y', 300)
        tag = pill_img(sc['tag'], 24, fg=ACC, bg=ACC, weight='SemiBold', tracking=2, outline=True, mono=True) if sc.get('tag') else None
        tTag = self.at(line, sc.get('tag_at', 0.2)) if tag is not None else None
        dlab = self.label_img('ΑΠΟΣΤΑΣΗ')
        self.events += [(T + 0.2, 'pop'), (t0, 'whoosh'), (t1, 'thud')]
        if tTag is not None:
            self.events.append((tTag, 'pop'))
        if tSub is not None:
            self.events.append((tSub, 'thud' if sub_st is not None else 'pop'))
        self.add_ticks(lambda tt: dist / 40 * ease(min(1, max(0, (tt - t0) / max(t1 - t0, 0.3)))), t0, t1)

        def label_at(fr, c, x, y, p, extra=None, pe=0):
            if c['side'] == 'below':
                lx, ly = x - c['name'].width / 2, y + 34
            else:
                lx, ly = x + 34, y - c['name'].height * 0.62
            reveal(fr, c['name'], lx, ly, p)
            reveal(fr, c['coord'], lx + 4, ly + c['name'].height - 6, p - 0.15)
            if extra is not None:
                reveal(fr, extra, lx + 2, ly + c['name'].height + c['coord'].height, pe)

        def draw(fr, t):
            fr.paste(plate, (0, 0))
            u = t - (T + 0.15)
            if u > 0:
                fr.alpha_composite(with_alpha(faint, min(1, u / 0.4)))
                place(fr, cdot, ax, ay, ease_out_back(u / 0.4, 2.0))
                label_at(fr, ca, ax, ay, u / 0.5)
            q = ease(min(1, max(0, (t - t0) / max(t1 - t0, 0.3))))
            if t > t0:
                k = max(2, int(q * N) + 1)
                path = pts[:k] + [bez(q)]
                glow = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
                ImageDraw.Draw(glow).line([(x / 2, y / 2) for x, y in path], fill=ACC + (200,), width=6)
                fr.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BILINEAR))
                lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                ImageDraw.Draw(lay).line(path, fill=ACC + (255,), width=5, joint='curve')
                fr.alpha_composite(lay)
                if t < t1 + 0.3:
                    x, y = bez(q)
                    fade = 1 - max(0, (t - t1) / 0.3)
                    if plane is not None:                    # ✈️ turned along the flight path
                        (xa, ya), (xb, yb) = bez(max(0, q - 0.02)), bez(min(1, q + 0.02))
                        ang = math.degrees(math.atan2(-(yb - ya), xb - xa))
                        place(fr, head, x, y, 0.8, 0.6 * fade)
                        place(fr, plane, x, y, 1, fade, rot=ang - 45)
                    else:
                        place(fr, head, x, y, 1, fade)
            v = t - t1
            if v > 0:
                ph = (v % 1.3) / 1.3
                r = 14 + 46 * ease_out(ph)
                ring = Image.new('RGBA', (int(2 * r + 8), int(2 * r + 8)), (0, 0, 0, 0))
                ImageDraw.Draw(ring).ellipse((4, 4, 4 + 2 * r, 4 + 2 * r), outline=ACC + (int(220 * (1 - ph)),), width=3)
                place(fr, ring, bx, by)
                place(fr, cdot, bx, by, ease_out_back(v / 0.4, 2.2))
                label_at(fr, cb, bx, by, v / 0.5, sub, (t - tSub) / 0.45 if sub is not None else 0)
            if sub_st is not None and t > tSub:
                w = t - tSub
                k = 1 + 1.3 * (1 - ease_out(w / 0.18, 3))
                place(fr, sub_st['glow'], sub_st['x'], sub_st['y'], k, 0.8 * min(1, w / 0.1), rot=sub_st['rot'])
                place(fr, sub_st['im'], sub_st['x'], sub_st['y'], k, min(1, w / 0.06), rot=sub_st['rot'])
            if tag is not None:
                reveal(fr, tag, M, tag_y, (t - tTag) / 0.45)
            if t > t0 - 0.2:
                a = min(1, (t - (t0 - 0.2)) / 0.3)
                fr.alpha_composite(with_alpha(dlab, a), (M, 1168))
                num = text_img(fmt_int(dist * q) + ' km', F('Black', 104), WHITE, tracking=-3)
                fr.alpha_composite(with_alpha(num, a), (M - 4, 1196))
        return draw

    # ---------------------------------------------------------------- score (+ match timeline)
    def make_timeline(self, sc, line):
        """0'-90' match bar: the playhead runs to the goal minute on the voice, then a marker + label pop."""
        tl_t = self.at(line, sc.get('timeline_at', 0.2))
        g = sc.get('goal')
        g_t = self.at(line, g['at']) if g else None
        g_lab = text_img(g['label'], F('Bold', 30, True), ACC, tracking=1) if g else None
        x0, x1, yb = M, W - M, sc.get('timeline_y', 1030)
        ticks = [(m, text_img(f"{m}'", F('Medium', 20, True), MUTED)) for m in range(0, 91, 15)]
        gdot = dot_sprite(11, ACC, glow=14)
        pdot = dot_sprite(7, WHITE)
        self.events.append((tl_t, 'pop'))
        if g:
            self.events.append((g_t, 'thud'))

        def xm(m):
            return x0 + (x1 - x0) * m / 90

        def draw(fr, t):
            a = min(1, max(0, (t - tl_t) / 0.35))
            if a > 0:                                    # timeline 0'-90'
                lay = Image.new('RGBA', (W, 80), (0, 0, 0, 0))
                d = ImageDraw.Draw(lay)
                d.rounded_rectangle((x0, 20, x1, 24), 2, fill=(255, 255, 255, int(60 * a)))
                for m, im in ticks:
                    d.line((xm(m), 14, xm(m), 30), fill=(255, 255, 255, int(90 * a)), width=2)
                    lay.alpha_composite(with_alpha(im, a), (int(min(max(xm(m) - im.width / 2, 0), W - im.width)), 38))
                gm = g['minute'] if g else 90
                mnow = gm * ease(min(1, max(0, (t - tl_t) / max((g_t or tl_t + 1) - tl_t, 0.3))))
                if mnow > 0.3:
                    d.rounded_rectangle((x0, 19, xm(mnow), 25), 3, fill=ACC + (int(255 * a),))
                fr.alpha_composite(lay, (0, yb - 22))
                if g and t >= g_t:
                    v = t - g_t
                    place(fr, gdot, xm(gm), yb, ease_out_back(v / 0.35, 2.4))
                    reveal(fr, g_lab, min(xm(gm) - g_lab.width / 2, W - M - g_lab.width), yb - 70, v / 0.4)
                else:
                    place(fr, pdot, xm(mnow), yb, 1, a)
        return draw

    def m_score(self, sc, line, T):
        T1 = self.seg_end(line)
        ph = sc.get('ph', 1000)
        P = Photo(self.load_photo(sc['photo']), ph, tuple(sc.get('focus', (0.5, 0.45))))
        fname, fdig = F('Black', 84), F('Black', 120)
        cw = int(max(ImageDraw.Draw(Image.new('L', (1, 1))).textlength(str(d), font=fdig) for d in range(10))) + 6
        ch = int(sum(fdig.getmetrics())) + 8
        strips = {'w': odometer_strip(fdig, cw, ch, WHITE), 'a': odometer_strip(fdig, cw, ch, ACC)}
        winner = sc.get('winner')

        def row(name, color):
            nm = text_img(name, fname, WHITE, tracking=-2)
            im = Image.new('RGBA', (nm.width + 34, nm.height), (0, 0, 0, 0))
            cap_top = int(4 + (fname.getmetrics()[0] - 0.73 * fname.size))
            ImageDraw.Draw(im).rounded_rectangle((0, cap_top, 9, cap_top + int(0.73 * fname.size)), 4, fill=color + (255,))
            im.alpha_composite(nm, (30, 0))
            return im
        rows = [dict(img=row(sc['home'], tuple(sc.get('home_color', (200, 200, 200)))), t=self.at(line, sc['home_at']),
                     y=sc.get('row_y', 1092), strip=strips['a' if winner == 'home' else 'w']),
                dict(img=row(sc['away'], tuple(sc.get('away_color', self.tcol))), t=self.at(line, sc['away_at']),
                     y=sc.get('row_y', 1092) + 116, strip=strips['a' if winner == 'away' else 'w'])]
        steps = [(self.at(line, s['at']), s['value']) for s in sc['steps']]
        digit_steps = [[(ts, v[k]) for ts, v in steps] for k in (0, 1)]
        for ds in digit_steps:
            self.add_ticks(lambda tt, ds=ds: step_value(tt, ds), ds[0][0], ds[-1][0] + 0.8)
        tl_draw = self.make_timeline(sc, line)
        self.events += [(r['t'], 'pop') for r in rows]
        if len(steps) > 1:
            self.events.append((steps[-1][0], 'boom'))
        def draw(fr, t):
            self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            tl_draw(fr, t)
            for k, r in enumerate(rows):                 # scoreboard rows
                reveal(fr, r['img'], M, r['y'], (t - r['t']) / 0.5)
                if t > r['t'] + 0.1:
                    ds = digit_steps[k]
                    v = step_value(t, ds) if t > ds[0][0] else ds[0][1] + 15
                    dig, off = digit_window(r['strip'], ch, v, fdig.size)
                    name_cap_mid = r['y'] + 4 + fname.getmetrics()[0] - 0.365 * fname.size
                    fr.alpha_composite(with_alpha(dig, min(1, (t - r['t'] - 0.1) / 0.2)),
                                       (W - M - cw, int(name_cap_mid - ch / 2 + off)))
        return draw

    # ---------------------------------------------------------------- gallery (hero moment)
    def m_gallery(self, sc, line, T):
        T1 = self.seg_end(line)
        ph = sc.get('ph', 1080)
        photos = [dict(P=Photo(self.load_photo(it['photo']), ph, tuple(it.get('focus', (0.5, 0.45)))),
                       t=self.at(line, it['at'])) for it in sc['photos']]
        y0 = sc.get('y', 960)
        lab = self.label_img(sc['label']['text'], ACC) if sc.get('label') else None
        tLab = self.at(line, sc['label']['at']) if lab is not None else None
        titles, y = [], y0 + 44
        for tl in sc.get('title', []):
            size = tl.get('size', 160)
            im = text_img(tl['text'], F('Black', size), ACC if tl.get('color') == 'acc' else WHITE, tracking=-int(size * 0.03))
            im, pad = shadowed(im)
            titles.append((im, self.at(line, tl['at']), y - pad))
            y += int(size * 1.0)
            self.events.append((titles[-1][1], 'thud' if len(titles) == 1 else 'pop'))
        if lab is not None:
            self.events.append((tLab, 'pop'))
        self.events += [(p['t'], 'whoosh') for p in photos[1:]]
        es = sc.get('emoji_sticker')
        eimg = emoji_img(es['emoji'], es.get('size', 170)) if es else None
        tE = self.at(line, es['at']) if es else None
        if es:
            self.events.append((tE, 'pop'))

        def draw(fr, t):
            u = (t - T) / max(T1 - T, 0.1)
            cur = max([i for i, p in enumerate(photos) if t >= p['t']] or [0])
            img = photos[cur]['P'].at(u)
            v = t - photos[cur]['t']
            if cur > 0 and v < 0.45:                      # next photo slides up inside the photo area
                prev = photos[cur - 1]['P'].at(u)
                e = expo(v / 0.45)
                yy = int(ph * (1 - e))
                prev.paste(img.crop((0, 0, W, ph - yy)), (0, yy))
                ImageDraw.Draw(prev).rectangle((0, max(0, yy - 3), W, yy + 3), fill=ACC)
                img = prev
            fr.paste(img, (0, 0))
            fr.alpha_composite(self.shade_for(ph))
            if lab is not None:
                reveal(fr, lab, M, y0, (t - tLab) / 0.45)
            for im, ta, yy in titles:
                reveal(fr, im, M - 4 - 24, yy, (t - (ta - 0.05)) / 0.55)
            if es and t > tE:
                v = t - tE
                place(fr, eimg, es['x'], es['y'], ease_out_back(v / 0.3, 2.4), min(1, v / 0.08),
                      rot=es.get('rot', 12) + 6 * math.sin(v * 9) * math.exp(-v * 2))
        return draw

    # ---------------------------------------------------------------- fact (statement)
    def m_fact(self, sc, line, T):
        T1 = self.seg_end(line)
        plate = self.dark_plate(sc.get('photo'), 0.24)
        big = outline_img(sc.get('big', '#1'), F('Black', 980), ACC, width=5, alpha=0.30)
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        crest = crest.resize((int(crest.width * 116 / crest.height), 116), Image.LANCZOS)
        kick = self.label_img(sc.get('kicker', ''), ACC, 28) if sc.get('kicker') else None
        size = sc.get('size', 118)
        lines, y = [], sc.get('y', 740)
        for wd in sc['words']:
            col = ACC if wd.get('color') in ('acc', 'green', 'yellow') else WHITE
            im = text_img(wd['text'], F('Black', size), col, tracking=-int(size * 0.03))
            lines.append((im, self.at(line, wd['at']), y))
            y += int(size * 1.02)
        stamp = pill_img(sc['stamp']['text'], 40, tracking=3) if sc.get('stamp') else None
        tSt = self.at(line, sc['stamp']['at']) if stamp is not None else None
        yst = y + 36
        self.events += [(lines[0][1], 'boom')] + [(ta, 'pop') for _, ta, _ in lines[1:]]
        if stamp is not None:
            self.events.append((tSt, 'thud'))

        def draw(fr, t):
            fr.paste(plate, (0, 0))
            u = t - T
            place(fr, big, W - big.width * 0.42 + 30 * (1 - ease_out(min(1, u / 4))), 560, 1, min(1, u / 0.6))
            reveal(fr, crest, M, 560, (t - (T + 0.1)) / 0.5)
            if kick is not None:
                reveal(fr, kick, M + crest.width + 26, 560 + crest.height / 2 - kick.height / 2, (t - (T + 0.25)) / 0.45)
            for im, ta, yy in lines:
                reveal(fr, im, M - 4, yy, (t - (ta - 0.05)) / 0.55)
            if stamp is not None and t > tSt:
                v = t - tSt
                k = 0.85 + 0.15 * ease_out_back(v / 0.4, 2.6)
                place(fr, stamp, M + stamp.width / 2, yst + stamp.height / 2, k, min(1, v / 0.1))
        return draw

    # ---------------------------------------------------------------- end card
    def m_end(self):
        c = self.cfg.get('end', {})
        plate = self.dark_plate(c.get('photo', self.cfg.get('hook_photo')), 0.2)
        lines = [text_img(l, F('Black', 84), WHITE, tracking=-2) for l in c.get('lines', ['Ποια ιστορική στιγμή', 'θες να δούμε;'])]
        pill = pill_img(c.get('pill', 'ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ ↓'), 40, tracking=2)
        small = text_img(c.get('small', 'FOLLOW ΓΙΑ ΠΕΡΙΣΣΟΤΕΡΑ «ΗΞΕΡΕΣ ΟΤΙ;»'), F('Medium', 24, True), MUTED, tracking=2)
        T0 = self.t_end
        self.events += [(T0 + 0.25, 'pop'), (T0 + 0.75, 'pop')]

        def draw(fr, t):
            fr.paste(plate, (0, 0))
            u = t - T0
            a = min(1, max(0, u / 0.35))
            place(fr, self.k_big, XC, 690, 0.94 + 0.06 * ease_out(min(1, u / 0.6)), a)
            for i, im in enumerate(lines):
                reveal(fr, im, XC - im.width / 2, 800 + i * 92, (u - 0.25 - 0.12 * i) / 0.5)
            v = u - 0.75
            if v > 0:
                k = (0.85 + 0.15 * ease_out_back(v / 0.4, 2.4)) * (1 + 0.02 * math.sin(2 * math.pi * 1.2 * v))
                place(fr, pill, XC, 1080, k, min(1, v / 0.1))
            fr.alpha_composite(with_alpha(small, min(1, max(0, (u - 1.0) / 0.4))), (int(XC - small.width / 2), 1170))
        return draw

    # ---------------------------------------------------------------- captions (pill highlight)
    def caption_img(self, words, active, size, emoji):
        size = self.cfg.get('caption_size', 64)
        while True:
            f = F('ExtraBold', size)
            ims = [text_img(w, f, INK if i == active else WHITE, tracking=-1) for i, w in enumerate(words)]
            em = emoji_img(emoji, int(size * 0.95)) if emoji else None
            gap = int(size * 0.24)
            tw = sum(im.width for im in ims) + gap * (len(ims) - 1) + ((em.width + gap) if em else 0)
            if tw <= 860 or size <= 40:
                break
            size -= 4
        padx = int(size * 0.2)
        hh = ims[0].height
        out = Image.new('RGBA', (tw + 2 * padx + 40, hh + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(out)
        x = 20 + padx
        for i, im in enumerate(ims):
            if i == active:
                d.rounded_rectangle((x - padx, 24 + int(size * 0.14), x + im.width + padx - 6, 24 + int(size * 1.13)),
                                    int(size * 0.26), fill=ACC + (255,))
            out.alpha_composite(im, (x, 20))
            x += im.width + gap
        if em:
            out.alpha_composite(em, (x, int(20 + 4 + size * 0.62 - em.height / 2)))
        sh = Image.new('RGBA', out.size, (0, 0, 0, 0))
        sh.putalpha(out.getchannel('A').filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.55)))
        res = Image.new('RGBA', (out.width, out.height + 6), (0, 0, 0, 0))
        res.alpha_composite(sh, (0, 6))
        res.alpha_composite(out)
        return res

    def draw_captions(self, fr, t):
        for c in self.captions:
            if c['t0'] <= t < c['t1']:
                k = 0
                for i, s in enumerate(c['starts']):
                    if t >= s - 0.03:
                        k = i
                u = t - c['t0']
                place(fr, c['imgs'][k], XC, CAP_Y + 12 * (1 - ease_out(min(1, u / 0.16))), 1, min(1, u / 0.08))
                return

    # ---------------------------------------------------------------- compositing
    def seg(self, k, t):
        fr = Image.new('RGBA', (W, H), BG + (255,))
        if k == 0:
            self.intro_draw(fr, t)
        elif k <= len(self.scenes):
            self.scenes[k - 1]['draw'](fr, t)
        else:
            self.end_draw(fr, t)
        return fr

    def captions_on(self, k):
        if k == 0:
            return not self.cfg.get('hook_kinetic', True)
        if k <= len(self.scenes):
            return self.scenes[k - 1]['cfg'].get('captions', True)
        return False

    def swipe(self, A, B, e):
        fr = Image.new('RGBA', (W, H), BG + (255,))
        dy = int(110 * e)
        fr.paste(A.crop((0, dy, W, H)), (0, 0))
        fr.alpha_composite(Image.new('RGBA', (W, H), (0, 0, 0, int(160 * e))))
        y0 = int(round(H * (1 - e)))
        if y0 < H:
            fr.paste(B.crop((0, 0, W, H - y0)), (0, y0))
            if y0 > 0:
                ImageDraw.Draw(fr).rectangle((0, max(0, y0 - 3), W, y0 + 3), fill=ACC + (255,))
        return fr

    def header(self, fr, t, logo=True):
        a = min(1, t / 0.5)
        lay = Image.new('RGBA', (W, 90), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.rounded_rectangle((M, 0, W - M, 6), 3, fill=(255, 255, 255, int(55 * a)))
        xp = M + (W - 2 * M) * min(1, t / self.total)
        if xp > M + 6:
            d.rounded_rectangle((M, 0, xp, 6), 3, fill=ACC + (int(255 * a),))
        fr.alpha_composite(lay, (0, 150))
        if logo:
            fr.alpha_composite(with_alpha(self.k_small, a), (M, 182))
            fr.alpha_composite(with_alpha(self.series, a), (W - M - self.series.width, 188))

    def grain(self, fr, n):
        if not self.noise:
            return fr.convert('RGB')
        arr = np.asarray(fr.convert('RGB'), dtype=np.int16) + self.noise[(n // 2) % len(self.noise)][..., None]
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGB')

    def frame(self, n):
        t = n / FPS
        k = max(i for i, s in enumerate(self.starts) if s <= t + 1e-9)
        u = t - self.starts[k]
        fr = self.swipe(self.seg(k - 1, t), self.seg(k, t), expo(u / TR)) if k > 0 and u < TR else self.seg(k, t)
        self.header(fr, t, logo=k < len(self.starts) - 1)
        if self.captions_on(k):
            self.draw_captions(fr, t)
        return self.grain(fr, n)

    # ---------------------------------------------------------------- audio
    def sfx_lib(self):
        return {'pop': (sfx_pop, 0.14), 'thud': (sfx_thud, 0.3), 'whoosh': (lambda: sfx_whoosh(0.45), 0.2),
                'tick': (sfx_tick, 0.05), 'boom': (lambda: sfx_boom(1.4), 0.28), 'riser': (lambda: sfx_riser(0.7), 0.2)}

    def audio(self):
        n = int((self.total + 2) * SR)
        vo, sfx = np.zeros(n, np.float32), np.zeros(n, np.float32)

        def add(t, x, g, dst):
            i = int(max(t, 0) * SR)
            x = x[:max(0, n - i)]
            dst[i:i + len(x)] += x * g

        lib = self.sfx_lib()
        for t, kind in self.events:
            f, g = lib[kind]
            add(t, f(), g, sfx)
        for t, (v, _) in zip(self.vo_starts, self.vo):
            add(t, v, 1.0, vo)

        def smooth(x, k):
            c = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
            y = (c[k:] - c[:-k]) / k
            return np.concatenate([np.full(k // 2, y[0]), y, np.full(len(x) - len(y) - k // 2, y[-1])]).astype(np.float32)
        rms = np.sqrt(np.maximum(smooth(vo ** 2, int(0.06 * SR)), 0))
        duck = smooth(1 - 0.5 * np.clip(rms / 0.06, 0, 1), int(0.12 * SR))
        out = (vo * 1.1 + sfx * duck)[:int(self.total * SR)]
        fade = int(0.12 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        out = np.tanh(out * 1.1) / np.tanh(1.1) * 0.95
        path = os.path.join(CACHE, 'modern_mix.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            s = (np.clip(out, -1, 1) * 32767).astype(np.int16)
            w.writeframes(np.repeat(s[:, None], 2, axis=1).tobytes())
        return path


if __name__ == '__main__':
    st = Modern(sys.argv[1])
    if sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(st.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else os.path.join(CACHE, 'preview.png'))
        print('vo starts', [round(x, 2) for x in st.vo_starts], 'scenes', [round(x, 2) for x in st.scene_t],
              'end card', round(st.t_end, 2), 'total', round(st.total, 2))
    else:
        st.render(sys.argv[2])
