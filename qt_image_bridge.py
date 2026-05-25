# -*- coding: utf-8 -*-
from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage


def qimage_to_pil(image: QImage) -> Image.Image:
    if image.isNull():
        raise ValueError("Cannot convert a null QImage")
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = rgba.width()
    height = rgba.height()
    stride = rgba.bytesPerLine()
    data = bytes(rgba.constBits())
    return Image.frombytes("RGBA", (width, height), data, "raw", "RGBA", stride)


def pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()
