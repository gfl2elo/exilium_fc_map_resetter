"""Local OCR and Roman-numeral node detection; no network service."""
import re
import shutil

import cv2
import numpy as np
import pytesseract
from PIL import Image


def configure_ocr(path=None):
    path = path or shutil.which('tesseract')
    if not path:
        raise RuntimeError('Tesseract was not found. Set tesseract in settings.json.')
    pytesseract.pytesseract.tesseract_cmd = path


def text(image, box=None, psm=6):
    if box:
        image = image.crop(tuple(round(v * s) for v, s in zip(box, image.size * 2)))
    # Small HUD labels can turn the slash in "1/10" into a 7 at native
    # resolution. Upscale before OCR while keeping exact screen verification.
    if image.height < 64:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    return pytesseract.image_to_string(image, config=f'--psm {psm}', timeout=10)


def tile_type(image):
    # The right-hand card includes the resource description even under an enemy.
    value = text(image, (.79, .085, .985, .72)).lower()
    found = [kind for kind, words in [('shovel', ('mining', 'excavat')), ('compass', ('survey',)),
                                     ('radar', ('exploration', 'prob'))] if any(word in value for word in words)]
    return found[0] if len(found) == 1 else None


def normalized(image):
    return cv2.resize(np.asarray(image.convert('RGB')), (2048, round(image.height * 2048 / image.width)))


def nodes(image):
    """Return badge centers in 2048-wide coordinates, excluding fixed HUD areas."""
    rgb = normalized(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = ((rgb.min(axis=2) > 125) & (rgb.max(axis=2).astype(int) - rgb.min(axis=2) < 40)).astype('uint8')
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    bars = []
    for x, y, w, h, area in stats[1:]:
        if 2 <= w <= 6 and 11 <= h <= 20 and area / (w * h) > .78 and h / w > 2.5:
            if 180 < x < 1920 and 100 < y < gray.shape[0] - 75:
                if not (x > 1650 and y > gray.shape[0] * .79):
                    bars.append((int(x), int(y), int(w), int(h)))
    groups = []
    for b in sorted(bars):
        for g in groups:
            p = g[-1]
            if 0 <= b[0] - p[0] - p[2] <= 5 and abs(b[1] - p[1]) <= 2 and abs(b[3] - p[3]) <= 2:
                g.append(b)
                break
        else:
            groups.append([b])
    result = []
    for g in groups:
        if not 1 <= len(g) <= 3:
            continue
        x, y, _, h = g[0]
        right = g[-1][0] + g[-1][2]
        # Numerals are framed by a black circular badge, not ordinary white text.
        border = gray[y - 2:y + h + 2, x - 2:right + 2]
        if np.median(border[:2]) > 90 or np.median(border[-2:]) > 90:
            continue
        result.append((float((x + right) / 2), float(y + h / 2)))
    return sorted(result, key=lambda p: (p[1], p[0]))


def pan_shift(before, after):
    """Measure actual camera translation, so overlapping nodes are counted once."""
    a, b = [cv2.cvtColor(normalized(im), cv2.COLOR_RGB2GRAY) for im in (before, after)]
    mask = np.zeros_like(a)
    mask[120:-150, 210:1600] = 255
    orb = cv2.ORB_create(nfeatures=3000)
    ka, da = orb.detectAndCompute(a, mask)
    kb, db = orb.detectAndCompute(b, mask)
    if da is None or db is None:
        raise RuntimeError('Cannot measure camera movement.')
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .7 * n.distance]
    if len(good) < 15:
        raise RuntimeError('Too few map landmarks to verify the drag.')
    shifts = np.array([np.subtract(kb[m.trainIdx].pt, ka[m.queryIdx].pt) for m in good])
    median = np.median(shifts, axis=0)
    inliers = shifts[np.linalg.norm(shifts - median, axis=1) < 4]
    if len(inliers) < 15:
        raise RuntimeError('Camera movement is ambiguous; leaving expedition intact.')
    return np.median(inliers, axis=0)
