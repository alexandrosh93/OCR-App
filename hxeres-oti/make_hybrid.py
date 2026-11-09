#!/usr/bin/env python3
"""'Ήξερες ότι;' — HYBRID theme (test): the modern layout with the elements of the current style.

    python3 make_hybrid.py configs/apollon_legia_hybrid.json ../videos/hxeres_oti_apollon_legia_hybrid.mp4
    python3 make_hybrid.py configs/apollon_legia_hybrid.json --preview 1,4,8 preview.png

From the modern test (make_modern.py): big photos with slow push-ins, clean Inter Display text with masked reveals,
the map with coordinates and a live distance counter, the 0'-90' match timeline, pill captions,
swipe-up transitions, soft grain (no progress bar).
The video opens straight on the hook (photo with a punch-in + the words as they are spoken), so the viewer is
hooked from the first second; the «Ήξερες ότι;» sticker comes only on the end card, with «Κάνε follow για
περισσότερα!». "intro_sticker": true brings back the old opening (animated sticker first, then the hook).
From the current style (make_story.py): the animated «Ήξερες ότι;» sticker (end card; with intro_sticker also the
opening, popping out when the photos start so it never covers them),
the mascot, chunky stickers (ΙΣΤΟΡΙΚΟ!, ΣΑΝΓΚΟΪ 56', VS ΛΕΓΚΙΑ), team plates with the crest and flip-clock tiles,
the crest on rotating rays, confetti, emoji (✈️ 🇨🇾 🇵🇱 👑), floating particles and the «ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ 👇» badge.
"""
import sys, os, math, random, subprocess, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageEnhance
from make_video import (HERE, W, H, FPS, ease, ease_out, ease_out_back, with_alpha, place, glow_of, fnt, Intro,
                        calendar_icon, LIME, sfx_ding, sfx_boom, band_noise, env_t)
from make_story import (Story, fit_text, plain_text, emoji_img, tile_parts, odometer_strip, digit_tile, roll, step_value,
                        shade, norm, sfx_confetti, XC, YELLOW, TEXT_W, STICKER_Y, STICKER_S, LOGO_Y)
from make_modern import Modern, Photo, F, text_img, reveal, expo, inout, shadowed, BG, WHITE, MUTED, ACC, INK, M, TR
from make_video import SR, CACHE
from make_story import caps

LOUDNESS = -9.5          # final mix, LUFS (stereo): a loud, voice-first social video (the old mix was -11)
PEAK = 0.82              # limiter ceiling (about -1.7 dBFS: true peak stays under -1 dBTP)


def sfx_click(dur=0.09):
    """Short UI tap: a crisp transient with a little body."""
    t = env_t(dur)
    return band_noise(dur, 1800, 9000) * np.exp(-t * 170) * 0.8 + np.sin(2 * np.pi * 900 * t) * np.exp(-t * 80) * 0.5


def sfx_notify(dur=1.0):
    """Bright two-note chime (E6 -> B6), like an app notification."""
    t = env_t(dur)

    def note(f, t0):
        tt = np.clip(t - t0, 0, None)
        tone = sum(g * np.sin(2 * np.pi * f * k * tt) for k, g in ((1, 1.0), (2, 0.35), (3, 0.12)))
        return (t >= t0) * tone * np.exp(-tt * 6.5) * np.clip(tt / 0.004, 0, 1)
    return note(1318.5, 0.0) * 0.55 + note(1975.5, 0.11) * 0.6


def _pill(w, h, fill, outline=None, top=None):
    """Rounded button with a soft top highlight."""
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), h // 2, fill=fill + (255,), outline=outline and outline + (255,),
                        width=5 if outline else 0)
    if top:
        hi = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(hi).rounded_rectangle((8, 6, w - 9, h // 2), h // 4, fill=top)
        im.alpha_composite(hi.filter(ImageFilter.GaussianBlur(4)))
    return im


def _icon(kind, size, color, width=10):
    """Plus or check mark, drawn (crisper than an emoji at this size)."""
    im = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
    d, s, w = ImageDraw.Draw(im), size * 4, width * 4
    if kind == 'plus':
        d.line((s / 2, w / 2, s / 2, s - w / 2), fill=color + (255,), width=w)
        d.line((w / 2, s / 2, s - w / 2, s / 2), fill=color + (255,), width=w)
    else:
        d.line([(w / 2, s * 0.55), (s * 0.38, s - w), (s - w / 2, w)], fill=color + (255,), width=w, joint='curve')
    return im.resize((size, size), Image.LANCZOS)


def lufs(path):
    """Integrated loudness of a file (ffmpeg ebur128)."""
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-af', 'ebur128', '-f', 'null', '-'],
                       capture_output=True, text=True).stderr
    return float(r[r.rfind('Summary:'):].split('I:')[1].split('LUFS')[0])


class PopPhoto(Photo):
    """Photo with its player cut out (make_cutout.py). The background (player filled in) and the player zoom at
    different speeds, which gives depth, and the player is drawn over the photo's bottom fade, so he pops out."""

    def __init__(self, fg, bg, ph, focus=(0.5, 0.45), margin=1.15):
        super().__init__(bg, ph, focus, margin)
        k = max(W * margin / fg.width, ph * margin / fg.height)
        size = (int(fg.width * k) + 1, int(fg.height * k) + 1)
        rgb = fg.convert('RGB').resize(size, Image.LANCZOS)
        if k > 1.3:
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        rgb = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(0.9)).enhance(1.05)
        rgb.putalpha(fg.getchannel('A').resize(size, Image.LANCZOS))
        self.fg = rgb

    def fg_at(self, u, z0=1.0, z1=1.07, depth=0.07):
        """The player layer: zooms `depth` more than the background over the scene."""
        z = z0 + (z1 - z0 + depth) * inout(min(max(u, 0), 1))
        cw, ch = self.fg.size
        ww, wh = W / z, self.ph / z
        cx = min(max(self.focus[0] * cw, ww / 2), cw - ww / 2)
        cy = min(max(self.focus[1] * ch, wh / 2), ch - wh / 2)
        return self.fg.resize((W, self.ph), Image.BILINEAR, box=(cx - ww / 2, cy - wh / 2, cx + ww / 2, cy + wh / 2))


