#!/usr/bin/env python3
"""'Ήξερες ότι;' — TikTok-editor style reel (CapCut-like edit) built from a real photo + a fact.

    python3 make_tiktok.py configs/anorthosis_edit.json ../videos/anorthosis_edit.mp4
    python3 make_tiktok.py configs/anorthosis_edit.json --preview 1,3,6,9 preview.png

The video is an edit decision list ("shots" in the config): each shot starts on a spoken word and has
  type : photo (the real photo full-width, camera crop/zoom) | date (VHS look, flip-clock year) |
         crest (crest slam on rays) | score (scoreboard with rolling digits) | text (kinetic words) | end
  in   : cut | zoomblur | whip | glitch | flash | rewind   (the transition into the shot)
  stickers: emoji / plate stickers that pop on a word, punch_at: quick punch-in zooms on words.
On top: brand sticker pop + header, CapCut-style word-by-word captions, screen shake, SFX on every hit.
"""
import sys, os, json, math, random, subprocess, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageEnhance
from make_video import (HERE, CACHE, W, H, FPS, SR, NAVY, INK, LIME, fnt, ease, ease_out, ease_out_back, with_alpha,
                        glow_of, place, calendar_icon, Intro, band_noise, env_t, sfx_pop, sfx_thud, sfx_whoosh,
                        sfx_boom, sfx_ding)
from make_story import (Story, tts_words, tighten, fit_text, plain_text, shade, emoji_img, odometer_strip, tile_parts,
                        digit_tile, roll, step_value, sfx_tick, sfx_confetti, XC, TEXT_W, LOGO_Y, YELLOW)

PHOTO_Y = 880          # centre line of the full-width photo
CAP_Y_EDIT = 1290      # captions sit on the lower part of the photo, inside the safe area
STICK_Y, STICK_S = 330, 0.36
RED = (210, 28, 48)


# --------------------------------------------------------------------- sfx
def sfx_vboom(dur=1.3):
    """Deep cinematic boom for the big hits."""
    t = env_t(dur)
    x = np.sin(2 * np.pi * (38 * t + 5 * (1 - np.exp(-6 * t)))) * np.exp(-2.6 * t)
    return np.tanh(x * 2.2) * 0.8 + band_noise(dur, 40, 500) * np.exp(-14 * t) * 0.45


def sfx_glitch(dur=0.3):
    t = env_t(dur)
    q = np.round(band_noise(dur, 300, 9000) * 5) / 5                     # bit-crushed noise
    gate = (np.sin(2 * np.pi * 34 * t) > -0.2).astype(np.float32)
    return q * gate * np.exp(-5 * t) * 0.7


def sfx_rewind(dur=0.8):
    t = env_t(dur)
    f = 700 + 900 * t / dur + 260 * np.sin(2 * np.pi * 7 * t)            # tape spinning up
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = 2 * ((ph / (2 * np.pi)) % 1) - 1
    return (saw * 0.3 + band_noise(dur, 1500, 7000) * 0.35) * np.sin(np.pi * t / dur) ** 0.6


def sfx_shutter(dur=0.12):
    t = env_t(dur)
    out = band_noise(dur, 1500, 9000) * np.exp(-t * 90)
    i = int(0.055 * SR)
    out[i:] += (band_noise(dur, 800, 6000) * np.exp(-t * 120))[:len(out) - i] * 0.7
    return out


# ------------------------------------------------------------- image fx
def zoom(img, s, cx=W / 2, cy=H / 2):
    s = max(s, 1.0)
    return img.resize((W, H), Image.BILINEAR, box=(cx - W / 2 / s, cy - H / 2 / s, cx + W / 2 / s, cy + H / 2 / s))


