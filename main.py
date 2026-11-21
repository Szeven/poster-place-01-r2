#!/usr/bin/env python3
"""SOLMARA travel poster — poster-place-01 round 3.

Reads poster.png next to this script, centre-crops it to a square,
resizes to 1024x1024, and writes a compact entry.png into
MAKEFUN_OUTPUT_DIR (default /output) that fits under 1 MiB.

Paths are resolved from this file's own location, never from the
current working directory, so the script works from any CWD and on a
read-only mount (e.g. the grader's /bot).
"""

import os
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_BYTES = 1_048_576  # 1 MiB
TARGET = 1024


def source_path() -> Path:
    """Image file living next to this script."""
    return Path(__file__).resolve().parent / "poster.png"


def output_path() -> Path:
    """Destination directory from the environment, default /output."""
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    return out_dir / "entry.png"


def centre_crop_square(img: Image.Image) -> Image.Image:
    """Centre-crop the image to a square using its shorter side."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def lanczos():
    """LANCZOS resampling filter, compatible with old and new Pillow."""
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:  # Pillow < 9.1
        return Image.LANCZOS


def normalise(img: Image.Image) -> Image.Image:
    """Drop any alpha channel so palette/JPEG encoding is well-defined."""
    if img.mode in ("RGBA", "LA", "PA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    return img.convert("RGB")


def palette_candidates(img: Image.Image):
    """Yield (label, bytes) for palette PNGs, 256 -> 128 -> 64 colours."""
    for colours in (256, 128, 64):
        pal = img.convert("P", palette=Image.ADAPTIVE, colors=colours)
        buf = BytesIO()
        pal.save(buf, format="PNG", optimize=True)
        yield f"palette-{colours}", buf.getvalue()


def jpeg_candidates(img: Image.Image):
    """Yield (label, bytes) for JPEGs, quality 92 -> 85 -> 75 -> 60."""
    rgb = img.convert("RGB")
    for quality in (92, 85, 75, 60):
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        yield f"jpeg-q{quality}", buf.getvalue()


def main() -> int:
    src = source_path()
    if not src.is_file():
        print(f"error: source image not found: {src}", file=sys.stderr)
        return 1

    with Image.open(src) as img:
        img.load()
        square = centre_crop_square(img)
        square = square.resize((TARGET, TARGET), lanczos())
        square = normalise(square)

    # Try palette PNGs first, then JPEGs; take the first that fits under
    # the limit. If none fits, fall back to the smallest candidate tried.
    chosen_label = None
    chosen_data = None
    for label, data in list(palette_candidates(square)) + list(
        jpeg_candidates(square)
    ):
        if chosen_data is None or len(data) < len(chosen_data):
            smallest_label, smallest_data = label, data
        if len(data) < MAX_BYTES:
            chosen_label, chosen_data = label, data
            break
    else:
        chosen_label, chosen_data = smallest_label, smallest_data
        print(
            f"warning: no encoding fits under {MAX_BYTES} bytes; "
            f"using smallest ({chosen_label}, {len(chosen_data)} bytes)",
            file=sys.stderr,
        )

    out = output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(chosen_data)
    print(
        f"wrote {out} ({len(chosen_data)} bytes, {chosen_label}, "
        f"{TARGET}x{TARGET})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
