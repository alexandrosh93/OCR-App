#!/usr/bin/env python3
"""Cut the main subject (a player) out of a photo, for the pop-out / depth effect of template 3.

    python3 make_cutout.py posts/x.jpg --rect X0 Y0 X1 Y1 [--fg X,Y,R ...] [--bg X,Y,R ...] [--preview out.png]
    python3 make_cutout.py posts/x.jpg --poly X,Y X,Y ... [--fg ...] [--bg ...]

--rect: a box around the player (pixels of the original photo); --poly: a rough outline instead, better when
the background around the player is busy (LED boards). --fg / --bg: extra circles that are surely the player /
surely background (e.g. an opponent's arm crossing the player), when the first pass gets them wrong.
Writes posts/cutouts/<name>_fg.png (the photo with the player as alpha) and posts/cutouts/<name>_bg.jpg (the
photo with the player filled in), which make_hybrid.py picks up for "popout": true photos.
"""
import argparse
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def circle(spec):
    x, y, r = (int(float(v)) for v in spec.split(','))
    return x, y, r


def point(spec):
    x, y = (int(float(v)) for v in spec.split(','))
    return x, y


def cutout(path, rect=None, fg=(), bg=(), iters=8, poly=None):
    img = cv2.imread(path)
    h, w = img.shape[:2]
    mask = np.full((h, w), cv2.GC_BGD, np.uint8)
    if poly:                                      # rough outline: inside = probably player, a band around = maybe
        pts = np.array(poly, np.int32)
        band = np.zeros((h, w), np.uint8)
        cv2.fillPoly(band, [pts], 255)
        mask[cv2.dilate(band, np.ones((31, 31), np.uint8)) > 0] = cv2.GC_PR_BGD
        mask[band > 0] = cv2.GC_PR_FGD
    else:
        x0, y0, x1, y1 = rect
        mask[y0:y1, x0:x1] = cv2.GC_PR_FGD
    for x, y, r in fg:
        cv2.circle(mask, (x, y), r, cv2.GC_FGD, -1)
    for x, y, r in bg:
        cv2.circle(mask, (x, y), r, cv2.GC_BGD, -1)
    bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, mask, None, bgm, fgm, iters, cv2.GC_INIT_WITH_MASK)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)       # keep the player, drop specks
    if n > 1:
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        big = stats[1:, cv2.CC_STAT_AREA].max()
        m = np.isin(lab, [i for i in range(1, n) if i == keep or stats[i, cv2.CC_STAT_AREA] > 0.15 * big]).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_CLOSE, k), cv2.MORPH_OPEN, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((m == 0).astype(np.uint8), 4)
    sure_bg = {lab[y, x] for x, y, r in bg}
    for i in range(1, n):                         # fill enclosed holes (white shirt numbers), not marked background
        x, y, bw, bh, area = stats[i]
        if x > 0 and y > 0 and x + bw < w and y + bh < h and area < 0.05 * (m > 0).sum() and i not in sure_bg:
            m[lab == i] = 255
    alpha = cv2.GaussianBlur(m, (0, 0), 1.2)                        # soft, anti-aliased edge
    fill = cv2.inpaint(img, cv2.dilate(m, k, iterations=2), 9, cv2.INPAINT_TELEA)
    return img, alpha, fill


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('photo')
    ap.add_argument('--rect', nargs=4, type=int)
    ap.add_argument('--poly', nargs='+', type=point)
    ap.add_argument('--fg', action='append', default=[], type=circle)
    ap.add_argument('--bg', action='append', default=[], type=circle)
    ap.add_argument('--iters', type=int, default=8)
    ap.add_argument('--preview')
    a = ap.parse_args()
    if not (a.rect or a.poly):
        ap.error('give --rect or --poly')
    img, alpha, fill = cutout(a.photo, a.rect, a.fg, a.bg, a.iters, a.poly)
    name = os.path.splitext(os.path.basename(a.photo))[0]
    out = os.path.join(HERE, 'posts', 'cutouts')
    os.makedirs(out, exist_ok=True)
    cv2.imwrite(os.path.join(out, f'{name}_fg.png'), np.dstack([img, alpha]))
    cv2.imwrite(os.path.join(out, f'{name}_bg.jpg'), fill, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if a.preview:                                                  # player on lime | filled background
        lime = np.zeros_like(img)
        lime[:] = (60, 255, 182)
        f = alpha[..., None].astype(np.float32) / 255
        cv2.imwrite(a.preview, np.hstack([(img * f + lime * (1 - f)).astype(np.uint8), fill]))
    print(f'{name}: fg {int((alpha > 128).sum())} px -> posts/cutouts/{name}_fg.png, _bg.jpg')


if __name__ == '__main__':
    main()
