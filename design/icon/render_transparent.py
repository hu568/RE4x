#!/usr/bin/env python3
"""Render each concept's icon.svg to transparent PNGs at all icon sizes.

The svg-maker skill's playwright backend bakes a white page background into
the output; app icons need real alpha. This renders every size directly from
the vector (crisper small sizes than downscaling a master).

Usage: python render_transparent.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
SIZES = [1024, 256, 128, 64, 48, 32, 16]
CONCEPTS = ["concept-a-magnifier", "concept-b-pixels", "concept-c-4x"]

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:transparent}}svg{{width:{s}px;height:{s}px;display:block}}</style>
</head><body>{svg}</body></html>"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for key in CONCEPTS:
            svg = (ROOT / key / "icon.svg").read_text(encoding="utf-8")
            outdir = ROOT / key / "png"
            outdir.mkdir(exist_ok=True)
            for s in SIZES:
                page = browser.new_page(viewport={"width": s, "height": s}, device_scale_factor=1)
                page.set_content(HTML.format(s=s, svg=svg))
                page.screenshot(path=str(outdir / f"{key}_{s}.png"), omit_background=True)
                page.close()
            print(f"[OK] {key}: {', '.join(map(str, SIZES))} px (transparent)")
        browser.close()


if __name__ == "__main__":
    main()
