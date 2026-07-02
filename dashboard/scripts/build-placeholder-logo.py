#!/usr/bin/env python3
"""Create placeholder Accord logo assets when the website blocks hotlinking."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DASHBOARD = Path(__file__).resolve().parents[1]
ASSETS = DASHBOARD / "assets"
SIDEBAR_OUT = ASSETS / "accord-logo-dark.png"
FAVICON_OUT = ASSETS / "accord-favicon.png"
GREEN = (45, 90, 39)
DARK = (26, 26, 26)


def build() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sidebar = Image.new("RGBA", (880, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sidebar)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 72)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
        small = font
    draw.rounded_rectangle((20, 30, 90, 150), radius=12, fill=GREEN)
    draw.text((120, 42), "ACCORD", fill=DARK, font=font)
    draw.text((122, 118), "GROUP", fill=GREEN, font=small)
    sidebar.save(SIDEBAR_OUT, format="PNG")

    favicon = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(favicon)
    fdraw.rounded_rectangle((16, 16, 112, 112), radius=20, fill=GREEN)
    fdraw.text((44, 46), "A", fill=(255, 255, 255, 255), font=font)
    favicon.save(FAVICON_OUT, format="PNG")
    print(f"Wrote {SIDEBAR_OUT}")
    print(f"Wrote {FAVICON_OUT}")


if __name__ == "__main__":
    build()
