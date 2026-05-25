# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class GrayParams:
    brightness: int = 0
    contrast_a: float = 1.0
    contrast_b: int = 0
    threshold: int = 128
    gamma: float = 1.0


ALGORITHMS = (
    "original",
    "grayscale",
    "invert",
    "brightness",
    "contrast",
    "threshold",
    "gamma",
    "equalize",
)

ALGORITHM_LABELS = {
    "original": "原图",
    "grayscale": "灰度化",
    "invert": "灰度反转",
    "brightness": "亮度调整",
    "contrast": "对比度调整",
    "threshold": "阈值二值化",
    "gamma": "Gamma 变换",
    "equalize": "直方图均衡化",
}

ALGORITHM_FORMULAS = {
    "original": "s = r",
    "grayscale": "Gray = 0.299R + 0.587G + 0.114B",
    "invert": "s = 255 - r",
    "brightness": "s = r + b",
    "contrast": "s = a * r + b",
    "threshold": "s = 255 if r >= T else 0",
    "gamma": "s = 255 * (r / 255)^gamma",
    "equalize": "s = round((CDF(r) - CDFmin) / (N - CDFmin) * 255)",
}


def _clamp(v: float, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, int(round(v))))


def _weighted_gray_value(r: int, g: int, b: int) -> int:
    return _clamp(0.299 * r + 0.587 * g + 0.114 * b)


def _split_alpha(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    if image.mode in ("RGBA", "LA"):
        rgba = image.convert("RGBA")
        return rgba, rgba.getchannel("A")
    if image.mode == "P" and "transparency" in image.info:
        rgba = image.convert("RGBA")
        return rgba, rgba.getchannel("A")
    return image.convert("RGB"), None


def _to_weighted_gray(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    rgb, alpha = _split_alpha(image)
    src = rgb.convert("RGB")
    gray = Image.new("L", src.size)
    src_px = src.load()
    gray_px = gray.load()
    width, height = src.size
    for y in range(height):
        for x in range(width):
            r, g, b = src_px[x, y]
            gray_px[x, y] = _weighted_gray_value(r, g, b)
    return gray, alpha


def _merge_alpha(gray: Image.Image, alpha: Image.Image | None) -> Image.Image:
    if alpha is None:
        return gray.convert("RGB")
    rgba = Image.merge("RGBA", (gray, gray, gray, alpha.resize(gray.size)))
    return rgba


def _map_gray(gray: Image.Image, fn) -> Image.Image:
    out = Image.new("L", gray.size)
    src = gray.load()
    dst = out.load()
    width, height = gray.size
    for y in range(height):
        for x in range(width):
            dst[x, y] = _clamp(fn(src[x, y]))
    return out


def _equalize_gray(gray: Image.Image) -> Image.Image:
    hist = gray.histogram()
    total = gray.width * gray.height
    if total <= 0:
        return gray.copy()

    cdf = []
    running = 0
    for count in hist:
        running += count
        cdf.append(running)

    cdf_min = next((value for value in cdf if value > 0), 0)
    denom = total - cdf_min
    if denom <= 0:
        return gray.copy()

    lut = [
        _clamp((cdf[i] - cdf_min) * 255 / denom) if cdf[i] > 0 else 0
        for i in range(256)
    ]
    return gray.point(lut)


def apply_gray_transform(image: Image.Image, algorithm: str, params: GrayParams) -> Image.Image:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown grayscale algorithm: {algorithm}")

    gray, alpha = _to_weighted_gray(image)
    if algorithm in ("original", "grayscale"):
        return _merge_alpha(gray, alpha)
    if algorithm == "invert":
        return _merge_alpha(_map_gray(gray, lambda r: 255 - r), alpha)
    if algorithm == "brightness":
        b = int(params.brightness)
        return _merge_alpha(_map_gray(gray, lambda r: r + b), alpha)
    if algorithm == "contrast":
        a = float(params.contrast_a)
        b = int(params.contrast_b)
        return _merge_alpha(_map_gray(gray, lambda r: a * r + b), alpha)
    if algorithm == "threshold":
        t = _clamp(params.threshold)
        return _merge_alpha(_map_gray(gray, lambda r: 255 if r >= t else 0), alpha)
    if algorithm == "gamma":
        gamma = max(0.01, float(params.gamma))
        return _merge_alpha(_map_gray(gray, lambda r: 255 * ((r / 255.0) ** gamma)), alpha)
    if algorithm == "equalize":
        return _merge_alpha(_equalize_gray(gray), alpha)

    raise ValueError(f"Unhandled grayscale algorithm: {algorithm}")


def histogram_256(image: Image.Image) -> list[int]:
    gray, _ = _to_weighted_gray(image)
    hist = gray.histogram()
    return [int(v) for v in hist[:256]]


def default_suffix(algorithm: str) -> str:
    return {
        "original": "_gray",
        "grayscale": "_gray",
        "invert": "_invert",
        "brightness": "_bright",
        "contrast": "_contrast",
        "threshold": "_binary",
        "gamma": "_gamma",
        "equalize": "_enhanced",
    }.get(algorithm, "_processed")


def comparison_image(original: Image.Image, processed: Image.Image) -> Image.Image:
    max_w = 760
    label_h = 34
    gap = 16
    margin = 18

    orig = original.convert("RGB")
    proc = processed.convert("RGB")
    scale = min(1.0, max_w / max(orig.width, proc.width))
    if scale < 1.0:
        orig = orig.resize((max(1, int(orig.width * scale)), max(1, int(orig.height * scale))))
        proc = proc.resize((max(1, int(proc.width * scale)), max(1, int(proc.height * scale))))

    tile_w = max(orig.width, proc.width)
    tile_h = max(orig.height, proc.height)
    canvas = Image.new("RGB", (tile_w * 2 + gap + margin * 2, tile_h + label_h + margin * 2), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    left_x = margin
    right_x = margin + tile_w + gap
    y = margin + label_h
    canvas.paste(orig, (left_x + (tile_w - orig.width) // 2, y + (tile_h - orig.height) // 2))
    canvas.paste(proc, (right_x + (tile_w - proc.width) // 2, y + (tile_h - proc.height) // 2))
    draw.text((left_x, margin), "Original", fill=(24, 24, 24), font=font)
    draw.text((right_x, margin), "Processed", fill=(24, 24, 24), font=font)
    draw.rectangle((left_x, y, left_x + tile_w, y + tile_h), outline=(210, 210, 210), width=1)
    draw.rectangle((right_x, y, right_x + tile_w, y + tile_h), outline=(210, 210, 210), width=1)
    return canvas
