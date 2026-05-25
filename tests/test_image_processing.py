# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from PIL import Image

from image_processing import GrayParams, apply_gray_transform, histogram_256


class ImageProcessingTests(unittest.TestCase):
    def test_grayscale_uses_weighted_formula(self) -> None:
        image = Image.new("RGB", (1, 1), (10, 20, 30))
        out = apply_gray_transform(image, "grayscale", GrayParams())
        self.assertEqual(out.convert("L").getpixel((0, 0)), 18)

    def test_invert(self) -> None:
        image = Image.new("RGB", (1, 1), (10, 20, 30))
        out = apply_gray_transform(image, "invert", GrayParams())
        self.assertEqual(out.convert("L").getpixel((0, 0)), 237)

    def test_brightness_clamps(self) -> None:
        image = Image.new("RGB", (2, 1), (250, 250, 250))
        out = apply_gray_transform(image, "brightness", GrayParams(brightness=20))
        self.assertEqual(out.convert("L").getpixel((0, 0)), 255)

    def test_contrast_clamps(self) -> None:
        image = Image.new("RGB", (1, 1), (200, 200, 200))
        out = apply_gray_transform(image, "contrast", GrayParams(contrast_a=2.0, contrast_b=-20))
        self.assertEqual(out.convert("L").getpixel((0, 0)), 255)

    def test_threshold_boundary_is_white(self) -> None:
        image = Image.new("RGB", (1, 1), (128, 128, 128))
        out = apply_gray_transform(image, "threshold", GrayParams(threshold=128))
        self.assertEqual(out.convert("L").getpixel((0, 0)), 255)

    def test_gamma_lighten_and_darken(self) -> None:
        image = Image.new("RGB", (1, 1), (64, 64, 64))
        light = apply_gray_transform(image, "gamma", GrayParams(gamma=0.5))
        dark = apply_gray_transform(image, "gamma", GrayParams(gamma=2.0))
        self.assertGreater(light.convert("L").getpixel((0, 0)), 64)
        self.assertLess(dark.convert("L").getpixel((0, 0)), 64)

    def test_histogram_shape_and_total(self) -> None:
        image = Image.new("RGB", (3, 2), (10, 10, 10))
        hist = histogram_256(image)
        self.assertEqual(len(hist), 256)
        self.assertEqual(sum(hist), 6)

    def test_equalize_single_color_does_not_crash(self) -> None:
        image = Image.new("RGB", (3, 3), (80, 80, 80))
        out = apply_gray_transform(image, "equalize", GrayParams())
        self.assertEqual(out.size, image.size)
        self.assertEqual(out.convert("L").getpixel((0, 0)), 80)


if __name__ == "__main__":
    unittest.main()
