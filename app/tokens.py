"""Tabletop role-playing tokens: a portrait inside a frame, computed with Pillow only.

The output is a square RGBA PNG whose outside is fully transparent, so the
token can be dropped on any virtual tabletop. Edges are antialiased by
drawing at four times the size, then reducing.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, cos, floor, pi, sin

from PIL import Image, ImageChops, ImageDraw

FRAMES = {
    "circle": "Cercle simple",
    "square": "Carré",
    "thick": "Bordure épaisse",
    "decorative": "Décoratif (rivets)",
}
SUPERSAMPLING = 4
# Largest side drawn before reduction: big tokens are supersampled less
# (a 4096 px token drawn four times larger would need gigabytes of memory).
MAX_DRAWN_SIZE = 4096
MIN_SIZE, MAX_SIZE = 32, 4096


def _rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError("Couleur de bordure invalide")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _darker(rgb: tuple[int, int, int], factor: float = 0.55) -> tuple[int, int, int]:
    red, green, blue = (int(channel * factor) for channel in rgb)
    return red, green, blue


@dataclass
class TokenSettings:
    size: int = 512
    frame: str = "circle"
    zoom: float = 1.0          # 1 = the portrait just covers the frame
    offset_x: float = 0.0      # portrait shift, in output pixels
    offset_y: float = 0.0
    border_color: str = "#D6A06A"
    border_width: int = 16     # in output pixels
    pixel_art: bool = False    # nearest-neighbour scaling for pixel art portraits

    def validate(self) -> None:
        if not MIN_SIZE <= self.size <= MAX_SIZE:
            raise ValueError(f"Taille de token entre {MIN_SIZE} et {MAX_SIZE} px")
        if self.frame not in FRAMES:
            raise ValueError(f"Cadre inconnu : {self.frame}")
        if not 0.05 <= self.zoom <= 20:
            raise ValueError("Zoom hors limites")
        if not 0 <= self.border_width <= self.size // 4:
            raise ValueError("Bordure trop épaisse pour cette taille")
        _rgb(self.border_color)


def _shape_mask(size: int, inset: float, square: bool) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    box = (inset, inset, size - 1 - inset, size - 1 - inset)
    draw = ImageDraw.Draw(mask)
    if square:
        draw.rounded_rectangle(box, radius=size * 0.06, fill=255)
    else:
        draw.ellipse(box, fill=255)
    return mask


def supersampling(size: int) -> int:
    return max(1, min(SUPERSAMPLING, MAX_DRAWN_SIZE // size))


def _portrait(image: Image.Image, settings: TokenSettings, big: int) -> Image.Image:
    """Portrait scaled to cover the token, zoomed and shifted, on a transparent square."""
    source = image if image.mode == "RGBA" else image.convert("RGBA")
    scale = max(big / source.width, big / source.height) * settings.zoom
    width, height = max(1, round(source.width * scale)), max(1, round(source.height * scale))
    resample = Image.Resampling.NEAREST if settings.pixel_art else Image.Resampling.LANCZOS
    factor = big / settings.size
    left = round((big - width) / 2 + settings.offset_x * factor)
    top = round((big - height) / 2 + settings.offset_y * factor)
    # Only the part of the scaled portrait that lands on the canvas is computed: memory
    # stays proportional to big² whatever the source size, aspect ratio or zoom.
    region = (max(0, -left), max(0, -top), min(width, big - left), min(height, big - top))
    if region[2] <= region[0] or region[3] <= region[1]:
        return Image.new("RGBA", (big, big), (0, 0, 0, 0))  # the portrait was moved out of the token
    visible = _resized_region(source, (width, height), region, resample)
    if visible.size == (big, big):
        return visible  # the portrait covers the whole square
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas.paste(visible, (left + region[0], top + region[1]))  # plain copy: alpha stays exact
    return canvas


def _resized_region(source: Image.Image, size: tuple[int, int], region: tuple[int, int, int, int],
                    resample: Image.Resampling) -> Image.Image:
    """``source.resize(size, resample).crop(region)`` without computing the rest of the resized image."""
    (width, height), (x0, y0, x1, y1) = size, region
    scale_x, scale_y = source.width / width, source.height / height  # source pixels per resized pixel
    if resample == Image.Resampling.NEAREST:
        # One affine pass with double precision coefficients (a resize box is single precision).
        # Only pixel centres falling exactly between two source pixels may pick the other one.
        return source.transform((x1 - x0, y1 - y0), Image.Transform.AFFINE,
                                (scale_x, 0, x0 * scale_x, 0, scale_y, y0 * scale_y), resample)
    # Source coordinates of the region; multiplying first keeps the far edges exact.
    left, right = x0 * source.width / width, x1 * source.width / width
    top, bottom = y0 * source.height / height, y1 * source.height / height
    # Only the source rows read by the vertical filter are used (Lanczos support: 3 source
    # pixels, wider when reducing), with a margin so no filter window is clipped by the crop.
    support = 3 * max(1.0, scale_y) + 2
    first, last = max(0, floor(top - support)), min(source.height, ceil(bottom + support))
    # Same premultiplied space as Image.resize, kept across both passes. The passes are
    # separate on purpose: Pillow 13 gives different pixels when a single call combines
    # a horizontal pass with a vertical box offset.
    rows = source.crop((0, first, source.width, last)).convert("RGBa")
    rows = rows.resize((x1 - x0, last - first), resample, box=(left, 0, right, last - first))
    rows = rows.resize((x1 - x0, y1 - y0), resample, box=(0, top - first, x1 - x0, bottom - first))
    return rows.convert("RGBA")


def render_token(image: Image.Image, settings: TokenSettings) -> Image.Image:
    """Square RGBA token: the portrait clipped to the frame, the frame on top."""
    settings.validate()
    big = settings.size * supersampling(settings.size)
    border = settings.border_width * supersampling(settings.size)
    square = settings.frame == "square"
    width = border * 2 if settings.frame == "thick" else border
    color = _rgb(settings.border_color)
    portrait = _portrait(image, settings, big)
    inner = _shape_mask(big, width * 0.5, square)
    # Colours stay straight (not premultiplied): only the alpha is cut by the frame. The
    # portrait is a new image, changed in place to spare a big² copy.
    token = portrait
    token.putalpha(ImageChops.multiply(portrait.getchannel("A"), inner))
    if width > 0:
        ring = Image.new("RGBA", (big, big), (*color, 255))
        ring.putalpha(ImageChops.subtract(_shape_mask(big, 0, square), _shape_mask(big, width, square)))
        token = Image.alpha_composite(token, ring)
        draw = ImageDraw.Draw(token)
        line = max(1, width // 6)
        if settings.frame == "thick":
            # A darker inner rim gives depth to the thick border.
            inset = width - line
            box = (inset, inset, big - 1 - inset, big - 1 - inset)
            if square:
                draw.rounded_rectangle(box, radius=big * 0.05, outline=(*_darker(color), 255), width=line)
            else:
                draw.ellipse(box, outline=(*_darker(color), 255), width=line)
        if settings.frame == "decorative":
            _decorate(draw, big, width, color, square)
    if token.size == (settings.size, settings.size):
        return token  # not supersampled (large tokens): resizing would only copy it
    return token.resize((settings.size, settings.size), Image.Resampling.LANCZOS)


def _decorate(draw: ImageDraw.ImageDraw, big: int, width: int, color, square: bool) -> None:
    """Rivets on the ring and a thin inner line, in the copper and steampunk spirit of ReefKit."""
    dark = (*_darker(color), 255)
    light = (*tuple(min(255, int(channel * 1.25)) for channel in color), 255)
    radius = max(2, width // 3)
    centre = (big - 1) / 2
    distance = centre - width / 2
    count = 8
    for index in range(count):
        angle = 2 * pi * index / count - pi / 2
        if square:
            # Rivets on the corners and the middle of each side.
            x = centre + distance * max(-1.0, min(1.0, cos(angle) * 1.42))
            y = centre + distance * max(-1.0, min(1.0, sin(angle) * 1.42))
        else:
            x, y = centre + distance * cos(angle), centre + distance * sin(angle)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=light, outline=dark,
                     width=max(1, radius // 3))
    inset = width + max(2, width // 5)
    box = (inset, inset, big - 1 - inset, big - 1 - inset)
    line = max(1, width // 8)
    if square:
        draw.rounded_rectangle(box, radius=big * 0.05, outline=dark, width=line)
    else:
        draw.ellipse(box, outline=dark, width=line)
