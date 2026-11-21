#!/usr/bin/env python3
"""SOLMARA poster entrypoint (vB).

Reads the SOLMARA travel poster, centre-crops it to a square, resizes to
1024x1024, steps the palette down 256 -> 128 -> 64 colours until the file
fits under the 1 MiB gate, and writes entry.png to MAKEFUN_OUTPUT_DIR
(default /output). Runs offline with Pillow only; absolute paths only.
"""

import os
from io import BytesIO

from PIL import Image

POSTER_PATH = "/home/hatch/workspace/makefun/poster-place-01-r2/poster.png"
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "entry.png")
TARGET_SIZE = (1024, 1024)
MAX_BYTES = 1_048_576
PALETTE_STEPS = (256, 128, 64)
# Pillow >= 10 moved the filter constants under Image.Resampling.
try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - Pillow < 10
    RESAMPLE = Image.LANCZOS


def centre_crop_square(image: Image.Image) -> Image.Image:
    """Crop the largest centred square out of the image."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def encode_png(image: Image.Image, colours: int) -> bytes:
    """Encode as a palettised PNG with the given colour count."""
    palettised = image.quantize(colors=colours, method=Image.Quantize.MEDIANCUT)
    buffer = BytesIO()
    palettised.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def encode_jpeg(image: Image.Image, quality: int) -> bytes:
    """Encode as JPEG; last-resort fallback if no palette PNG fits."""
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def main() -> None:
    source = Image.open(POSTER_PATH).convert("RGB")
    square = centre_crop_square(source)
    resized = square.resize(TARGET_SIZE, RESAMPLE)

    encoded = None
    chosen = None
    for colours in PALETTE_STEPS:
        candidate = encode_png(resized, colours)
        if len(candidate) <= MAX_BYTES:
            encoded = candidate
            chosen = f"{colours}-colour PNG"
            break
    if encoded is None:
        for quality in (92, 85, 75):
            candidate = encode_jpeg(resized, quality)
            if len(candidate) <= MAX_BYTES:
                encoded = candidate
                chosen = f"JPEG q{quality}"
                break
    if encoded is None:
        encoded = encode_jpeg(resized, 60)
        chosen = "JPEG q60"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "wb") as handle:
        handle.write(encoded)
    print(f"wrote {OUTPUT_PATH}: {len(encoded)} bytes ({chosen})")


if __name__ == "__main__":
    main()
