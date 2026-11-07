#!/usr/bin/env python3
"""'Ήξερες ότι;' — HYBRID theme (test): the modern layout with the elements of the current style.

    python3 make_hybrid.py configs/apollon_legia_hybrid.json ../videos/TEST_hybrid_apollon_legia.mp4
    python3 make_hybrid.py configs/apollon_legia_hybrid.json --preview 1,4,8 preview.png

From the modern test (make_modern.py): big photos with slow push-ins, clean Inter Display text with masked reveals,
the map with coordinates and a live distance counter, the 0'-90' match timeline, pill captions, progress bar,
swipe-up transitions, soft grain.
From the current style (make_story.py): the animated «Ήξερες ότι;» sticker (intro pop, bulb, sticker in the header),
the mascot, chunky stickers (ΙΣΤΟΡΙΚΟ!, ΣΑΝΓΚΟΪ 56', VS ΛΕΓΚΙΑ), team plates with the crest and flip-clock tiles,
the crest on rotating rays, confetti, emoji (✈️ 🇨🇾 🇵🇱 👑), floating particles and the «ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ 👇» badge.
"""
import sys, os, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from make_video import (HERE, W, H, FPS, ease, ease_out, ease_out_back, with_alpha, place, glow_of, fnt, Intro,
                        calendar_icon, LIME, sfx_ding, sfx_boom)
from make_story import (fit_text, plain_text, emoji_img, tile_parts, odometer_strip, digit_tile, roll, step_value,
                        shade, sfx_confetti, XC, YELLOW, STICKER_Y, STICKER_S, LOGO_Y)
from make_modern import Modern, Photo, F, text_img, reveal, expo, shadowed, BG, WHITE, MUTED, ACC, INK, M, TR


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

    def sfx_lib(self):
        lib = super().sfx_lib()
        lib.update({'ding': (sfx_ding, 0.75), 'boom_big': (lambda: sfx_boom(1.4), 0.6), 'confetti': (sfx_confetti, 0.45)})
        return lib

    # ---------------------------------------------------------------- intro: sticker pop, then the question
    def m_intro(self):
        cfg = self.cfg
        P = Photo(self.load_photo(cfg.get('hook_photo')), cfg.get('hook_ph', 1120), tuple(cfg.get('hook_focus', (0.5, 0.45))))
        words = self.disp_words(0)
        k = 0
        while k < len(words) and words[k][3] in ('ηξερες', 'οτι'):
            k += 1
        rest = words[k:]
        split = max((rest[0][1] - 0.15) if rest else self.t_intro - 0.6, self.intro.t_hit + 0.45)
        self.fly0, self.fly_end = split, split + 0.6
        size = cfg.get('hook_size', 122)
        f, tr, sp = F('Black', size), -int(size * 0.025), int(size * 0.26)
        acc = {w.lower() for w in cfg.get('hook_accent', [])}
        from make_story import norm
        acc = {norm(w) for w in cfg.get('hook_accent', [])}
        lines, cur, cw, pad = [], [], 0, 24
        for w, t0, t1, n in rest:
            im, pad = shadowed(text_img(w, f, ACC if n in acc else WHITE, tracking=tr))
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
        self.events += [(0.0, 'riser'), (self.intro.t_hit, 'boom_big'), (self.intro.t_bulb, 'ding')]

        def draw(fr, t):
            if t < split:                                 # the original sticker intro, untouched
                fr.paste(self.intro.frame(t).convert('RGBA'), (0, 0))
                return
            x = ease((t - split) / 0.5)
            self.photo_bg(fr, P, t / max(self.t_intro, 0.1), dim=cfg.get('hook_dim', 0.32))
            if x < 1:
                fr.alpha_composite(with_alpha(self.intro.background(t), 1 - x))
            for im, xx, yy, t0 in placed:
                reveal(fr, im, xx, yy, (t - (t0 - 0.06)) / 0.5)
            if t < self.fly_end:                          # sticker flies up into the header
                e = ease((t - self.fly0) / (self.fly_end - self.fly0))
                s0 = self.intro.logo_state(self.fly0)[0]
                fr.paste(self.intro.draw_sticker(fr.copy(), t, W / 2, 880 + (STICKER_Y - 880) * e,
                                                 s0 + (STICKER_S - s0) * e, glow=0.9))
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

        def draw(fr, t):
            if P:
                self.photo_bg(fr, P, (t - T) / max(T1 - T, 0.1))
            else:
                fr.paste(plate, (0, 0))
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
        P = Photo(self.load_photo(sc['photo']), sc.get('ph', 1000), tuple(sc.get('focus', (0.5, 0.45))))
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
        lines, y = [], sc.get('y', 810)
        for wd in sc['words']:
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

    # ---------------------------------------------------------------- end card: sticker + logo + comment badge
    def m_end(self):
        c = self.cfg.get('end', {})
        plate = self.dark_plate(c.get('photo', self.cfg.get('hook_photo')), 0.2)
        lines = [text_img(l, F('Black', 80), WHITE, tracking=-2) for l in c.get('lines', ['Ποια ιστορική στιγμή', 'θες να δούμε;'])]
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
            p = ease_out_back((u - 0.85) / 0.5, 2.0)
            if p > 0.02:
                pulse = 1 + 0.035 * math.sin(2 * math.pi * 1.6 * u)
                place(fr, self.badge_glow, XC, 1125, p * pulse, 0.6)
                place(fr, self.badge, XC, 1125, p * pulse)
        return draw

    # ---------------------------------------------------------------- header + compositing
    def hheader(self, fr, t, show=True):
        a = min(1, t / 0.5)
        lay = Image.new('RGBA', (W, 12), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.rounded_rectangle((M, 3, W - M, 9), 3, fill=(255, 255, 255, int(55 * a)))
        xp = M + (W - 2 * M) * min(1, t / self.total)
        if xp > M + 6:
            d.rounded_rectangle((M, 3, xp, 9), 3, fill=ACC + (int(255 * a),))
        fr.alpha_composite(lay, (0, 128))
        if show and t >= self.fly0:
            u = t - self.fly0
            place(fr, self.k_small, 60 + self.k_small.width / 2, LOGO_Y - 110 * (1 - ease_out(min(1, u / 0.5))), 1, min(1, u / 0.3))
        if show and t >= self.fly_end:
            fr = self.intro.draw_sticker(fr, t, W / 2, STICKER_Y, STICKER_S * (1 + 0.012 * math.sin(2 * math.pi * 0.8 * t)), glow=0.9)
        return fr

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
    if sys.argv[2] == '--preview':
        ts = [float(x) for x in sys.argv[3].split(',')]
        g = Image.new('RGB', (360 * len(ts), 640))
        for i, t in enumerate(ts):
            g.paste(st.frame(int(t * FPS)).resize((360, 640)), (360 * i, 0))
        g.save(sys.argv[4] if len(sys.argv) > 4 else 'preview.png')
        print('vo starts', [round(x, 2) for x in st.vo_starts], 'scenes', [round(x, 2) for x in st.scene_t],
              'end card', round(st.t_end, 2), 'total', round(st.total, 2), 'fly', round(st.fly0, 2), round(st.fly_end, 2))
    else:
        st.render(sys.argv[2])
