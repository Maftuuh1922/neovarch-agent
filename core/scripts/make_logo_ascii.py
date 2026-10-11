"""Bake the Neovarch star mark into a static braille text asset.

Developer tool only (needs Pillow). The CLI reads the generated text files and
never imports an image library at runtime.

    python core/scripts/make_logo_ascii.py star-logo-transparent.png core/neovarch/tui/assets

Writes ``logo.txt`` (braille cells) and ``logo.mask`` (same grid: ``w`` = a cell of
the bone-white star, ``r`` = a cell of the red debris, space = empty).
Defaults (40 columns, thresholds 40/175) produced the committed asset.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

# braille dot bit for (x, y) inside a 2x4 cell
BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (1, 0): 0x08,
        (1, 1): 0x10, (1, 2): 0x20, (0, 3): 0x40, (1, 3): 0x80}


def bake(src: Path, out: Path, cols: int = 40, star_threshold: int = 40, red_threshold: int = 175) -> None:
    im = Image.open(src).convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    w = cols * 2
    h = round(w * im.height / im.width / 4) * 4
    big = im.resize((w * 4, h * 4), Image.LANCZOS)
    px = big.load()
    star = Image.new("L", big.size)
    red = Image.new("L", big.size)
    sp, rp = star.load(), red.load()
    for y in range(big.height):
        for x in range(big.width):
            r, g, _b, a = px[x, y]
            if a < 120:
                continue
            if g > 150 and r > 150:      # white strokes of the star
                sp[x, y] = 255
            elif r > 140 and g < 110:    # red ring and debris
                rp[x, y] = 255
    star = star.filter(ImageFilter.MaxFilter(5)).resize((w, h), Image.BOX).point(
        lambda v: 255 if v > star_threshold else 0)
    red = red.resize((w, h), Image.BOX).point(lambda v: 255 if v > red_threshold else 0)
    s, rr = star.load(), red.load()
    lines, masks = [], []
    for cy in range(0, h, 4):
        line, mask = [], []
        for cx in range(0, w, 2):
            code, n_star = 0, 0
            for (dx, dy), bit in BITS.items():
                x, y = cx + dx, cy + dy
                if x >= w or y >= h:
                    continue
                if s[x, y]:
                    code |= bit
                    n_star += 1
                elif rr[x, y]:
                    code |= bit
            line.append(chr(0x2800 + code) if code else " ")
            mask.append(("w" if n_star else "r") if code else " ")
        lines.append("".join(line).rstrip())
        masks.append("".join(mask).rstrip())
    while lines and not lines[-1].strip():
        lines.pop()
        masks.pop()
    out.mkdir(parents=True, exist_ok=True)
    (out / "logo.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "logo.mask").write_text("\n".join(masks) + "\n", encoding="utf-8")
    print(f"{len(lines)} rows x {max(len(x) for x in lines)} cols -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("out", nargs="?", default=".")
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--star-threshold", type=int, default=40)
    ap.add_argument("--red-threshold", type=int, default=175)
    a = ap.parse_args()
    bake(Path(a.image), Path(a.out), a.cols, a.star_threshold, a.red_threshold)
