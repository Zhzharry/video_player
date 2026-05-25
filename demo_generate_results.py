# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PIL import Image

from image_processing import GrayParams, apply_gray_transform, comparison_image


INPUT_DIR = Path("demo_assets/input")
OUTPUT_DIR = Path("demo_assets/output")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


DEMO_CASES = (
    ("gray_comparison.png", "grayscale", GrayParams()),
    ("invert_comparison.png", "invert", GrayParams()),
    ("brightness_comparison.png", "brightness", GrayParams(brightness=40)),
    ("contrast_comparison.png", "contrast", GrayParams(contrast_a=1.5, contrast_b=-20)),
    ("binary_comparison.png", "threshold", GrayParams(threshold=128)),
    ("gamma_comparison.png", "gamma", GrayParams(gamma=0.6)),
    ("equalized_comparison.png", "equalize", GrayParams()),
)


def _first_input_image() -> Path | None:
    if not INPUT_DIR.exists():
        return None
    for path in sorted(INPUT_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            return path
    return None


def main() -> int:
    source_path = _first_input_image()
    if source_path is None:
        print("No input image found. Put a jpg/png/webp/bmp file in demo_assets/input/.")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    original = Image.open(source_path)
    for filename, algorithm, params in DEMO_CASES:
        processed = apply_gray_transform(original, algorithm, params)
        comparison = comparison_image(original, processed)
        comparison.save(OUTPUT_DIR / filename)
        print(f"wrote {OUTPUT_DIR / filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
