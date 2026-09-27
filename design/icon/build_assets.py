#!/usr/bin/env python3
"""RE4x icon asset builder.

Consumes the transparent per-size PNGs produced by render_transparent.py and
produces:
  - <concept>.ico   (multi-frame: 256/128/64/48/32/16, PNG-compressed frames)
  - preview.png     (3-concept contact sheet, light + dark backgrounds)

Usage: python build_assets.py
"""
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
SIZES = [256, 128, 64, 48, 32, 16]
CONCEPTS = [
    ("concept-a-magnifier", "A · 放大镜 + 山景"),
    ("concept-b-pixels", "B · 像素重生"),
    ("concept-c-4x", "C · 4× 徽标"),
]
LIGHT_BG = (245, 245, 245, 255)
DARK_BG = (31, 31, 31, 255)
TEXT_LIGHT_ROW = (60, 60, 60)
TEXT_DARK_ROW = (200, 200, 200)


def font(size):
    for name in ("msyh.ttc", "msyhbd.ttc", "arial.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_ico(png_dir, key, out_path):
    """Assemble an ICO from per-size transparent PNGs (PNG frames, Vista+)."""
    blobs = []
    for s in sorted(SIZES, reverse=True):
        data = (png_dir / f"{key}_{s}.png").read_bytes()
        blobs.append((s, data))
    offset = 6 + 16 * len(blobs)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(blobs)))
        for s, data in blobs:
            b = 0 if s >= 256 else s
            f.write(struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset))
            offset += len(data)
        for _, data in blobs:
            f.write(data)


def main():
    fonts = {n: font(n) for n in (22, 18)}

    all_sizes = {}
    for key, _ in CONCEPTS:
        png_dir = ROOT / key / "png"
        sizes = {s: Image.open(png_dir / f"{key}_{s}.png").convert("RGBA") for s in SIZES}
        for s, img in sizes.items():
            assert img.size == (s, s), f"{key}_{s}: got {img.size}"
            assert img.mode == "RGBA"
        all_sizes[key] = sizes
        build_ico(png_dir, key, ROOT / key / f"{key}.ico")
        print(f"[OK] {key}: ico (6 frames) + {len(sizes)} png verified transparent")

    # contact sheet
    cell, gutter, margin = 300, 24, 24
    big_h, ladder_h, title_h = 304, 110, 56
    width = margin * 2 + cell * 3 + gutter * 2
    height = margin + title_h + big_h * 2 + ladder_h * 2 + margin
    sheet = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    y = margin
    draw.text((margin, y + 8), "RE4x — 软件图标概念方案（浅色 / 深色背景）", fill=(30, 30, 30), font=fonts[22])
    y += title_h

    def paste_row(y0, h, bg, label_color, size, ladder):
        draw.rectangle([0, y0, width, y0 + h], fill=bg)
        for i, (key, label) in enumerate(CONCEPTS):
            x0 = margin + i * (cell + gutter)
            draw.text((x0 + 4, y0 + 10), label, fill=label_color, font=fonts[18])
            if ladder:
                ladder_sizes = SIZES[2:]
                total = sum(ladder_sizes) + 12 * (len(ladder_sizes) - 1)
                cx = x0 + (cell - total) // 2
                cy = y0 + (h + 20) // 2
                for s in ladder_sizes:
                    img = all_sizes[key][s]
                    sheet.alpha_composite(img, (cx, cy - s // 2))
                    cx += s + 12
            else:
                img = all_sizes[key][size]
                sheet.alpha_composite(img, (x0 + (cell - size) // 2, y0 + (h - size) // 2 + 10))

    paste_row(y, big_h, LIGHT_BG, TEXT_LIGHT_ROW, 256, ladder=False)
    y += big_h
    paste_row(y, big_h, DARK_BG, TEXT_DARK_ROW, 256, ladder=False)
    y += big_h
    paste_row(y, ladder_h, LIGHT_BG, TEXT_LIGHT_ROW, 0, ladder=True)
    y += ladder_h
    paste_row(y, ladder_h, DARK_BG, TEXT_DARK_ROW, 0, ladder=True)

    sheet.convert("RGB").save(ROOT / "preview.png")
    print(f"[OK] preview sheet -> {ROOT / 'preview.png'} ({width}x{height})")


if __name__ == "__main__":
    main()