def hblur(img, k=14):
    return img.resize((W // k, H), Image.BILINEAR).resize((W, H), Image.BILINEAR)


def roll_x(img, dx):
    return Image.fromarray(np.roll(np.asarray(img), int(dx), axis=1))


def glitch_fx(img, amt, seed):
    a = np.asarray(img.convert('RGB')).copy()
    d = int(26 * amt)
    if d:
        a[..., 0] = np.roll(a[..., 0], d, axis=1)
        a[..., 2] = np.roll(a[..., 2], -d, axis=1)
    rnd = random.Random(seed)
    for _ in range(7):
        y0 = rnd.randint(0, H - 40)
        h = rnd.randint(14, 110)
        a[y0:y0 + h] = np.roll(a[y0:y0 + h], int(rnd.randint(-90, 90) * amt), axis=1)
    return Image.fromarray(a).convert('RGBA')


def scanlines(alpha=46):
    m = np.zeros((H, W), np.uint8)
    m[::4] = alpha
    m[1::4] = alpha // 2
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    lay.putalpha(Image.fromarray(m))
    return lay


def tri(size, color, left=False):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    pts = [(size, 0), (0, size / 2), (size, size)] if left else [(0, 0), (size, size / 2), (0, size)]
    ImageDraw.Draw(im).polygon(pts, fill=color + (255,))
    return im


class Edit(Story):
    def __init__(self, cfg_path):
        self.cfg = cfg = json.load(open(cfg_path, encoding='utf-8'))
        voice = cfg.get('voice', 'el-GR-NestorasNeural')
        rate, pitch, fx = cfg.get('rate', '+10%'), cfg.get('pitch', '+0Hz'), cfg.get('voice_fx', False)
        lines = [cfg['hook']] + cfg['lines'] + [cfg['cta']]
        lines = [l if isinstance(l, dict) else {'text': l} for l in lines]
        self.line_text = [l['text'] for l in lines]
        self.vo = [tighten(*tts_words(l['text'], l.get('voice', voice), l.get('rate', rate), l.get('pitch', pitch), fx),
                           max_pause=cfg.get('max_pause', 0.22)) for l in lines]
        self.intro = Intro()
        self.team = cfg['team']
        self.tcol = tuple(self.team['color'])
        self.photo = Image.open(os.path.join(HERE, cfg['photo'])).convert('RGB')
        self.events, self.shakes, self.flashes = [], [], []
        self.cap_y = CAP_Y_EDIT
        self.timeline()
        self.build_backdrop()
        self.prepare_source()
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((330, int(kl.height * 330 / kl.width)), Image.LANCZOS)
        self.k_big = kl.resize((760, int(kl.height * 760 / kl.width)), Image.LANCZOS)
        self.k_glow, _ = glow_of(self.k_big, 26, (70, 220, 50))
        self.build_end_card()
        self.scan = scanlines()
        self.build_shots()
        self.build_captions()
        self.events += [(0.05, 'boom'), (self.intro.t_bulb, 'ding')]
        self.shakes.append((0.05, 14))
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.0), v=rnd.uniform(18, 60),
                           ph=rnd.uniform(0, 6.28)) for _ in range(50)]

    # ---------------------------------------------------------------- timing
    def timeline(self):
        d = [len(a) / SR for a, _ in self.vo]
        starts = [self.cfg.get('hook_start', 0.3)]
        t = starts[0] + d[0] + 0.35
        for i in range(1, len(self.vo)):
            starts.append(t)
            t += d[i] + 0.35
        self.vo_starts = starts
        self.total = starts[-1] + d[-1] + self.cfg.get('tail', 1.0)
        self.t_end = self.total + 1                      # Story's end card is replaced by the 'end' shot

    # ---------------------------------------------------------------- photo
    def prepare_source(self):
        p = ImageEnhance.Color(ImageEnhance.Contrast(self.photo).enhance(1.08)).enhance(1.12)
        self.src_hi = p.resize((p.width * 3, p.height * 3), Image.LANCZOS)
        self.ph_h = W * p.height / p.width

    def paste_photo(self, fr, fx, fy, S, dim=0.0):
        """The real photo full-width (S=1) or punched in (S>1), focus point (fx, fy) on the centre line."""
        Wd, Hd = W * S, self.ph_h * S
        left = min(0.0, max(W - Wd, W / 2 - fx * Wd))
        top = PHOTO_Y - fy * Hd
        vx0, vy0, vx1, vy1 = max(0, left), max(0, top), min(W, left + Wd), min(H, top + Hd)
        w, h = int(round(vx1 - vx0)), int(round(vy1 - vy0))
        if w < 2 or h < 2:
            return
        SW, SH = self.src_hi.size
        box = ((vx0 - left) / Wd * SW, (vy0 - top) / Hd * SH, (vx1 - left) / Wd * SW, (vy1 - top) / Hd * SH)
        img = self.src_hi.resize((w, h), Image.BILINEAR, box=box)
        if dim > 0:
            img = Image.blend(img, Image.new('RGB', img.size, (0, 0, 0)), dim)
        ramp = np.ones(h, np.float32)
        f = min(46, h // 3)
        if top > 0:
            ramp[:f] = np.minimum(ramp[:f], np.linspace(0, 1, f))
        if top + Hd < H:
            ramp[-f:] = np.minimum(ramp[-f:], np.linspace(1, 0, f))
        fr.paste(img, (int(vx0), int(vy0)), Image.fromarray((np.repeat(ramp[:, None], w, axis=1) * 255).astype(np.uint8)))

    # ---------------------------------------------------------------- shots
    def build_shots(self):
        self.shots = [dict(sh, T=self.at(sh['line'], sh.get('at', 0))) for sh in self.cfg['shots']]
        sfx = {'zoomblur': 'whoosh', 'whip': 'whoosh', 'glitch': 'glitch', 'rewind': 'rewind', 'flash': 'boom',
               'cut': 'shutter'}
        for i, s in enumerate(self.shots):
            s['T1'] = self.shots[i + 1]['T'] if i + 1 < len(self.shots) else self.total + 1
            s['_punch'] = [self.at(s['line'], p) for p in s.get('punch_at', [])]
            for tp in s['_punch']:
                self.events.append((tp, 'thud'))
                self.shakes.append((tp, 9))
            getattr(self, 'prep_' + s['type'])(s)
            s['_stk'] = [self.prep_sticker(st, s['line']) for st in s.get('stickers', [])]
            if i:
                kind = s.get('in', 'cut')
                self.events.append((s['T'] - (0.1 if kind in ('zoomblur', 'whip') else 0.02), sfx[kind]))
                if kind in ('flash', 'glitch'):
                    self.shakes.append((s['T'], 10))

    def shot_at(self, t):
        i = 0
        for k, s in enumerate(self.shots):
            if s['T'] <= t:
                i = k
        return i

    def shot_frame(self, s, t):
        fr = self.backdrop(t)
        getattr(self, 'draw_' + s['type'])(fr, s, t)
        for k in s['_stk']:
            self.draw_sticker(fr, k, t)
        return fr

    def cam(self, s, t):
        p = ease((t - s['T']) / max(s['T1'] - s['T'], 0.3))
        a, b = s['from'], s.get('to', s['from'])
        S = math.exp(math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * p)
        for tp in s['_punch']:
            if t > tp:
                S *= 1 + 0.12 * ease_out(min(1, (t - tp) / 0.12))
        return a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p, S

    # photo ------------------------------------------------------------
    def prep_photo(self, s):
        pass

    def draw_photo(self, fr, s, t):
        fx, fy, S = self.cam(s, t)
        self.paste_photo(fr, fx, fy, S, s.get('dim', 0.0))

    # stickers ---------------------------------------------------------
    def prep_sticker(self, st, line):
        if 'plate' in st:
            col = tuple(st.get('color', RED))
            txt = plain_text(st['plate'], fnt('FiraSansExtraCondensed-Black', st.get('size', 84)), stroke=4)
            em = emoji_img(st['emoji'], int(txt.height * 0.9)) if st.get('emoji') else None
            w = txt.width + 60 + (em.width + 18 if em else 0)
            h = txt.height + 34
            img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((0, 0, w - 1, h - 1), 22, fill=col + (255,), outline=(255, 255, 255, 255), width=5)
            img.alpha_composite(txt, (30, int(h / 2 - txt.height / 2)))
            if em:
                img.alpha_composite(em, (30 + txt.width + 18, int(h / 2 - em.height / 2)))
        else:
            img = emoji_img(st['emoji'], st.get('size', 150))
        t0 = self.at(line, st['at'])
        self.events.append((t0, 'pop'))
        return dict(img=img, t=t0, x=st.get('x', XC), y=st.get('y', 700), rot=st.get('rot', 0))

    def draw_sticker(self, fr, k, t):
        u = t - k['t']
        if u <= 0:
            return
        sc = ease_out_back(u / 0.3, 2.4)
        wig = 5 * math.sin(u * 9) * math.exp(-u * 2)
        place(fr, k['img'], k['x'], k['y'] + 6 * math.sin(u * 3), sc, min(1, u / 0.08), rot=k['rot'] + wig)

    # date (VHS) -------------------------------------------------------
    def prep_date(self, s):
        L = s['line']
        s['_tD'] = self.at(L, s.get('day_at', 0.0))
        s['_tM'] = self.at(L, s.get('month_at', {'word': s['month']}))
        tY0, tY1 = self.at(L, s['year_at']), self.at(L, s['year_end'])
        s['_day'] = fit_text(s['day'], 'white', TEXT_W, 340)
        s['_dglow'], _ = glow_of(s['_day'], 30, LIME)
        s['_month'] = fit_text(s['month'], 'yellow', TEXT_W - 240, 140)
        s['_icon'] = calendar_icon(96)
        tw, th, gap = 140, 190, 14
        s['_strip'] = odometer_strip(fnt('FiraSansExtraCondensed-Black', 160), tw, th, LIME)
        s['_tile'] = tile_parts(tw, th)
        n = len(s['year'])
        x0 = XC - (n * tw + (n - 1) * gap) / 2 + tw / 2
        s['_rolls'] = [dict(target=int(c), t0=tY0 + 0.08 * i, t1=tY1 + 0.1 * i, spins=1 + i, cx=x0 + i * (tw + gap))
                       for i, c in enumerate(s['year'])]
        s['_tY0'] = tY0
        self.events += [(s['_tD'], 'thud'), (s['_tM'], 'pop'), (tY0 - 0.35, 'pop')]
        self.shakes.append((s['_tD'], 12))
        for r in s['_rolls']:
            self.add_ticks(lambda tt, r=r: roll(tt, r['target'], r['t0'], r['t1'], r['spins']), r['t0'], r['t1'])
        f = fnt('FiraSansExtraCondensed-Bold', 46)
        s['_play'] = plain_text('PLAY', f, stroke=3, stroke_col=(0, 0, 0))
        s['_stamp'] = plain_text(s.get('vhs_stamp', ''), f, stroke=3, stroke_col=(0, 0, 0)) if s.get('vhs_stamp') else None
        s['_rec'] = plain_text('REC', f, stroke=3, stroke_col=(0, 0, 0))

    def draw_date(self, fr, s, t):
        base = fr.convert('RGB')
        base = Image.blend(base, base.convert('L').convert('RGB'), 0.55)
        fr.paste(Image.blend(base, Image.new('RGB', base.size, (16, 28, 64)), 0.22).convert('RGBA'))
        Yi, Yd, Ym, Yy = 470, 690, 925, 1115
        u = t - (s['_tD'] - 0.25)
        if u > 0:
            place(fr, s['_icon'], XC, Yi, ease_out_back(u / 0.4, 2.0), min(1, u / 0.15))
        u = t - s['_tD']
        if u > 0:
            sc = 1 + 0.55 * (1 - ease_out(u / 0.22, 3))
            place(fr, s['_dglow'], XC, Yd, sc, 0.55 * min(1, u / 0.2))
            place(fr, s['_day'], XC, Yd, sc, min(1, u / 0.1))
        u = t - s['_tM']
        if u > 0:
            q = ease_out(u / 0.35)
            m = s['_month']
            place(fr, m, XC, Ym + 40 * (1 - q), 1, min(1, u / 0.2))
            L = 90 * q
            if L > 2:
                d = ImageDraw.Draw(fr)
                half = m.width / 2 + 12
                d.rounded_rectangle((XC - half - L, Ym - 5, XC - half, Ym + 5), 5, fill=LIME + (255,))
                d.rounded_rectangle((XC + half, Ym - 5, XC + half + L, Ym + 5), 5, fill=LIME + (255,))
        u = t - (s['_tY0'] - 0.35)
        if u > 0:
            sc = ease_out_back(u / 0.4, 1.8)
            bg, ov = s['_tile']
            for r in s['_rolls']:
                place(fr, digit_tile(s['_strip'], bg, ov, roll(t, r['target'], r['t0'], r['t1'], r['spins'])),
                      r['cx'], Yy, sc, min(1, u / 0.15))
        fr.alpha_composite(self.scan)
        u = t - s['T']                                     # camcorder overlay
        if u < 1.4:
            place(fr, tri(36, (255, 255, 255)), 88, 262)
            place(fr, s['_play'], 88 + 26 + s['_play'].width / 2, 262)
        elif s['_stamp'] is not None:
            place(fr, s['_stamp'], 70 + s['_stamp'].width / 2, 262)
        if int(t * 2.5) % 2 == 0:
            ImageDraw.Draw(fr).ellipse((790, 246, 822, 278), fill=(235, 30, 40, 255))
        place(fr, s['_rec'], 834 + s['_rec'].width / 2, 262)

    def rewind_fx(self, A, q):
        """VHS rewind: the previous frame scrolls back fast with scanlines, chroma shift and noise bars."""
        a = np.asarray(A.convert('RGB'))
        a = np.roll(a, int(H * 2.4 * q ** 1.4), axis=0).copy()
        g = a.mean(axis=2, keepdims=True)
        a = (a * 0.45 + g * 0.55).astype(np.uint8)
        a[..., 0] = np.roll(a[..., 0], 10, axis=1)
        a[..., 2] = np.roll(a[..., 2], -10, axis=1)
        rnd = random.Random(int(q * 1000))
        for _ in range(3):
            y0 = rnd.randint(0, H - 60)
            hh = rnd.randint(12, 50)
            a[y0:y0 + hh] = np.clip(a[y0:y0 + hh].astype(np.int16) + rnd.randint(40, 110), 0, 255).astype(np.uint8)
            a[y0:y0 + hh] = np.roll(a[y0:y0 + hh], rnd.randint(-60, 60), axis=1)
        fr = Image.fromarray(a).convert('RGBA')
        fr.alpha_composite(self.scan)
        f = fnt('FiraSansExtraCondensed-Black', 64)
        place(fr, tri(46, (255, 255, 255), left=True), 92, 262)
        place(fr, tri(46, (255, 255, 255), left=True), 128, 262)
        txt = plain_text('REWIND', f, stroke=4, stroke_col=(0, 0, 0))
        place(fr, txt, 160 + txt.width / 2, 262)
        return fr

    # crest ------------------------------------------------------------
    def prep_crest(self, s):
        c = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        s['_crest'] = c.resize((int(c.width * 470 / c.height), 470), Image.LANCZOS)
        s['_glow'], _ = glow_of(s['_crest'], 24, (150, 255, 110))
        R = 560
        rays = Image.new('L', (R, R), 0)
        dr = ImageDraw.Draw(rays)
        for i in range(16):
            a0 = i / 16 * 2 * math.pi
            dr.polygon([(R / 2, R / 2)] + [(R / 2 + R * math.cos(a), R / 2 + R * math.sin(a)) for a in (a0, a0 + math.pi / 16)],
                       fill=120 if i % 2 else 70)
        yy, xx = np.mgrid[0:R, 0:R]
        fall = np.clip(1 - np.hypot(xx - R / 2, yy - R / 2) / (R / 2), 0, 1) ** 1.2
        s['_rays'] = Image.fromarray((np.asarray(rays.filter(ImageFilter.GaussianBlur(2))) * fall).astype(np.uint8))
        s['_raycol'] = tuple(min(255, int(c * 1.3 + 50)) for c in self.tcol)

    def draw_crest(self, fr, s, t):
        u = t - s['T']
        rr = s['_rays'].rotate(t * 20, resample=Image.BILINEAR).resize((1250, 1250), Image.BILINEAR)
        lay = Image.new('RGBA', rr.size, s['_raycol'] + (0,))
        lay.putalpha(rr.point(lambda v: int(v * min(1, u / 0.3))))
        place(fr, lay, XC, PHOTO_Y)
        sc = 1 + 0.5 * (1 - ease_out(u / 0.2, 3))
        im = s['_crest']
        sv = u - 0.25
        if 0 < sv < 0.5:
            im = im.copy()
            band = Image.new('L', im.size, 0)
            xx = -im.width * 0.6 + im.width * 2.2 * ease(sv / 0.5)
            ImageDraw.Draw(band).polygon([(xx, 0), (xx + 90, 0), (xx - 120, im.height), (xx - 210, im.height)], fill=170)
            band = ImageChops.multiply(band.filter(ImageFilter.GaussianBlur(18)), im.getchannel('A'))
            wl = Image.new('RGBA', im.size, (255, 255, 255, 0))
            wl.putalpha(band)
            im.alpha_composite(wl)
        place(fr, s['_glow'], XC, PHOTO_Y, sc, 0.8)
        place(fr, im, XC, PHOTO_Y, sc, min(1, u / 0.06))

    # score ------------------------------------------------------------
    def prep_score(self, s):
        L = s['line']
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        s['_home'] = self.plate(s['home'], self.tcol, crest)
        s['_away'] = self.plate(s['away'], tuple(s.get('away_color', RED)), None, mirror=True)
        bw, bh = 230, 160
        box = Image.new('RGBA', (bw + 60, bh + 60), (0, 0, 0, 0))
        gl = Image.new('RGBA', box.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, outline=LIME + (255,), width=12)
        box.alpha_composite(gl.filter(ImageFilter.GaussianBlur(11)))
        ImageDraw.Draw(box).rounded_rectangle((30, 30, 30 + bw, 30 + bh), 26, fill=(8, 20, 36, 250), outline=LIME + (255,), width=5)
        s['_box'], s['_bw'], s['_bh'] = box, bw, bh
        dw, dh = 80, 118
        s['_strip'] = odometer_strip(fnt('FiraSansExtraCondensed-Black', 110), dw, dh, LIME)
        s['_dtile'] = tile_parts(dw, dh, border=None, radius=16)
        s['_dw'], s['_dh'] = dw, dh
        s['_dash'] = plain_text('–', fnt('FiraSansExtraCondensed-Black', 80))
        steps = [dict(value=st['value'], t=self.at(L, st['at']), label=st.get('label', ''),
                      t_label=self.at(L, st.get('label_at', st['at']))) for st in s['steps']]
        s['_dsteps'] = [[(st['t'], st['value'][k]) for st in steps] for k in (0, 1)]
        for ds in s['_dsteps']:
            self.add_ticks(lambda tt, ds=ds: step_value(tt, ds), ds[0][0], ds[-1][0] + 0.8)
        s['_pills'] = []
        for st in steps:
            ptxt = plain_text(st['label'], fnt('FiraSansExtraCondensed-Bold', 38), (6, 30, 16))
            pill = Image.new('RGBA', (ptxt.width + 50, 60), (0, 0, 0, 0))
            ImageDraw.Draw(pill).rounded_rectangle((0, 0, pill.width - 1, 59), 30, fill=LIME + (255,))
            pill.alpha_composite(ptxt, (25, int(30 - ptxt.height / 2)))
            s['_pills'].append((st['t_label'], pill))
        T = s['T']
        s['_tHo'], s['_tAw'], s['_tBox'] = T, T + 0.12, T + 0.22
        self.events += [(T + 0.12, 'pop'), (T + 0.22, 'thud')] + [(st['t_label'], 'pop') for st in steps[1:]]

    def draw_score(self, fr, s, t):
        p = (t - s['T']) / max(s['T1'] - s['T'], 0.3)
        self.paste_photo(fr, 0.5, 0.5, 1.15 + 0.12 * ease(p), dim=0.62)
        board = Image.new('RGBA', (1000, 360), (0, 0, 0, 0))
        cx, cy = 500, 140
        home, away, bw = s['_home'], s['_away'], s['_bw']
        xl, xr = cx - bw / 2 - home.width / 2 + 16, cx + bw / 2 + away.width / 2 - 16
        u = t - s['_tHo']
        if u > 0:
            place(board, home, xl - 560 * (1 - ease_out_back(u / 0.4, 1.3)), cy, 1, min(1, u / 0.12))
        u = t - s['_tAw']
        if u > 0:
            place(board, away, xr + 560 * (1 - ease_out_back(u / 0.4, 1.3)), cy, 1, min(1, u / 0.12))
        u = t - s['_tBox']
        if u > 0:
            b = s['_box'].copy()
            bg, ov = s['_dtile']
            for k in (0, 1):
                tile = digit_tile(s['_strip'], bg, ov, step_value(t, s['_dsteps'][k]))
                b.alpha_composite(tile, (int(30 + 14 + k * (bw - 28 - s['_dw'])), int(30 + (s['_bh'] - s['_dh']) / 2)))
            dash = s['_dash']
            b.alpha_composite(dash, (int(b.width / 2 - dash.width / 2), int(b.height / 2 - dash.height / 2)))
            place(board, b, cx, cy, 0.3 + 0.7 * ease_out_back(u / 0.4, 2.0), min(1, u / 0.1))
            cur = [pp for pp in s['_pills'] if t >= pp[0]]
            if cur:
                tl, pill = cur[-1]
                v = t - tl
                place(board, pill, cx, cy + 135, 0.6 + 0.4 * ease_out_back(v / 0.35, 2.0), min(1, v / 0.12))
        S = 1.0                                             # fits the safe area; punch-ins add ~8%
        for tp in s['_punch']:
            if t > tp:
                S *= 1 + 0.08 * ease_out(min(1, (t - tp) / 0.12))
        place(fr, board, XC, PHOTO_Y + 40, S)

    # kinetic text -----------------------------------------------------
    def prep_text(self, s):
        L = s['line']
        words, y = [], 600
        for i, wd in enumerate(s['words']):
            im = fit_text(wd['text'], wd.get('color', 'white'), TEXT_W + 40, wd.get('max_size', 160))
            tw = self.at(L, wd['at'])
            words.append(dict(im=im, t=tw, cy=y + im.height / 2))
            self.events.append((tw, 'thud'))
            self.shakes.append((tw, 15 if i == 0 else 6))
            y += im.height - 18
        s['_words'] = words
        s['_mascot'] = None
        if self.team.get('mascot'):
            m = Image.open(os.path.join(HERE, self.team['mascot'])).convert('RGBA')
            s['_mascot'] = m.resize((int(m.width * 300 / m.height), 300), Image.LANCZOS)
            s['_tMa'] = self.at(L, s.get('mascot_at', 0.5))
            self.events += [(s['_tMa'], 'whoosh'), (s['_tMa'] + 0.35, 'pop')]
        s['_stampd'] = None
        if s.get('stamp'):
            st = s['stamp']
            simg = fit_text(st['text'], st.get('color', 'yellow'), 420, st.get('max_size', 100))
            s['_stampd'] = dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(L, st['at']),
                                x=st.get('x', XC + 250), y=st.get('y', 500), rot=st.get('rotate', 12))
            self.events.append((s['_stampd']['t'], 'boom'))
            self.shakes.append((s['_stampd']['t'], 12))
        s['_tCf'] = self.at(L, s['confetti_at']) if s.get('confetti_at') else None
        if s['_tCf'] is not None:
            self.events.append((s['_tCf'], 'confetti'))
        rnd = random.Random(9)
        light = tuple(min(255, int(c * 1.3 + 60)) for c in self.tcol)
        cols = [LIME, (255, 255, 255), YELLOW, light]
        conf = []
        for i in range(170):
            burst = i < 105
            ang = rnd.uniform(-math.pi * 0.92, -math.pi * 0.08)
            sp = rnd.uniform(800, 1700)
            conf.append(dict(burst=burst, x0=XC + rnd.uniform(-80, 80) if burst else rnd.uniform(0, W),
                             y0=words[min(2, len(words) - 1)]['cy'] if burst else rnd.uniform(-900, -40),
                             vx=math.cos(ang) * sp if burst else rnd.uniform(-40, 40),
                             vy=math.sin(ang) * sp if burst else rnd.uniform(120, 260),
                             d=rnd.uniform(0, 0.06) if burst else rnd.uniform(0, 0.4),
                             w=rnd.uniform(13, 24), h=rnd.uniform(7, 12), r0=rnd.uniform(0, 6.28),
                             rv=rnd.uniform(-7, 7), fv=rnd.uniform(5, 11), ph=rnd.uniform(0, 6.28), c=rnd.choice(cols)))
        s['_conf'] = conf

    def draw_text(self, fr, s, t):
        p = (t - s['T']) / max(s['T1'] - s['T'], 0.3)
        self.paste_photo(fr, 0.5, 0.48, 1.25 + 0.18 * ease(p), dim=0.62)
        if s['_tCf'] is not None and t > s['_tCf']:
            d = ImageDraw.Draw(fr)
            for c in s['_conf']:
                tt = t - s['_tCf'] - c['d']
                if tt <= 0:
                    continue
                if c['burst']:
                    kk = 2.4
                    x = c['x0'] + c['vx'] * (1 - math.exp(-kk * tt)) / kk
                    y = c['y0'] + c['vy'] * (1 - math.exp(-kk * tt)) / kk + 0.5 * 520 * tt * tt
                else:
                    x = c['x0'] + c['vx'] * tt
                    y = c['y0'] + c['vy'] * tt + 0.5 * 160 * tt * tt
                x += 22 * math.sin(tt * 3 + c['ph'])
                if y > H + 40 or y < -60:
                    continue
                a = c['r0'] + c['rv'] * tt
                f = abs(math.cos(c['fv'] * tt + c['ph']))
                hw, hh = c['w'] / 2, c['h'] / 2 * (0.25 + 0.75 * f)
                ca, sa = math.cos(a), math.sin(a)
                d.polygon([(x + ca * dx - sa * dy, y + sa * dx + ca * dy) for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))],
                          fill=shade(c['c'], 0.55 + 0.45 * f) + (255,))
        for wd in s['_words']:
            u = t - wd['t']
            if u > 0:
                place(fr, wd['im'], XC, wd['cy'], 1 + 0.65 * (1 - ease_out(u / 0.2, 3)), min(1, u / 0.08))
        st = s['_stampd']
        if st is not None and t > st['t']:
            u = t - st['t']
            sc = 1 + 1.4 * (1 - ease_out(u / 0.18, 3))
            place(fr, st['glow'], st['x'], st['y'], sc, 0.8 * min(1, u / 0.1), rot=st['rot'])
            place(fr, st['im'], st['x'], st['y'], sc, min(1, u / 0.06), rot=st['rot'])
        m = s['_mascot']
        if m is not None and t > s['_tMa']:
            u = t - s['_tMa']
            e = ease_out_back(u / 0.55, 1.5)
            place(fr, m, 40 + m.width / 2 - 420 * (1 - e), 1340 + 300 * (1 - e) + 10 * math.sin(2 * math.pi * 1.1 * u),
                  1, min(1, u / 0.2), rot=-16 * (1 - e) + 3 * math.sin(3.4 * u))

    # end --------------------------------------------------------------
    def prep_end(self, s):
        self.events.append((s['T'] + 0.3, 'boom_soft'))

    def draw_end(self, fr, s, t):
        u = t - s['T']
        self.paste_photo(fr, 0.5, 0.5, 1.3 - 0.2 * ease(min(1, u / 3)), dim=0.72)
        p = ease_out_back((u - 0.1) / 0.5)
        if p > 0.02:
            place(fr, self.k_glow, XC, 700, p, 0.55)
            place(fr, self.k_big, XC, 700, p)
        p = ease_out_back((u - 0.35) / 0.45, 2.0)
        if p > 0.02:
            pulse = 1 + 0.035 * math.sin(2 * math.pi * 1.6 * u)
            place(fr, self.badge_glow, XC, 850, p * pulse, 0.6)
            place(fr, self.badge, XC, 850, p * pulse)
        p = ease_out_back((u - 0.6) / 0.4, 2.0)
        if p > 0.02:
            place(fr, emoji_img('👇', 120), XC, 990 + 16 * abs(math.sin(2 * math.pi * 1.3 * u)), p)

    # ---------------------------------------------------------------- composition
    def compose(self, t, n):
        i = self.shot_at(t)
        cur = self.shots[i]
        kind, u = cur.get('in', 'cut'), t - cur['T']
        if kind == 'rewind' and u < 0.7 and i > 0:
            prev = self.shots[i - 1]
            if '_frozen' not in prev:
                prev['_frozen'] = self.shot_frame(prev, cur['T'] - 1 / FPS)
            B = self.rewind_fx(prev['_frozen'], u / 0.7)
            if u > 0.55:
                B = Image.blend(B, self.shot_frame(cur, t), ease((u - 0.55) / 0.15))
            return B
        B = self.shot_frame(cur, t)
        nxt = self.shots[i + 1] if i + 1 < len(self.shots) else None
        if nxt is not None:                               # the outgoing half of zoom / whip transitions
            v = nxt['T'] - t
            k2 = nxt.get('in', 'cut')
            if k2 == 'zoomblur' and v < 0.12:
                q = 1 - v / 0.12
                B = Image.blend(zoom(B, 1 + 0.2 * q * q), zoom(B, 1 + 0.32 * q * q), 0.5)
            elif k2 == 'whip' and v < 0.12:
                q = 1 - v / 0.12
                B = roll_x(hblur(B), -W * 0.55 * q * q)
        if kind == 'zoomblur' and u < 0.22:
            q = u / 0.22
            s = 1.25 - 0.25 * ease_out(q)
            B = Image.blend(zoom(B, s * 1.06), zoom(B, s), 0.5 + 0.5 * q)
        elif kind == 'whip' and u < 0.16:
            q = u / 0.16
            B = Image.blend(roll_x(hblur(B), W * 0.55 * (1 - q) ** 2), B, ease(q))
        elif kind == 'glitch' and u < 0.26:
            B = glitch_fx(B, 1 - u / 0.26, n)
        elif kind == 'flash' and u < 0.16:
            B = Image.blend(B, Image.new('RGBA', B.size, (255, 255, 255, 255)), 0.75 * (1 - u / 0.16))
        return B

    def brand(self, fr, t):
        """The 'Ήξερες ότι;' sticker pops big on the first frame, then parks in the header."""
        if t < 1.45:
            u = t - 0.05
            s = 0.78 * ease_out_back(u / 0.4, 2.2) * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t)) if u > 0 else 0
            fr = Image.alpha_composite(fr, Image.new('RGBA', fr.size, (2, 8, 18, int(110 * min(1, max(u, 0) / 0.2)))))
            y = 760
        elif t < 1.95:
            x = ease((t - 1.45) / 0.5)
            s, y = 0.78 + (STICK_S - 0.78) * x, 760 + (STICK_Y - 760) * x
            fr = Image.alpha_composite(fr, Image.new('RGBA', fr.size, (2, 8, 18, int(110 * (1 - x)))))
        else:
            s, y = STICK_S * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t)), STICK_Y
        if s > 0.02:
            fr = self.intro.draw_sticker(fr, t, W / 2, y, s, glow=0.9)
        u = t - 1.6
        if u > 0 and self.shots[self.shot_at(t)]['type'] != 'end':
            place(fr, self.k_small, 60 + self.k_small.width / 2, LOGO_Y - 120 * (1 - ease_out(u / 0.5)), 1, min(1, u / 0.3))
        return fr

    def frame(self, n):
        t = n / FPS
        fr = self.compose(t, n)
        fr = self.brand(fr, t)
        if not self.shots[self.shot_at(t)].get('hide_captions'):
            self.draw_captions(fr, t)
        fr = self.particles(fr, t, 0.4)
        dx, dy = self.shake(t)
        dx, dy = max(-15, min(15, dx)), max(-15, min(15, dy))
        if abs(dx) + abs(dy) > 0.5:
            fr = fr.resize((W, H), Image.BILINEAR, box=(16 + dx, 28 + dy, W - 16 + dx, H - 28 + dy))
        return fr.convert('RGB')

    # ---------------------------------------------------------------- audio
    def audio(self):
        out = np.zeros(int((self.total + 2) * SR), np.float32)

        def add(t, x, g):
            i = int(max(t, 0) * SR)
            x = x[:max(0, len(out) - i)]
            out[i:i + len(x)] += x * g

        lib = {'pop': (sfx_pop, 0.22), 'thud': (sfx_thud, 0.4), 'whoosh': (lambda: sfx_whoosh(0.5), 0.26),
               'boom_soft': (lambda: sfx_boom(1.2), 0.3), 'tick': (sfx_tick, 0.08), 'confetti': (sfx_confetti, 0.5),
               'boom': (sfx_vboom, 0.55), 'glitch': (sfx_glitch, 0.35), 'rewind': (sfx_rewind, 0.4),
               'shutter': (sfx_shutter, 0.3), 'ding': (sfx_ding, 0.7)}
        for t, kind in self.events:
            f, g = lib[kind]
            add(t, f(), g)
        for t, (v, _) in zip(self.vo_starts, self.vo):
            add(t, v, 1.0)
        out = out[:int(self.total * SR)]
        fade = int(0.12 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        out = np.tanh(out * 1.1) / np.tanh(1.1) * 0.95
        path = os.path.join(CACHE, 'edit_mix.wav')
        with wave.open(path, 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            s = (np.clip(out, -1, 1) * 32767).astype(np.int16)
            w.writeframes(np.repeat(s[:, None], 2, axis=1).tobytes())
        return path


if __name__ == '__main__':
    ed = Edit(sys.argv[1])
    if sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(ed.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else os.path.join(CACHE, 'preview.png'))
        print('vo starts', [round(x, 2) for x in ed.vo_starts], 'total', round(ed.total, 2))
        print('shots', [(s['type'], s.get('in', 'cut'), round(s['T'], 2)) for s in ed.shots])
    else:
        ed.render(sys.argv[2])