class Hybrid(Modern):
    def __init__(self, cfg_path):
        self.intro = Intro()
        rnd = random.Random(7)
        self.parts = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), r=rnd.uniform(1.5, 4.0), v=rnd.uniform(18, 60),
                           ph=rnd.uniform(0, 6.28)) for _ in range(50)]
        super().__init__(cfg_path)
        kl = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA')
        self.k_small = kl.resize((330, int(kl.height * 330 / kl.width)), Image.LANCZOS)
        self.build_end_card()                            # «ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ 👇» badge of the current style

    @property
    def sticker_intro(self):
        """Old opening: the animated «Ήξερες ότι;» sticker before the hook (off by default: it delays the hook)."""
        return bool(self.cfg.get('intro_sticker', False))

    def timeline(self):
        if not self.sticker_intro:                # no sticker intro: the voice starts right away
            self.HOOK_START, self.INTRO_MIN = 0.15, 0.0
        super().timeline()

    # ---------------------------------------------------------------- pop-out photos
    def photo_of(self, path, ph, focus=(0.5, 0.45), pop=False):
        """Photo, or PopPhoto when "popout" is on and make_cutout.py has cut the player out of it."""
        if pop:
            name = os.path.splitext(os.path.basename(path))[0]
            fg, bg = (os.path.join(HERE, 'posts', 'cutouts', f'{name}_{x}') for x in ('fg.png', 'bg.jpg'))
            if os.path.exists(fg) and os.path.exists(bg):
                return PopPhoto(Image.open(fg).convert('RGBA'), Image.open(bg).convert('RGB'), ph, focus)
            print(f'popout: no cutout for {path} (run make_cutout.py), plain photo used', file=sys.stderr)
        return Photo(self.load_photo(path), ph, focus)

    def fg_ramp(self, ph):
        """The popped-out player stays solid down to near the bottom of the photo, then fades in 0.24 of a frame."""
        if not hasattr(self, '_ramps'):
            self._ramps = {}
        if ph not in self._ramps:
            a = np.clip((ph - 40 - np.arange(ph, dtype=np.float32)) / 240, 0, 1)
            self._ramps[ph] = Image.fromarray((np.repeat(a[:, None], W, axis=1) * 255).astype(np.uint8), 'L')
        return self._ramps[ph]

    def draw_pop(self, fr, P, u, dim=0.0, y=0, h=None, alpha=1.0):
        """The cut-out player over the (faded) photo: a soft shadow, and brighter than the dimmed photo."""
        fg = P.fg_at(u)
        a = ImageChops.multiply(fg.getchannel('A'), self.fg_ramp(P.ph))
        if alpha < 1:
            a = a.point(lambda v: int(v * alpha))
        rgb = fg.convert('RGB')
        if dim > 0:
            rgb = Image.blend(rgb, Image.new('RGB', rgb.size, BG), dim * 0.3)
        sh = Image.new('RGBA', rgb.size, (0, 0, 0, 0))
        sh.putalpha(a.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.6)))
        rgb.putalpha(a)
        h = P.ph if h is None else h
        if h < P.ph:
            sh, rgb = sh.crop((0, 0, W, max(1, h))), rgb.crop((0, 0, W, max(1, h)))
        fr.alpha_composite(sh, (0, y + 14))
        fr.alpha_composite(rgb, (0, y))

    def behind_img(self, b):
        """Huge word that sits behind the popped-out player (text-behind-subject)."""
        size = b.get('size', 330)
        im = plain_text(b['text'], fnt('FiraSansExtraCondensed-Black', size), ACC if b.get('color') == 'acc' else WHITE)
        if im.width > W - 40:
            im = im.resize((W - 40, int(im.height * (W - 40) / im.width)), Image.LANCZOS)
        return im, glow_of(im, 22, (0, 0, 0))[0]

    def build_end_card(self):
        """«ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ 👇» badge of the current style; "cta_badge": null = no badge."""
        if self.cfg.get('cta_badge', '') is None:
            self.badge = self.badge_glow = None
            return
        self.cfg.setdefault('cta_badge', 'ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ')
        super().build_end_card()

    def sfx_lib(self):
        lib = super().sfx_lib()
        lib.update({'ding': (sfx_ding, 0.75), 'boom_big': (lambda: sfx_boom(1.4), 0.6), 'confetti': (sfx_confetti, 0.45),
                    'click': (sfx_click, 0.45), 'notify': (sfx_notify, 0.55)})
        return lib

    # ---------------------------------------------------------------- intro: the hook (optionally after the sticker)
    def m_intro(self):
        cfg = self.cfg
        P = Photo(self.load_photo(cfg.get('hook_photo')), cfg.get('hook_ph', 1120), tuple(cfg.get('hook_focus', (0.5, 0.45))))
        words = self.disp_words(0)
        k = 0
        while self.sticker_intro and k < len(words) and words[k][3] in ('ηξερες', 'οτι'):
            k += 1                                        # «Ήξερες ότι» is spoken over the sticker itself
        rest = words[k:]
        if self.sticker_intro:
            split = max((rest[0][1] - 0.15) if rest else self.t_intro - 0.6, self.intro.t_hit + 0.45)
            self.fly0, self.fly_end = split, split + 0.45  # sticker pops out: it must not cover the photos
        else:
            split = self.fly0 = self.fly_end = 0.0
        size = cfg.get('hook_size', 122)
        f, tr, sp = F('Black', size), -int(size * 0.025), int(size * 0.26)
        acc = {norm(w) for w in cfg.get('hook_accent', [])}
        hrep = {norm(k): v for k, v in cfg.get('hook_replace', {}).items()}
        lines, cur, cw, pad = [], [], 0, 24
        for w, t0, t1, n in rest:
            if n in hrep:
                w = hrep[n] + ''.join(ch for ch in w if ch in ',.;:!?·…')
            im, pad = shadowed(text_img(w, f, ACC if (n in acc or norm(w) in acc) else WHITE, tracking=tr))
            if cur and cw + sp + im.width - 2 * pad > W - 2 * M:
                lines.append(cur)
                cur, cw = [], 0
            cur.append((im, t0))
            cw += (sp if len(cur) > 1 else 0) + im.width - 2 * pad
        if cur:
            lines.append(cur)
        lh = int(size * 1.04)
        top = cfg.get('hook_bottom', 1330) - lh * len(lines) - int(size * 0.24)
        placed = []
        for li, row in enumerate(lines):
            x = M
            for im, t0 in row:
                placed.append((im, x - pad, top + li * lh - pad, t0))
                x += im.width - 2 * pad + sp
        if self.sticker_intro:
            self.events += [(0.0, 'riser'), (self.intro.t_hit, 'boom_big'), (self.intro.t_bulb, 'ding'), (split, 'whoosh')]
        else:                                             # straight in: a hit on the first frame
            self.events += [(0.0, 'boom'), (0.02, 'whoosh')]
        dim = cfg.get('hook_dim', 0.32)

        def draw(fr, t):
            if t < split:                                 # the original sticker intro, untouched
                fr.paste(self.intro.frame(t).convert('RGBA'), (0, 0))
                return
            x = ease((t - split) / 0.5)
            u = t / max(self.t_intro, 0.1)
            if self.sticker_intro:
                self.photo_bg(fr, P, u, dim=dim)
            else:                                         # punch-in: starts 10% closer and settles in 0.45 s
                z = 1 + 0.10 * (1 - ease_out(min(1.0, t / 0.45)))
                img = P.at(u, z, 1.07 * z)
                fr.paste(Image.blend(img, Image.new('RGB', img.size, BG), dim) if dim > 0 else img, (0, 0))
                fr.alpha_composite(self.shade_for(P.ph))
            if self.sticker_intro and x < 1:
                fr.alpha_composite(with_alpha(self.intro.background(t), 1 - x))
            for im, xx, yy, t0 in placed:
                reveal(fr, im, xx, yy, (t - (t0 - 0.06)) / 0.5)
            if self.sticker_intro and t < self.fly_end:   # sticker pops out (small grow, then shrinks away)
                e = (t - self.fly0) / (self.fly_end - self.fly0)
                s0 = self.intro.logo_state(self.fly0)[0]
                s = s0 * (1 + 0.08 * ease_out(e / 0.25)) if e < 0.25 else s0 * 1.08 * (1 - ease((e - 0.25) / 0.75))
                if s > 0.02:
                    fr.paste(self.intro.draw_sticker(fr.copy(), t, W / 2, 880 - 140 * ease(e), s, glow=0.9))
        return draw

    # ---------------------------------------------------------------- date: clean type + flip-clock year
    def m_date(self, sc, line, T):
        T1 = self.seg_end(line)
        P = Photo(self.load_photo(sc['photo']), sc.get('ph', 1150), tuple(sc.get('focus', (0.5, 0.45)))) if sc.get('photo') else None
        plate = None if P else self.dark_plate(sc.get('backdrop'), 0.18)
        tD, tM = self.at(line, sc.get('day_at', 0.0)), self.at(line, sc['month_at'])
        tY0, tY1 = self.at(line, sc['year_at']), self.at(line, sc['year_end'])
        icon = calendar_icon(90)
        lab = self.label_img(sc['label']) if sc.get('label') else None
        day = text_img(sc['day'], F('Black', 290), WHITE, tracking=-10, line_box=False)
        month = text_img(sc['month'], F('Black', 108), WHITE, tracking=-2)
        tw, th, gap = 112, 150, 12
        strip = odometer_strip(fnt('FiraSansExtraCondensed-Black', 128), tw, th, LIME)
        bg, ov = tile_parts(tw, th)
        rolls = [dict(target=int(c), t0=tY0 + 0.06 * i, t1=tY1 + 0.04 * i, spins=1 + i) for i, c in enumerate(sc['year'])]
        y0 = sc.get('y', 720)
        iy, ly, dy = y0 - 104, y0, y0 + 42
        my = dy + day.height + 20
        yy = my + month.height + 6
        for r in rolls:
            self.add_ticks(lambda tt, r=r: roll(tt, r['target'], r['t0'], r['t1'], r['spins']), r['t0'], r['t1'])
        self.events += [(tD, 'thud'), (tM, 'pop'), (tY0 - 0.35, 'pop')]
        pc = None
        if sc.get('photo_card'):                          # polaroid of the current style (e.g. the founder)
            pc = self.photo_card(sc.get('photo_width', 300), sc.get('photo_max_h', 300), self.load_photo(sc['photo_card']))
            tPh = self.at(line, sc.get('photo_at', 0.0))
            pxy = (sc.get('photo_x', 790), sc.get('photo_y', 840), sc.get('photo_rot', 6))
            self.events.append((tPh, 'whoosh'))

        def draw(fr, t):
            if P:
                self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            else:
                fr.paste(plate, (0, 0))
            if pc is not None:
                self.draw_card(fr, pc, t, tPh, pxy[0], pxy[1], rot_end=pxy[2])
            u = t - (tD - 0.3)
            if u > 0:
                place(fr, icon, M + icon.width / 2, iy + icon.height / 2, ease_out_back(u / 0.4, 2.0), min(1, u / 0.15))
            if lab:
                reveal(fr, lab, M, ly, (t - (T + 0.12)) / 0.45)
            reveal(fr, day, M, dy, (t - (tD - 0.06)) / 0.55)
            reveal(fr, month, M, my, (t - (tM - 0.06)) / 0.5)
            u = t - (tY0 - 0.35)
            if u > 0:
                k = ease_out_back(u / 0.4, 1.8)
                for i, r in enumerate(rolls):
                    tile = digit_tile(strip, bg, ov, roll(t, r['target'], r['t0'], r['t1'], r['spins']))
                    place(fr, tile, M + tw / 2 + i * (tw + gap), yy + th / 2, k, min(1, u / 0.15))
        return draw

    # ---------------------------------------------------------------- score: big photo + timeline + plates/tiles
    def m_score(self, sc, line, T):
        T1 = self.seg_end(line)
        P = self.photo_of(sc['photo'], sc.get('ph', 1000), tuple(sc.get('focus', (0.5, 0.45))), sc.get('popout'))
        tl_draw = self.make_timeline(sc, line)

        def crest_of(key, default):
            path = sc.get(key, default)
            return Image.open(os.path.join(HERE, path)).convert('RGBA') if path else None
        home = self.plate(sc['home'], tuple(sc.get('home_color', self.tcol)), crest_of('home_crest', self.team['crest']))
        away = self.plate(sc['away'], tuple(sc.get('away_color', (90, 90, 100))), crest_of('away_crest', None), mirror=True)
        tHo, tAw, tBox = self.at(line, sc['home_at']), self.at(line, sc['away_at']), self.at(line, sc['score_at'])
        steps = [dict(value=s['value'], t=self.at(line, s['at']), label=s.get('label', ''),
                      t_label=self.at(line, s.get('label_at', s['at']))) for s in sc['steps']]
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
        for ds in digit_steps:
            self.add_ticks(lambda tt, ds=ds: step_value(tt, ds), ds[0][0], ds[-1][0] + 0.8)
        pills = [(s['t_label'], self.pill_img(s['label'], 36)) for s in steps if s['label']]
        badge = None
        if sc.get('badge'):
            b = sc['badge']
            bimg = fit_text(b['text'], b.get('color', 'yellow'), 420, b.get('max_size', 90))
            badge = dict(im=bimg, glow=glow_of(bimg, 16, LIME)[0], t=self.at(line, b['at']),
                         x=b.get('x', XC + 250), y=b.get('y', 540), rot=b.get('rotate', 9))
            self.events.append((badge['t'], 'thud'))
        self.events += [(tHo, 'pop'), (tAw, 'pop'), (tBox, 'thud')] + [(s['t_label'], 'pop') for s in steps[1:]]
        Ys = sc.get('board_y', 1160)
        xl, xr = XC - bw / 2 - home.width / 2 + 16, XC + bw / 2 + away.width / 2 - 16

        def draw(fr, t):
            self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            if isinstance(P, PopPhoto):
                self.draw_pop(fr, P, (t - T) / max(T1 - T, 0.1))
            tl_draw(fr, t)
            if badge is not None and t > badge['t']:
                v = t - badge['t']
                k = 1 + 1.2 * (1 - ease_out(v / 0.18, 3))
                place(fr, badge['glow'], badge['x'], badge['y'], k, 0.8 * min(1, v / 0.1), rot=badge['rot'])
                place(fr, badge['im'], badge['x'], badge['y'], k, min(1, v / 0.06), rot=badge['rot'])
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
                    v = step_value(t, digit_steps[k]) if t > digit_steps[k][0][0] else digit_steps[k][0][1] + 15
                    b.alpha_composite(digit_tile(strip, tbg, tov, v), (int(30 + 14 + k * (bw - 28 - dw)), int(30 + (bh - dh) / 2)))
                b.alpha_composite(dash, (int(b.width / 2 - dash.width / 2), int(b.height / 2 - dash.height / 2)))
                place(fr, b, XC, Ys, 0.3 + 0.7 * ease_out_back(u / 0.45, 2.0), min(1, u / 0.12))
                cur = [p for p in pills if t >= p[0]]
                if cur:
                    tl, pill = cur[-1]
                    v = t - tl
                    place(fr, pill, XC, Ys + 125, 0.6 + 0.4 * ease_out_back(v / 0.35, 2.0), min(1, v / 0.15))
        return draw

    # ---------------------------------------------------------------- fact: crest on rays, mascot, confetti, stamp
    def m_fact(self, sc, line, T):
        T1 = self.seg_end(line)
        plate = self.dark_plate(sc.get('photo'), 0.24)
        crest = Image.open(os.path.join(HERE, self.team['crest'])).convert('RGBA')
        crest = crest.resize((int(crest.width * 230 / crest.height), 230), Image.LANCZOS)
        cglow, _ = glow_of(crest, 20, (150, 255, 110))
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
        Yc = sc.get('crest_y', 590)
        tC = self.at(line, sc.get('crest_at', 0.0))
        size = sc.get('size', 110)
        chunky = sc.get('words_style') == 'chunky'
        lines, y = [], sc.get('y', 810)
        for wd in sc['words']:
            if chunky:                                    # template-1 headline stickers
                im = fit_text(wd['text'], wd.get('color', 'white'), TEXT_W, wd.get('max_size', 160))
                lines.append((im, self.at(line, wd['at']), y))
                y += im.height - 18
            else:
                col = ACC if wd.get('color') in ('acc', 'green', 'yellow') else WHITE
                im = text_img(wd['text'], F('Black', size), col, tracking=-int(size * 0.03))
                lines.append((im, self.at(line, wd['at']), y))
                y += int(size * 1.02)
        mascot, tMa = None, None
        if self.team.get('mascot'):
            m = Image.open(os.path.join(HERE, self.team['mascot'])).convert('RGBA')
            mascot = m.resize((int(m.width * 270 / m.height), 270), Image.LANCZOS)
            tMa = self.at(line, sc.get('mascot_at', 0.5))
            self.events += [(tMa, 'whoosh'), (tMa + 0.35, 'pop')]
        stamp = None
        if sc.get('stamp'):
            st = sc['stamp']
            simg = fit_text(st['text'], st.get('color', 'yellow'), 400, st.get('max_size', 100))
            stamp = dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(line, st['at']),
                         x=st.get('x', XC + 285), y=st.get('y', Yc + 70), rot=st.get('rotate', 12))
            self.events.append((stamp['t'], 'thud'))
        tCf = self.at(line, sc['confetti_at']) if sc.get('confetti_at') else None
        if tCf is not None:
            self.events.append((tCf, 'confetti'))
        self.events += [(tC, 'whoosh'), (tC + 0.3, 'pop'), (lines[0][1], 'boom')] + [(ta, 'pop') for _, ta, _ in lines[1:]]
        rnd = random.Random(9)
        light = tuple(min(255, int(c * 1.3 + 60)) for c in self.tcol)
        cols = [LIME, (255, 255, 255), YELLOW, light]
        conf = []
        for i in range(160):
            burst = i < 100
            ang = rnd.uniform(-math.pi * 0.92, -math.pi * 0.08)
            sp = rnd.uniform(800, 1700)
            conf.append(dict(burst=burst, x0=XC + rnd.uniform(-80, 80) if burst else rnd.uniform(0, W),
                             y0=Yc + 60 if burst else rnd.uniform(-900, -40),
                             vx=math.cos(ang) * sp if burst else rnd.uniform(-40, 40),
                             vy=math.sin(ang) * sp if burst else rnd.uniform(120, 260),
                             d=rnd.uniform(0, 0.06) if burst else rnd.uniform(0, 0.4),
                             w=rnd.uniform(13, 24), h=rnd.uniform(7, 12), r0=rnd.uniform(0, 6.28),
                             rv=rnd.uniform(-7, 7), fv=rnd.uniform(5, 11), ph=rnd.uniform(0, 6.28), c=rnd.choice(cols)))

        def draw(fr, t):
            fr.paste(plate, (0, 0))
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
                if 0 < sv < 0.6:                          # shine sweep over the crest
                    im = crest.copy()
                    band = Image.new('L', im.size, 0)
                    bx = -im.width * 0.6 + im.width * 2.2 * ease(sv / 0.6)
                    ImageDraw.Draw(band).polygon([(bx, 0), (bx + 70, 0), (bx - 90, im.height), (bx - 160, im.height)], fill=160)
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
                    d.polygon([(x + ca * dx - sa * dy, y + sa * dx + ca * dy) for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))],
                              fill=shade(p['c'], 0.55 + 0.45 * f) + (255,))
            for im, ta, yy in lines:
                if chunky:
                    u = t - ta
                    if u > 0:
                        place(fr, im, XC, yy + im.height / 2, 1 + 0.65 * (1 - ease_out(u / 0.2, 3)), min(1, u / 0.08))
                else:
                    reveal(fr, im, M - 4, yy, (t - (ta - 0.05)) / 0.55)
            if stamp is not None and t > stamp['t']:
                v = t - stamp['t']
                k = 1 + 1.4 * (1 - ease_out(v / 0.18, 3))
                place(fr, stamp['glow'], stamp['x'], stamp['y'], k, 0.8 * min(1, v / 0.1), rot=stamp['rot'])
                place(fr, stamp['im'], stamp['x'], stamp['y'], k, min(1, v / 0.06), rot=stamp['rot'])
            if mascot is not None and t > tMa:
                v = t - tMa
                e = ease_out_back(v / 0.55, 1.5)
                place(fr, mascot, XC - 330 - 420 * (1 - e), Yc + 40 + 260 * (1 - e) + 10 * math.sin(2 * math.pi * 1.1 * v),
                      1, min(1, v / 0.2), rot=-16 * (1 - e) + 3 * math.sin(3.4 * v))
        return draw

    # ---------------------------------------------------------------- stats / streak from template 1 on big photos
    def m_stats(self, sc, line, T):
        T1 = self.seg_end(line)
        P = Photo(self.load_photo(sc['photo']), sc.get('ph', 980), tuple(sc.get('focus', (0.5, 0.42))))
        inner = Story.build_stats(self, dict(sc, no_card=True), line, T)

        def draw(fr, t):
            self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            inner(fr, t)
        return draw

    def m_streak(self, sc, line, T):
        T1 = self.seg_end(line)
        P = Photo(self.load_photo(sc['photo']), sc.get('ph', 840), tuple(sc.get('focus', (0.5, 0.4)))) if sc.get('photo') else None
        plate = None if P else self.dark_plate(sc.get('backdrop'), 0.2)
        inner = Story.build_streak(self, sc, line, T)

        def draw(fr, t):
            if P:
                self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            else:
                fr.paste(plate, (0, 0))
            inner(fr, t)
        return draw

    def m_gallery(self, sc, line, T):
        """Photos that slide in on words (modern), optional pop-out player with a huge word behind him,
        title lines, label, emoji and the chunky stickers of template 1."""
        T1 = self.seg_end(line)
        ph = sc.get('ph', 1080)
        photos = []
        for it in sc['photos']:
            P = self.photo_of(it['photo'], ph, tuple(it.get('focus', (0.5, 0.45))), it.get('popout'))
            t0 = self.at(line, it['at'])
            bh = None
            if it.get('behind'):
                b = it['behind']
                im, glow = self.behind_img(b)
                bh = dict(im=im, glow=glow, t=self.at(line, b['at']) if 'at' in b else t0 + 0.3, y=b.get('y', 300))
                self.events.append((bh['t'], 'whoosh'))
            photos.append(dict(P=P, t=t0, behind=bh))
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
        stks = []                                         # chunky stickers of template 1
        for st in ([sc['sticker']] if sc.get('sticker') else []) + sc.get('stickers', []):
            simg = fit_text(st['text'], st.get('color', 'yellow'), st.get('max_w', 760), st.get('max_size', 120))
            stks.append(dict(im=simg, glow=glow_of(simg, 18, LIME)[0], t=self.at(line, st['at']),
                             x=st.get('x', XC), y=st.get('y', 1160), rot=st.get('rotate', -4)))
            self.events.append((stks[-1]['t'], 'thud'))

        def draw(fr, t):
            u = (t - T) / max(T1 - T, 0.1)
            cur = max([i for i, p in enumerate(photos) if t >= p['t']] or [0])
            p = photos[cur]
            img = p['P'].at(u)
            v = t - p['t']
            yy = 0
            if cur > 0 and v < 0.45:                      # next photo slides up inside the photo area
                prev = photos[cur - 1]['P'].at(u)
                yy = int(ph * (1 - expo(v / 0.45)))
                prev.paste(img.crop((0, 0, W, ph - yy)), (0, yy))
                ImageDraw.Draw(prev).rectangle((0, max(0, yy - 3), W, yy + 3), fill=ACC)
                img = prev
            fr.paste(img, (0, 0))
            fr.alpha_composite(self.shade_for(ph))
            b = p['behind']
            if b is not None and t >= b['t']:             # the word behind the player rises in
                w = t - b['t']
                e = ease_out(min(1, w / 0.5))
                yb = b['y'] + yy + 110 * (1 - e)
                place(fr, b['glow'], W / 2, yb, 1.08 - 0.08 * e, 0.55 * min(1, w / 0.3))
                place(fr, b['im'], W / 2, yb, 1.08 - 0.08 * e, min(1, w / 0.25))
            if isinstance(p['P'], PopPhoto):
                self.draw_pop(fr, p['P'], u, y=yy, h=ph - yy)
            if lab is not None:
                reveal(fr, lab, M, y0, (t - tLab) / 0.45)
            for im, ta, yt in titles:
                reveal(fr, im, M - 4 - 24, yt, (t - (ta - 0.05)) / 0.55)
            if es and t > tE:
                w = t - tE
                place(fr, eimg, es['x'], es['y'], ease_out_back(w / 0.3, 2.4), min(1, w / 0.08),
                      rot=es.get('rot', 12) + 6 * math.sin(w * 9) * math.exp(-w * 2))
            for stk in stks:
                if t > stk['t']:
                    w = t - stk['t']
                    k = 1 + 1.3 * (1 - ease_out(w / 0.18, 3))
                    place(fr, stk['glow'], stk['x'], stk['y'], k, 0.8 * min(1, w / 0.1), rot=stk['rot'])
                    place(fr, stk['im'], stk['x'], stk['y'], k, min(1, w / 0.06), rot=stk['rot'])
        return draw

    # ---------------------------------------------------------------- end card: follow pop-up
    def follow_card(self, c):
        """Static parts of the follow pop-up: card with shadow, avatar, name, both button states."""
        CW, CH, R, pad = 760, 300, 46, 50
        card = Image.new('RGBA', (CW, CH), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle((0, 0, CW - 1, CH - 1), R, fill=(250, 250, 252, 255))
        D = 140                                            # avatar: the kouponaki icon in a lime ring
        av = Image.new('RGBA', (D, D), (0, 0, 0, 0))
        ImageDraw.Draw(av).ellipse((0, 0, D - 1, D - 1), fill=ACC + (255,))
        ImageDraw.Draw(av).ellipse((8, 8, D - 9, D - 9), fill=(16, 22, 26, 255))
        icon = Image.open(os.path.join(HERE, 'assets', 'kouponaki_logo.png')).convert('RGBA').crop((0, 0, 134, 84))
        icon = icon.resize((104, int(84 * 104 / 134)), Image.LANCZOS)
        av.alpha_composite(icon, ((D - icon.width) // 2, (D - icon.height) // 2))
        card.alpha_composite(av, (30, 30))
        name = text_img(c.get('follow_name', 'kouponaki.com'), F('Black', 52), INK, tracking=-1)
        card.alpha_composite(name, (196, 44))
        sub_txt = c.get('follow_sub', 'Για περισσότερα «Ήξερες ότι;»')
        size = 31
        while size > 20:
            sub = text_img(sub_txt, F('Bold', size), (112, 118, 128))
            if sub.width <= CW - 196 - 24:
                break
            size -= 1
        card.alpha_composite(sub, (196, 112))
        bw, bh = CW - 60, 100
        txt_f = fnt('FiraSansExtraCondensed-Black', 58)
        follow = _pill(bw, bh, ACC, top=(255, 255, 255, 60))
        t1, i1 = plain_text(c.get('follow_button', 'ΚΑΝΕ FOLLOW'), txt_f, INK), _icon('plus', 40, INK)
        x = (bw - (i1.width + 18 + t1.width)) // 2
        follow.alpha_composite(i1, (x, (bh - i1.height) // 2))
        follow.alpha_composite(t1, (x + i1.width + 18, (bh - t1.height) // 2 + 2))
        done = _pill(bw, bh, (22, 26, 32), outline=ACC)
        t2, i2 = plain_text(c.get('following_button', 'FOLLOWING'), txt_f, ACC), _icon('check', 42, ACC)
        x = (bw - (i2.width + 18 + t2.width)) // 2
        done.alpha_composite(i2, (x, (bh - i2.height) // 2))
        done.alpha_composite(t2, (x + i2.width + 18, (bh - t2.height) // 2 + 2))
        shadow = Image.new('L', (CW + 2 * pad, CH + 2 * pad), 0)
        ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 18, pad + CW, pad + CH + 18), R, fill=140)
        badge_plus, badge_ok = Image.new('RGBA', (52, 52), (0, 0, 0, 0)), Image.new('RGBA', (52, 52), (0, 0, 0, 0))
        ImageDraw.Draw(badge_plus).ellipse((0, 0, 51, 51), fill=(255, 59, 92, 255), outline=(250, 250, 252, 255), width=5)
        badge_plus.alpha_composite(_icon('plus', 24, WHITE, 6), (14, 14))
        ImageDraw.Draw(badge_ok).ellipse((0, 0, 51, 51), fill=ACC + (255,), outline=(250, 250, 252, 255), width=5)
        badge_ok.alpha_composite(_icon('check', 26, INK, 6), (13, 14))
        glow, gpad = glow_of(card, 26, ACC)
        return dict(card=card, shadow=shadow.filter(ImageFilter.GaussianBlur(22)), pad=pad, CW=CW, CH=CH,
                    follow=follow, done=done, btn=(30, 180, bw, bh), plus=badge_plus, ok=badge_ok,
                    av_badge=(30 + D - 40, 30 + D - 44), glow=glow, gpad=gpad)

    def m_end_follow(self, c):
        """End card: «Ήξερες ότι;» sticker, comment badge, and a follow pop-up that gets 'tapped' (sound + burst)."""
        plate = self.dark_plate(c.get('photo', self.cfg.get('hook_photo')), 0.2)
        T0, L = self.t_end, len(self.vo) - 1
        badge = self.cfg.get('cta_badge', '') is not None

        def word_t(w, default):
            try:
                return self.at(L, {'word': w})
            except ValueError:
                return default
        tS = word_t('σχόλια', T0 + 0.85)
        tF = max(T0 + 0.5, word_t(c.get('follow_word', 'φόλοου'), T0 + 1.2) - 0.3)   # pop-up as "follow" is said
        tP, tTap = tF + 0.55, tF + 1.05
        tOn = tTap + 0.06
        self.total = max(self.total, tOn + 1.7)            # room for the whole animation
        k = self.follow_card(c)
        CX, CY = XC, c.get('follow_y', 860)
        bx, by, bw, bh = k['btn']
        bc = (CX - k['CW'] / 2 + bx + bw / 2, CY - k['CH'] / 2 + by + bh / 2)        # button centre on screen
        target = (bc[0] + 240, bc[1] + 10)              # right part of the button, clear of the text
        pointer, bell = emoji_img('👆', 132), emoji_img('🔔', 78)
        floaters = [(emoji_img(e, 64), rnd) for e, rnd in zip('💚⚽🔥💛⭐', random.Random(11).sample(range(-300, 300, 30), 5))]
        rng = random.Random(5)
        sparks = [dict(a=rng.uniform(0, 2 * math.pi), v=rng.uniform(520, 1150), r=rng.uniform(5, 12),
                       col=rng.choice([ACC, ACC, YELLOW, WHITE]), star=rng.random() < 0.35) for _ in range(34)]
        if badge:
            self.events.append((tS, 'pop'))
        self.events += [(T0 + 0.2, 'boom'), (tF, 'whoosh'), (tF + 0.06, 'pop'), (tP, 'whoosh'),
                        (tTap, 'click'), (tOn, 'notify'), (tOn + 0.02, 'confetti')]

        def draw(fr, t):
            fr.paste(plate, (0, 0))
            u = t - T0
            p = ease_out_back((u - 0.05) / 0.55)            # the sticker, as on every end card
            if p > 0.02:
                fr.paste(self.intro.draw_sticker(fr.copy(), 0, XC, 430, 0.56 * p, glow=min(1, u / 0.5)))
            if badge:
                p = ease_out_back((t - tS) / 0.5, 2.0)
                if p > 0.02:
                    pulse = 1 + 0.035 * math.sin(2 * math.pi * 1.6 * (t - tS))
                    place(fr, self.badge_glow, XC, 1200, p * pulse, 0.6)
                    place(fr, self.badge, XC, 1200, p * pulse)
            v = t - tF
            if v <= 0:
                return
            card = k['card'].copy()
            on = t >= tOn
            press = 1 - 0.07 * math.sin(math.pi * min(1, max(0, (t - tTap) / 0.16)))
            btn = k['done'] if on else k['follow']
            if press < 0.999:
                btn = btn.resize((int(bw * press), int(bh * press)), Image.BILINEAR)
            card.alpha_composite(btn, (int(bx + (bw - btn.width) / 2), int(by + (bh - btn.height) / 2)))
            if on:                                          # the avatar's red plus turns into a check
                q = ease_out_back((t - tOn) / 0.35, 2.2)
                b = k['ok'].resize((max(1, int(52 * q)), max(1, int(52 * q))), Image.BILINEAR)
                card.alpha_composite(b, (int(k['av_badge'][0] + 26 - b.width / 2), int(k['av_badge'][1] + 26 - b.height / 2)))
            else:
                card.alpha_composite(k['plus'], k['av_badge'])
            top = CY - k['CH'] / 2
            if on:                                          # emoji pop out from behind the card and float up
                for i, (em, dx) in enumerate(floaters):
                    w = t - tOn - 0.07 * i
                    if 0 < w < 1.5:
                        x = CX + dx * 1.05 + 22 * math.sin(w * 5 + i)
                        y = top + 50 - 185 * ease_out(min(1, w / 1.5))
                        place(fr, em, x, y, 0.85 + 0.15 * ease_out_back(min(1, w / 0.4), 2.5), 1 - max(0, (w - 1.0) / 0.5))
            comp = Image.new('RGBA', k['shadow'].size, (0, 0, 0, 0))
            comp.paste((0, 0, 0, 255), (0, 0), k['shadow'])
            comp.alpha_composite(card, (k['pad'], k['pad']))
            s = ease_out_back(v / 0.45, 1.9)
            if on:                                          # a little bump when it switches to FOLLOWING
                s *= 1 + 0.045 * math.sin(math.pi * min(1, (t - tOn) / 0.3))
            bob = 5 * math.sin(2 * math.pi * 0.7 * max(0, v - 0.45))
            rot = -7 * (1 - ease_out(min(1, v / 0.45)))
            if on:
                g = math.sin(math.pi * min(1, (t - tOn) / 0.9))
                place(fr, k['glow'], CX, CY + bob, s, 0.9 * g)
            place(fr, comp, CX, CY + bob, s, min(1, v / 0.12), rot)
            if v > 0.25:                                    # bell on the corner; it rings after the follow
                ring = 22 * math.sin(2 * math.pi * 5 * (t - tOn)) * math.exp(-3 * (t - tOn)) if on else 0
                place(fr, bell, CX + k['CW'] / 2 - 40, CY - k['CH'] / 2 + 2 + bob, ease_out_back((v - 0.25) / 0.4, 2.2), 1, ring)
            if tP <= t < tOn + 0.75:                        # a finger comes in, taps, and leaves
                e = ease_out(min(1, (t - tP) / 0.4))
                x = target[0] + 230 * (1 - e)
                y = target[1] + 330 * (1 - e) + pointer.height * 0.42
                sc = 1 - 0.14 * math.sin(math.pi * min(1, max(0, (t - tTap) / 0.16)))
                fade = 1 - min(1, max(0, (t - tOn - 0.35) / 0.4))
                place(fr, pointer, x, y + 40 * (1 - fade), sc, fade, 8)
            if on and t - tOn < 1.1:                        # burst of sparks from the button
                w = t - tOn
                d = ImageDraw.Draw(fr)
                for sp in sparks:
                    dist = sp['v'] * (1 - math.exp(-3.2 * w)) / 3.2
                    x = target[0] + math.cos(sp['a']) * dist * 1.15
                    y = target[1] + math.sin(sp['a']) * dist + 380 * w * w
                    r = sp['r'] * (1 - w / 1.1)
                    a = int(255 * max(0, 1 - w / 1.1))
                    if sp['star']:
                        pts = [(x + math.cos(i * math.pi / 4) * (r * 1.8 if i % 2 == 0 else r * 0.6),
                                y + math.sin(i * math.pi / 4) * (r * 1.8 if i % 2 == 0 else r * 0.6)) for i in range(8)]
                        d.polygon(pts, fill=sp['col'] + (a,))
                    else:
                        d.ellipse((x - r, y - r, x + r, y + r), fill=sp['col'] + (a,))
        return draw

    # ---------------------------------------------------------------- end card: sticker + logo + follow + badge
    def m_end(self):
        c = self.cfg.get('end', {})
        if c.get('style', 'classic' if 'lines' in c else 'follow') == 'follow':
            return self.m_end_follow(c)
        plate = self.dark_plate(c.get('photo', self.cfg.get('hook_photo')), 0.2)
        follow = ['Κάνε follow', 'για περισσότερα!']     # every video ends on the follow ask
        lines = [text_img(l, F('Black', 80), ACC if (l == follow[1] and 'lines' not in c) else WHITE, tracking=-2)
                 for l in c.get('lines', follow)]
        badge = self.cfg.get('cta_badge', '') is not None  # "cta_badge": null = no comment badge
        T0 = self.t_end
        self.events += [(T0 + 0.2, 'boom'), (T0 + 0.85, 'pop')]

        def draw(fr, t):
            fr.paste(plate, (0, 0))
            u = t - T0
            p = ease_out_back((u - 0.05) / 0.55)
            if p > 0.02:
                fr.paste(self.intro.draw_sticker(fr.copy(), 0, XC, 520, 0.62 * p, glow=min(1, u / 0.5)))
            p = ease_out_back((u - 0.25) / 0.55)
            if p > 0.02:
                place(fr, self.k_big, XC, 800, p)
            for i, im in enumerate(lines):
                reveal(fr, im, XC - im.width / 2, 880 + i * 88, (u - 0.45 - 0.12 * i) / 0.5)
            p = ease_out_back((u - 0.85) / 0.5, 2.0) if badge else 0
            if p > 0.02:
                pulse = 1 + 0.035 * math.sin(2 * math.pi * 1.6 * u)
                place(fr, self.badge_glow, XC, 1125, p * pulse, 0.6)
                place(fr, self.badge, XC, 1125, p * pulse)
        return draw

    # ---------------------------------------------------------------- header + compositing
    def hheader(self, fr, t, show=True):
        """Only the small kouponaki.com logo: no progress bar, no «Ήξερες ότι;» sticker over the photos."""
        if show and t >= self.fly0:
            u = t - self.fly0
            place(fr, self.k_small, 60 + self.k_small.width / 2, LOGO_Y - 110 * (1 - ease_out(min(1, u / 0.5))), 1, min(1, u / 0.3))
        return fr                                         # no «Ήξερες ότι;» sticker up here: it would cover the photos

    # ---------------------------------------------------------------- cover image
    def make_cover(self, out):
        """Only on request (--cover): cover (1080x1920) for TikTok / Reels: photo (pop-out player + huge word behind him if set), the
        «Ήξερες ότι;» sticker, a big title and the logo. All of it sits inside the middle 3:4 the profile grids show."""
        c = self.cfg.get('cover') or {}
        path = c.get('photo', self.cfg.get('hook_photo'))
        py = c.get('photo_y', 0)                          # photo lower down = room for the sticker on top
        ph = c.get('ph', 1300 if py == 0 else 1150)
        P = self.photo_of(path, ph, tuple(c.get('focus', self.cfg.get('hook_focus', (0.5, 0.42)))), c.get('popout'))
        fr = self.dark_plate(path, 0.18).copy()
        img = P.at(0.0).convert('RGBA')
        y = np.arange(ph, dtype=np.float32)
        a = np.minimum(np.clip(y / 220, 0, 1) if py else np.ones(ph, np.float32), np.clip((ph - y) / 420, 0, 1))
        img.putalpha(Image.fromarray((np.repeat(a[:, None], W, axis=1) * 255).astype(np.uint8), 'L'))
        fr.alpha_composite(img, (0, py))
        if c.get('behind'):
            im, glow = self.behind_img(c['behind'])
            yb = c['behind'].get('y', 640)
            place(fr, glow, W / 2, yb, 1, 0.55)
            place(fr, im, W / 2, yb)
        if isinstance(P, PopPhoto):
            self.draw_pop(fr, P, 0.0, y=py)
        fr = self.intro.draw_sticker(fr.copy(), 0, W / 2, c.get('sticker_y', 345), c.get('sticker_scale', 0.5), glow=1.0)
        hook = self.cfg.get('hook')
        hook = hook['text'] if isinstance(hook, dict) else (hook or '')
        words = (c.get('title') or caps(hook)).split()
        acc = {norm(w) for w in c.get('accent', self.cfg.get('hook_accent', []))}
        for size in range(176, 96, -6):                   # biggest size that fits in 3 lines
            f = fnt('FiraSansExtraCondensed-Black', size)
            ims = [plain_text(w, f, ACC if norm(w) in acc else WHITE) for w in words]
            gap, lines, cur, cw = int(size * 0.22), [], [], 0
            for im in ims:
                if cur and cw + gap + im.width > W - 120:
                    lines.append(cur)
                    cur, cw = [], 0
                cw += (gap if cur else 0) + im.width
                cur.append(im)
            lines.append(cur)
            if len(lines) <= 3:
                break
        lh = int(size * 0.98)
        top = c.get('title_bottom', 1545) - lh * len(lines)
        block = Image.new('RGBA', (W, lh * len(lines) + 40), (0, 0, 0, 0))
        for i, row in enumerate(lines):
            x = (W - (sum(im.width for im in row) + gap * (len(row) - 1))) // 2
            for im in row:
                block.alpha_composite(im, (x, i * lh + 20))
                x += im.width + gap
        glow, gp = glow_of(block, 26, (0, 0, 0))
        fr.alpha_composite(with_alpha(glow, 0.8), (-gp, top - 20 - gp))
        fr.alpha_composite(block, (0, top - 20))
        if c.get('badge'):
            place(fr, self.pill_img(c['badge'], 44), W / 2, top - 62)
        place(fr, self.k_small, W / 2, c.get('logo_y', 1625))
        fr.convert('RGB').save(out)
        print(f'cover: {out}')

    # ---------------------------------------------------------------- loud, voice-first mix
    def audio(self):
        """Voice first and loud: the SFX sit lower and duck more under the voice, and the mix is brought to
        LOUDNESS (LUFS) through a look-ahead peak limiter. (A compressor did not help: the TTS voice is already even,
        only its peaks stand out, and those are the limiter's job.)"""
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
        duck = smooth(1 - 0.65 * np.clip(rms / 0.05, 0, 1), int(0.12 * SR))
        out = (vo + 0.75 * sfx * duck)[:int(self.total * SR)]
        fade = int(0.12 * SR)
        out[-fade:] *= np.linspace(1, 0, fade)
        out *= 0.95 / max(np.abs(out).max(), 1e-6)
        raw, path = os.path.join(CACHE, 'hybrid_mix_raw.wav'), os.path.join(CACHE, 'hybrid_mix.wav')
        with wave.open(raw, 'wb') as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
            w.writeframes((out * 32767).astype(np.int16).tobytes())
        gain = LOUDNESS - (lufs(raw) + 3.01)               # the mono mix plays on both channels: +3 dB
        for _ in range(6):                                # the limiter takes part of the gain back: push and redo
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', raw, '-af',
                            f'volume={gain:.2f}dB,alimiter=limit={PEAK}:attack=3:release=60:level=false:latency=true,'
                            'pan=stereo|c0=c0|c1=c0',             # same signal on both sides (-ac 2 would drop 3 dB)
                            '-ar', str(SR), '-c:a', 'pcm_s16le', path], check=True)
            got = lufs(path)
            if abs(got - LOUDNESS) < 0.3:
                break
            gain = min(10.0, gain + 2.5 * (LOUDNESS - got))     # ~0.3 dB louder per dB of drive here
        print(f'mix: {got:.1f} LUFS (target {LOUDNESS})')
        return path

    def frame(self, n):
        t = n / FPS
        k = max(i for i, s in enumerate(self.starts) if s <= t + 1e-9)
        u = t - self.starts[k]
        fr = self.swipe(self.seg(k - 1, t), self.seg(k, t), expo(u / TR)) if k > 0 and u < TR else self.seg(k, t)
        last = k == len(self.starts) - 1
        if t >= self.fly0:
            fr = self.particles(fr, t, 0.35)
        fr = self.hheader(fr, t, show=not last)
        if self.captions_on(k):
            self.draw_captions(fr, t)
        return self.grain(fr, n)


if __name__ == '__main__':
    st = Hybrid(sys.argv[1])
    if sys.argv[2] == '--cover':
        st.make_cover(sys.argv[3])
    elif sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(st.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else 'preview.png')
        print('vo starts', [round(x, 2) for x in st.vo_starts], 'scenes', [round(x, 2) for x in st.scene_t],
              'end card', round(st.t_end, 2), 'total', round(st.total, 2), 'fly', round(st.fly0, 2), round(st.fly_end, 2))
    else:
        st.render(sys.argv[2])
