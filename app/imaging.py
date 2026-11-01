"""Pixel helpers shared by several tools, computed with Pillow only (no Qt).

Transparent margins are found from the alpha channel; crops never resample, so
pixel art keeps its exact pixels.
"""
from __future__ import annotations

from PIL import Image


def alpha_bounds(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Box (left, top, right, bottom) of the pixels that are not fully transparent."""
    return image.convert("RGBA").getchannel("A").getbbox()


def trim_transparent(image: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]] | None:
    """Image cropped to its visible pixels with the crop box; None if fully transparent."""
    box = alpha_bounds(image)
    if box is None:
        return None
    return image.crop(box), box
