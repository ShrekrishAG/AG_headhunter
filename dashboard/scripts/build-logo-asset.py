#!/usr/bin/env python3
"""Build sidebar + favicon PNGs from the Accord Group website logo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

DASHBOARD = Path(__file__).resolve().parents[1]
ASSETS = DASHBOARD / "assets"
SOURCE_URL = "https://weareaccord.com/wp-content/uploads/2023/03/Accord-Group-Logo.png"
SOURCE_CACHE = ASSETS / ".accord-logo-source.png"
SIDEBAR_OUT = ASSETS / "accord-logo-dark.png"
FAVICON_OUT = ASSETS / "accord-favicon.png"
SIDEBAR_WIDTH = 880
LOGO_RGB = (26, 26, 26)
LOGO_MARGIN_RATIO = 0.08
FAVICON_MARGIN_RATIO = 0.18


def add_margin(img: Image.Image, ratio: float = LOGO_MARGIN_RATIO) -> Image.Image:
    w, h = img.size
    pad_w = max(1, round(w * ratio))
    pad_h = max(1, round(h * ratio))
    out = Image.new("RGBA", (w + 2 * pad_w, h + 2 * pad_h), (0, 0, 0, 0))
    out.paste(img, (pad_w, pad_h))
    return out


def fetch_source() -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sfL", SOURCE_URL, "-o", str(SOURCE_CACHE)],
        check=True,
    )
    return SOURCE_CACHE


def to_dark_logo(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    pixels = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < 20:
                pixels[x, y] = (0, 0, 0, 0)
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum > 240:
                pixels[x, y] = (0, 0, 0, 0)
            else:
                pixels[x, y] = (*LOGO_RGB, a)
    if bbox := rgba.getbbox():
        rgba = rgba.crop(bbox)
    return add_margin(rgba)


def build() -> None:
    src = fetch_source()
    logo = to_dark_logo(Image.open(src))
    w, h = logo.size
    sidebar_h = round(h * SIDEBAR_WIDTH / w)
    sidebar = logo.resize((SIDEBAR_WIDTH, sidebar_h), Image.Resampling.LANCZOS)
    sidebar.save(SIDEBAR_OUT, format="PNG", compress_level=6)

    favicon_src = add_margin(logo, ratio=FAVICON_MARGIN_RATIO)
    fw, fh = favicon_src.size
    side = max(fw, fh)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(favicon_src, ((side - fw) // 2, (side - fh) // 2))
    favicon = square.resize((128, 128), Image.Resampling.LANCZOS)
    favicon.save(FAVICON_OUT, format="PNG", compress_level=6)
    print(f"Wrote {SIDEBAR_OUT} ({sidebar.size})")
    print(f"Wrote {FAVICON_OUT} ({favicon.size})")


if __name__ == "__main__":
    try:
        build()
    except subprocess.CalledProcessError:
        print("Website logo blocked — building placeholder instead.", file=sys.stderr)
        subprocess.run([sys.executable, str(Path(__file__).with_name("build-placeholder-logo.py"))], check=True)
