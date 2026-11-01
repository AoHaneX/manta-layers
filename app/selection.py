"""Selection masks computed with Pillow only.

A selection is an 8-bit "L" image the size of the document: 0 means not
selected, 255 fully selected, intermediate values come from antialiasing or
feathering. Nothing here depends on Qt, which keeps the maths testable and
separate from how the canvas draws the selection.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter

COMBINE_MODES = ("replace", "add", "subtract", "intersect")
COMBINE_LABELS = {
    "replace": "Nouvelle sélection",
    "add": "Ajouter",
    "subtract": "Soustraire",
    "intersect": "Intersection",
}
SUPERSAMPLING = 4  # antialiased shapes are drawn larger, then reduced


def empty(size: tuple[int, int]) -> Image.Image:
    return Image.new("L", size, 0)


def full(size: tuple[int, int]) -> Image.Image:
    return Image.new("L", size, 255)


def _pixel_box(box) -> tuple[int, int, int, int] | None:
    """Integer box covering the pixels whose centre lies inside ``box``."""
    x0, y0, x1, y1 = box
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    left, top, right, bottom = round(left), round(top), round(right), round(bottom)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _shape(size, box, antialias: bool, draw_ellipse: bool) -> Image.Image:
    mask = empty(size)
    if antialias:
        x0, y0, x1, y1 = box
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 0.5 or bottom - top < 0.5:
            return mask
        # Draw only the shape's neighbourhood at a higher resolution.
        area = (max(0, int(left) - 1), max(0, int(top) - 1),
                min(size[0], int(right) + 2), min(size[1], int(bottom) + 2))
        if area[2] <= area[0] or area[3] <= area[1]:
            return mask
        scale = SUPERSAMPLING
        big = Image.new("L", ((area[2] - area[0]) * scale, (area[3] - area[1]) * scale), 0)
        shape = ((left - area[0]) * scale, (top - area[1]) * scale,
                 (right - area[0]) * scale - 1, (bottom - area[1]) * scale - 1)
        draw = ImageDraw.Draw(big)
        (draw.ellipse if draw_ellipse else draw.rectangle)(shape, fill=255)
        mask.paste(big.resize((area[2] - area[0], area[3] - area[1]), Image.Resampling.BOX), area[:2])
        return mask
    pixels = _pixel_box(box)
    if pixels is None:
        return mask
    left, top, right, bottom = pixels
    draw = ImageDraw.Draw(mask)
    # Pillow draws nothing for an ellipse narrower than three pixels: such a
    # tiny ellipse is its whole box.
    if draw_ellipse and min(right - left, bottom - top) >= 3:
        draw.ellipse((left, top, right - 1, bottom - 1), fill=255)
    else:
        draw.rectangle((left, top, right - 1, bottom - 1), fill=255)
    return mask


def rectangle(size: tuple[int, int], box, antialias: bool = False) -> Image.Image:
    """Rectangle from two corners in document coordinates."""
    return _shape(size, box, antialias, draw_ellipse=False)


def ellipse(size: tuple[int, int], box, antialias: bool = False) -> Image.Image:
    """Ellipse inscribed in a box; pixel-perfect unless ``antialias`` is set."""
    return _shape(size, box, antialias, draw_ellipse=True)


def polygon(size: tuple[int, int], points, antialias: bool = False) -> Image.Image:
    """Closed polygon (free or polygonal lasso) through document-space points.

    Coverage is computed with supersampling; the pixel-perfect variant keeps
    the pixels covered by at least half, so a lasso drawn along pixel edges
    selects exactly the pixels inside. Fewer than three distinct points select nothing.
    """
    mask = empty(size)
    vertices = [(float(x), float(y)) for x, y in points]
    if len(set(vertices)) < 3:
        return mask
    xs, ys = [x for x, _ in vertices], [y for _, y in vertices]
    area = (max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1),
            min(size[0], int(max(xs)) + 2), min(size[1], int(max(ys)) + 2))
    if area[2] <= area[0] or area[3] <= area[1]:
        return mask
    scale = SUPERSAMPLING
    big = Image.new("L", ((area[2] - area[0]) * scale, (area[3] - area[1]) * scale), 0)
    ImageDraw.Draw(big).polygon([((x - area[0]) * scale - 0.5, (y - area[1]) * scale - 0.5)
                                 for x, y in vertices], fill=255)
    mask.paste(big.resize((area[2] - area[0], area[3] - area[1]), Image.Resampling.BOX), area[:2])
    return mask if antialias else mask.point([0] * 128 + [255] * 128)


def _within(channel: Image.Image, reference: int, tolerance: int) -> Image.Image:
    difference = ImageChops.difference(channel, Image.new("L", channel.size, reference))
    return difference.point([255 if value <= tolerance else 0 for value in range(256)])


def similar_colour(image: Image.Image, reference, tolerance: int) -> Image.Image:
    """Pixels whose RGBA channels are all within ``tolerance`` of ``reference``.

    A transparent reference matches transparent pixels; an opaque one never
    matches fully transparent pixels, whose colour is meaningless.
    """
    rgba = image.convert("RGBA")
    tolerance = max(0, min(255, int(tolerance)))
    red, green, blue, alpha = rgba.split()
    if reference[3] == 0:
        return _within(alpha, 0, tolerance)
    candidates = _within(alpha, reference[3], tolerance)
    for channel, value in zip((red, green, blue), reference[:3]):
        candidates = ImageChops.multiply(candidates, _within(channel, value, tolerance))
    return ImageChops.multiply(candidates, alpha.point([0] + [255] * 255))


# Byte translation tables for the flood fill: fillable pixels become 1.
_FILLABLE = bytes([0] + [1] * 255)
_ZERO, _ONE = b"\x00", b"\x01"


def flood_region(mask: Image.Image, seed: tuple[int, int]) -> Image.Image:
    """4-connected region of non-zero pixels of ``mask`` reachable from ``seed``.

    Returns an "L" mask, 255 in the region and 0 elsewhere; a seed outside the
    image or on a zero pixel gives an empty mask. Same result as Pillow's
    ``ImageDraw.floodfill`` (also 4-connected) on a binary mask, but filled
    span by span with ``bytes.find``, so the Python loop runs once per
    horizontal run instead of once per pixel.
    """
    if mask.mode != "L":
        mask = mask.convert("L")
    width, height = mask.size
    x, y = seed
    result = bytearray(width * height)
    if not (0 <= x < width and 0 <= y < height):
        return Image.frombytes("L", (width, height), bytes(result))
    # 1 = fillable and not filled yet; filled runs are reset to 0.
    pending = bytearray(mask.tobytes().translate(_FILLABLE))
    zeros, filled = memoryview(bytes(width)), memoryview(b"\xff" * width)
    stack = [(y, y * width + x)]
    while stack:
        row, position = stack.pop()
        if not pending[position]:
            continue  # its run was filled from another seed
        start = row * width
        end = start + width
        left = pending.rfind(_ZERO, start, position) + 1 or start
        right = pending.find(_ZERO, position, end)
        if right < 0:
            right = end
        length = right - left
        pending[left:right] = zeros[:length]
        result[left:right] = filled[:length]
        # One seed per fillable run touching [left, right) on the rows above and below.
        for neighbour in (row - 1, row + 1):
            if not 0 <= neighbour < height:
                continue
            shift = (neighbour - row) * width
            stop, row_end = right + shift, (neighbour + 1) * width
            found = pending.find(_ONE, left + shift, stop)
            while found >= 0:
                stack.append((neighbour, found))
                run_end = pending.find(_ZERO, found, row_end)
                if run_end < 0 or run_end >= stop:
                    break
                found = pending.find(_ONE, run_end, stop)
    return Image.frombytes("L", (width, height), bytes(result))


def magic_wand(image: Image.Image, seed: tuple[int, int], tolerance: int,
               contiguous: bool = True) -> Image.Image:
    """Select pixels similar to the seed pixel.

    Each RGBA channel must stay within ``tolerance``. Fully transparent pixels
    have no meaningful colour: a transparent seed selects the transparent area
    (alpha within the tolerance), and an opaque seed never selects them.
    """
    rgba = image.convert("RGBA")
    x, y = seed
    if not (0 <= x < rgba.width and 0 <= y < rgba.height):
        return empty(rgba.size)
    candidates = similar_colour(rgba, rgba.getpixel((x, y)), tolerance)
    if not contiguous:
        return candidates
    return flood_region(candidates, (x, y))


def combine(base: Image.Image | None, new: Image.Image, mode: str) -> Image.Image:
    """Combine a new shape with the current selection."""
    if base is None or mode == "replace":
        return new.copy()
    if mode == "add":
        return ImageChops.lighter(base, new)
    if mode == "subtract":
        return ImageChops.subtract(base, new)
    if mode == "intersect":
        return ImageChops.darker(base, new)
    raise ValueError(f"Mode de sélection inconnu : {mode}")


def feather(mask: Image.Image, radius: float) -> Image.Image:
    """Soften the edges; meant for photos, not for pixel art."""
    return mask.filter(ImageFilter.GaussianBlur(radius)) if radius > 0 else mask


def invert(mask: Image.Image) -> Image.Image:
    return ImageChops.invert(mask)


def bounds(mask: Image.Image | None) -> tuple[int, int, int, int] | None:
    return None if mask is None else mask.getbbox()


def is_empty(mask: Image.Image | None) -> bool:
    return bounds(mask) is None


def translate(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    moved = empty(mask.size)
    moved.paste(mask, (int(dx), int(dy)))
    return moved


def resize_canvas(mask: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Keep the selection anchored top-left when the document is resized."""
    if mask.size == tuple(size):
        return mask
    result = empty(size)
    result.paste(mask, (0, 0))
    return result


def apply_alpha(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Multiply the alpha channel of an RGBA image by a mask of the same size."""
    result = image.convert("RGBA")
    result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
    return result


def hide(layer_mask: Image.Image | None, area: Image.Image) -> Image.Image:
    """Layer mask with ``area`` made transparent (non-destructive deletion)."""
    base = layer_mask if layer_mask is not None else full(area.size)
    return ImageChops.subtract(base, area)


def reveal(layer_mask: Image.Image | None, area: Image.Image) -> Image.Image:
    """Layer mask with ``area`` made visible again."""
    base = layer_mask if layer_mask is not None else full(area.size)
    return ImageChops.lighter(base, area)


def encode(mask: Image.Image) -> bytes:
    output = BytesIO()
    mask.save(output, format="PNG", optimize=False)
    return output.getvalue()


def decode(data: bytes) -> Image.Image:
    # Masks are always stored as PNG; no other decoder is needed.
    with Image.open(BytesIO(data), formats=("PNG",)) as source:
        return source.convert("L")
