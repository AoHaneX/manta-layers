"""Canvas interactif et rendu sans les accessoires d'édition."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from hashlib import sha1
from io import BytesIO
from math import ceil, floor
from typing import TYPE_CHECKING, cast

from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt, QTextBoundaryFinder
from PySide6.QtGui import (
    QBitmap,
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene

from . import selection
from .imaging import trim_transparent
from .model import ASSET_FORMATS, MAX_PIXELS, Document, Layer, new_id
from .shape_item import ShapeGraphicItem
from .textpath import custom_points, drag_handle, handle_points, normalize_controls, normalize_shape, sample_path
from .theme import COLORS

if TYPE_CHECKING:
    pass

MAX_ZOOM = 64.0
CHECKER_TILE = 18


_font_families: dict[str, str] | None = None


def _installed_families() -> dict[str, str]:
    """Installed font families by lower-case name; cached, the system list is long."""
    global _font_families
    if _font_families is None:
        _font_families = {family.casefold(): family for family in QFontDatabase.families()}
    return _font_families


def forget_font_families() -> None:
    """Call after adding fonts to the application."""
    global _font_families
    _font_families = None


def font_is_installed(name: str) -> bool:
    return name.casefold() in _installed_families()


def resolve_font_family(name: str) -> str:
    """The installed family matching ``name`` (any case), else the default family."""
    return _installed_families().get(name.casefold(), QFont().defaultFamily())


def grapheme_clusters(text: str) -> list[str]:
    """User-perceived characters of ``text``: a letter and its accents, a whole emoji.

    Laying text out code point by code point would split "e" + U+0301 or an
    emoji sequence into separately placed pieces.
    """
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    # Qt counts UTF-16 code units; Python strings count code points.
    units = text.encode("utf-16-le")
    clusters, start = [], 0
    while (end := finder.toNextBoundary()) != -1:
        if end > start:
            clusters.append(units[start * 2:end * 2].decode("utf-16-le"))
        start = end
    return clusters


class CurvedTextGraphicItem(QGraphicsItem):
    """Vector text laid out glyph by glyph along a path; it is never rasterised.

    The path geometry comes from ``app.textpath``; this class only turns it
    into Qt paths, glyph placements and interactive handles.
    """

    def __init__(self, layer: Layer):
        super().__init__()
        self.apply_layer(layer)

    def apply_layer(self, layer: Layer) -> None:
        """Reload every text property from the model and redraw."""
        self.lines = layer.text.split("\n")
        self.font = QFont(resolve_font_family(layer.font_family), layer.font_size)
        self.color = QColor(layer.color)
        self.background = QColor(layer.text_background) if layer.text_background else QColor()
        self.path_shape, self.curve_intensity = normalize_shape(layer.text_deformation, layer.curve_intensity)
        self.controls = normalize_controls(layer.path_controls)
        self.spacing = float(layer.character_spacing)
        self.alignment = layer.path_alignment
        self.orientation = layer.path_orientation
        self.flip_horizontal = bool(layer.flip_horizontal)
        self.flip_vertical = bool(layer.flip_vertical)
        self._rebuild_geometry()
        self.update()

    def set_text_preview(self, text: str) -> None:
        """Live preview while the text is typed on the canvas."""
        self.lines = text.split("\n")
        self._rebuild_geometry()
        self.update()

    def _rebuild_geometry(self):
        self.prepareGeometryChange()
        metrics = QFontMetricsF(self.font)
        line_clusters = [grapheme_clusters(line) for line in self.lines]
        line_advances = [[metrics.horizontalAdvance(char) for char in clusters] for clusters in line_clusters]
        positive_advances = [advance for advances in line_advances for advance in advances if advance > 0]
        minimum_advance = min(positive_advances, default=1.0)
        # Negative spacing may tighten letters but never moves the cursor
        # backwards nor swaps their order.
        effective_spacing = max(self.spacing, -minimum_advance * 0.8)
        widths = [sum(advances) + max(0, len(advances) - 1) * effective_spacing
                  for advances in line_advances]
        self.text_width = max(widths, default=0.0)
        self.arc_amplitude = max(1.0, self.font.pointSizeF() * 2.0)
        margin = max(4.0, self.font.pointSizeF())
        self.path_start_x = -margin
        # The path width only depends on the text, so dragging a handle never
        # shifts the layout.
        self.path_width = max(1.0, self.text_width + margin * 2)
        # The first baseline stays where straight text has always been drawn;
        # following lines reuse the same shape, shifted downwards.
        self.baseline = metrics.ascent() + 2
        line_height = metrics.lineSpacing()
        block_height = metrics.height() + line_height * (len(self.lines) - 1) + 4
        # Flip centre independent from the shape: flipped text does not jump
        # while its handles are dragged.
        self._flip_center = QPointF(self.path_start_x + self.path_width / 2, block_height / 2)
        samples = max(32, min(256, int(self.path_width / 4)))
        offsets = sample_path(self.path_shape, self.curve_intensity, self.controls,
                              self.path_width, self.arc_amplitude, samples)
        self.placements = []
        content = None
        for index, (clusters, advances, width) in enumerate(zip(line_clusters, line_advances, widths)):
            baseline = self.baseline + index * line_height
            path = QPainterPath(QPointF(self.path_start_x + offsets[0][0], baseline + offsets[0][1]))
            for x, dy in offsets[1:]:
                path.lineTo(self.path_start_x + x, baseline + dy)
            if index == 0:
                self.guide_path = path
            length = max(1.0, path.length())
            spare = max(0.0, length - width)
            offset = 0.0 if self.alignment == "left" else spare if self.alignment == "right" else spare / 2
            cursor = offset
            for char, advance in zip(clusters, advances):
                center = cursor + advance / 2
                percent = path.percentAtLength(max(0.0, min(length, center)))
                point = path.pointAtPercent(percent)
                angle = -path.angleAtPercent(percent) if self.orientation == "tangent" else 0.0
                self.placements.append((char, advance, point, angle))
                glyph = QRectF(-advance / 2, -metrics.ascent(), advance, metrics.height())
                placed = QTransform().translate(point.x(), point.y()).rotate(angle).mapRect(glyph)
                content = placed if content is None else content.united(placed)
                cursor += max(advance * 0.2, advance + effective_spacing)
        if content is None:
            content = QRectF(self.path_start_x, 0, self.path_width, metrics.height())
        # The frame hugs the glyphs actually drawn, so the background and the
        # selection handles stay close to the text.
        self._content_bounds = content.adjusted(-2, -2, 2, 2)
        self._bounds = self._visual_transform().mapRect(self._content_bounds)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.save()
        painter.setTransform(self._visual_transform(), True)
        if self.background.isValid() and self.background.alpha() > 0:
            painter.fillRect(self._content_bounds, self.background)
        painter.setFont(self.font)
        painter.setPen(self.color)
        for char, advance, point, angle in self.placements:
            if char.isspace():
                continue
            painter.save()
            painter.translate(point)
            painter.rotate(angle)
            painter.drawText(QPointF(-advance / 2, 0), char)
            painter.restore()
        painter.restore()

    def _visual_transform(self) -> QTransform:
        center = self._flip_center
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.scale(-1 if self.flip_horizontal else 1,
                        -1 if self.flip_vertical else 1)
        transform.translate(-center.x(), -center.y())
        return transform

    def _to_visual(self, x: float, dy: float) -> QPointF:
        return self._visual_transform().map(QPointF(self.path_start_x + x, self.baseline + dy))

    def visual_guide_path(self) -> QPainterPath:
        return self._visual_transform().map(self.guide_path)

    def shape_handles_local(self) -> list[QPointF]:
        """Handles controlling the shape: the apex, or the two Bézier control points."""
        return [self._to_visual(x, dy) for x, dy in handle_points(
            self.path_shape, self.curve_intensity, self.controls, self.path_width, self.arc_amplitude
        )]

    def control_polygon_local(self) -> list[QPointF]:
        """Bézier control polygon of the custom shape, empty for other shapes."""
        if self.path_shape != "custom":
            return []
        return [self._to_visual(x, dy) for x, dy in custom_points(self.path_width, self.controls)]

    def drag_shape_handle(self, index: int, local: QPointF) -> None:
        inverse, invertible = self._visual_transform().inverted()
        if invertible:
            local = inverse.map(local)
        self.path_shape, self.curve_intensity, self.controls = drag_handle(
            self.path_shape, index, local.x() - self.path_start_x, local.y() - self.baseline,
            self.path_width, self.arc_amplitude, self.curve_intensity, self.controls,
        )
        self._rebuild_geometry()
        self.update()

    def set_curve_intensity(self, value: float):
        """Preview from the slider; a straight text becomes an arc when bent."""
        value = max(-100.0, min(100.0, float(value)))
        if self.path_shape == "straight" and value:
            self.path_shape = "arc"
        self.curve_intensity = abs(value) if self.path_shape in ("u", "u_inverted") else value
        self._rebuild_geometry()
        self.update()


def _rgb(color: QColor) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


def _render_operations(replacements: dict[str, str], fills: list[dict], strokes: list[dict]) -> list[tuple]:
    """Non-destructive edits of an image layer, flattened in their replay order.

    Colour replacements come first, then eraser strokes and fills interleaved
    by ``after_strokes``. Each operation only depends on the image before it,
    which lets renders resume from a cached prefix.
    """
    operations: list[tuple] = []
    mapping = {_rgb(QColor(old)): _rgb(QColor(new))
               for old, new in replacements.items()
               if QColor(old).isValid() and QColor(new).isValid()}
    for source_rgb, target_rgb in mapping.items():
        operations.append(("fill", source_rgb, target_rgb, 0, "global", None, False))
    applied_strokes = 0
    for fill in fills:
        source = QColor(str(fill.get("source", "")))
        target_color = QColor(str(fill.get("target", "")))
        if not source.isValid() or not target_color.isValid():
            continue
        due = max(applied_strokes, min(len(strokes), int(fill.get("after_strokes", 0))))
        operations.extend(("stroke", stroke) for stroke in strokes[applied_strokes:due])
        applied_strokes = due
        operations.append((
            "fill", _rgb(source), _rgb(target_color),
            max(0, min(255, int(fill.get("tolerance", 0)))),
            "global" if fill.get("mode") == "global" else "contiguous",
            (int(fill.get("x", -1)), int(fill.get("y", -1))),
            bool(fill.get("preserve_shading", False)),
        ))
    operations.extend(("stroke", stroke) for stroke in strokes[applied_strokes:])
    return operations


def _apply_operation(image: Image.Image, operation: tuple) -> Image.Image:
    # Both helpers return a new image (or the input untouched): cached images are never modified.
    if operation[0] == "stroke":
        return apply_eraser_strokes(image, [operation[1]])
    return _apply_color_fill(image, *operation[1:])


def render_layer_image(
    contents: bytes,
    replacements: dict[str, str],
    fills: list[dict] | None = None,
    strokes: list[dict] | None = None,
    cache_key: str | None = None,
) -> Image.Image:
    """Rend un calque image sans modifier l'image source du projet.

    Remplissages et traits de gomme sont rejoués dans l'ordre où ils ont été
    faits : un remplissage contigu ne traverse donc pas une zone déjà gommée.

    With a ``cache_key`` identifying ``contents`` (the asset id), the render
    resumes from the longest already rendered prefix of the operations: a new
    stroke or fill only costs itself, and undoing one is immediate.
    """
    operations = _render_operations(replacements, fills or [], strokes or [])
    keys: list[str] = []
    if cache_key is not None:
        digest = sha1(repr(cache_key).encode("utf-8"))
        keys.append(digest.hexdigest())
        for operation in operations:
            digest.update(repr(operation).encode("utf-8"))
            keys.append(digest.hexdigest())
    image, start = None, 0
    for index in range(len(keys) - 1, -1, -1):
        image = RENDER_CACHE.get(keys[index])
        if image is not None:
            start = index
            break
    if image is None:
        with Image.open(BytesIO(contents), formats=ASSET_FORMATS) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError(f"image trop grande ({source.width} × {source.height} px)")
            image = source.convert("RGBA")
    for operation in operations[start:]:
        image = _apply_operation(image, operation)
    if not keys or not operations:
        # A layer without edits is cached once, as a pixmap, by layer_pixmap.
        return image
    RENDER_CACHE.put(keys[-1], image)
    return image.copy()  # callers may modify their copy, never the cached image


def _similar_color_mask(image: Image.Image, source_rgb: tuple[int, int, int], tolerance: int) -> Image.Image:
    """Masque RVB sans anticrénelage ; chaque canal doit rester dans la tolérance."""
    rgb = image.convert("RGB")
    reference = Image.new("RGB", image.size, source_rgb)
    difference = ImageChops.difference(rgb, reference)
    lookup = [255 if value <= tolerance else 0 for value in range(256)]
    red, green, blue = (channel.point(lookup) for channel in difference.split())
    mask = ImageChops.multiply(ImageChops.multiply(red, green), blue)
    opaque = image.getchannel("A").point([0] + [255] * 255)
    return ImageChops.multiply(mask, opaque)


def _contiguous_mask(mask: Image.Image, seed: tuple[int, int] | None) -> Image.Image:
    if seed is None:
        return Image.new("L", mask.size, 0)
    return selection.flood_region(mask, seed)


def _shaded_recolor(
    image: Image.Image, source_rgb: tuple[int, int, int], target_rgb: tuple[int, int, int]
) -> Image.Image:
    """Change la teinte en conservant les écarts de luminosité des pixels d'origine."""
    luminance = image.convert("RGB").convert("L")
    source_luminance = round(0.299 * source_rgb[0] + 0.587 * source_rgb[1] + 0.114 * source_rgb[2])
    channels = [
        ImageChops.add(luminance, Image.new("L", image.size, value), offset=-source_luminance)
        for value in target_rgb
    ]
    recolored = Image.merge("RGB", channels).convert("RGBA")
    recolored.putalpha(image.getchannel("A"))
    return recolored


def _apply_color_fill(
    image: Image.Image,
    source_rgb: tuple[int, int, int],
    target_rgb: tuple[int, int, int],
    tolerance: int,
    mode: str,
    seed: tuple[int, int] | None,
    preserve_shading: bool,
) -> Image.Image:
    mask = _similar_color_mask(image, source_rgb, tolerance)
    if mode == "contiguous":
        mask = _contiguous_mask(mask, seed)
    if mask.getbbox() is None:
        return image
    replacement = (
        _shaded_recolor(image, source_rgb, target_rgb)
        if preserve_shading
        else Image.new("RGBA", image.size, (*target_rgb, 255))
    )
    if not preserve_shading:
        replacement.putalpha(image.getchannel("A"))
    result = image.copy()
    result.paste(replacement, (0, 0), mask)
    return result


def _segment_span(x: float, y: float, dx: float, dy: float,
                  bounds: tuple[float, float, float, float]) -> tuple[float, float] | None:
    """Part [t0, t1] of the segment (x, y) + t·(dx, dy), 0 ≤ t ≤ 1, inside ``bounds`` (Liang–Barsky)."""
    left, top, right, bottom = bounds
    t0, t1 = 0.0, 1.0
    for direction, distance in ((-dx, x - left), (dx, right - x), (-dy, y - top), (dy, bottom - y)):
        if direction == 0:
            if distance < 0:
                return None
            continue
        t = distance / direction
        if direction < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return (t0, t1) if t0 <= t1 else None


def _interpolated_points(points: list[list[float]], spacing: float,
                         bounds: tuple[float, float, float, float] | None = None):
    """Dab positions along a stroke, every ``spacing`` pixels.

    With ``bounds``, only the positions inside it are produced, without walking
    the rest of the segments: a point far outside the image (a damaged or forged
    project) costs nothing. The positions kept are exactly the same.
    """
    if not points:
        return
    yield points[0][0], points[0][1]
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = (dx * dx + dy * dy) ** 0.5
        steps = max(1, int(distance / max(0.25, spacing)) + 1)
        first, last = 1, steps
        if bounds is not None:
            span = _segment_span(start[0], start[1], dx, dy, bounds)
            if span is None:
                continue
            first, last = max(1, floor(span[0] * steps)), min(steps, ceil(span[1] * steps))
        for index in range(first, last + 1):
            ratio = index / steps
            yield start[0] + dx * ratio, start[1] + dy * ratio


def eraser_dab_origin(position: float, size: int, pixel_centered: bool = True) -> int:
    """First pixel covered by a dab of ``size`` pixels placed at ``position``.

    Pixel n spans [n, n + 1[: flooring centres the dab on the pixel under the
    pointer. Strokes saved before ``pixel_centered`` existed were rounded, half
    a pixel off, and keep that placement so that older projects look the same.
    """
    offset = (size - 1) / 2
    return floor(position - offset) if pixel_centered else round(position - offset)


def eraser_source_position(position: float, extent: int, size: int, flipped: bool) -> float:
    """Source position of a dab placed at ``position`` on a layer shown mirrored.

    Flooring is not symmetric: mirroring the position itself can move the dab
    by one pixel. The covered pixels are mirrored instead, and the result is
    the middle of the first source pixel span, where flooring is exact.
    """
    if not flipped:
        return position
    first = eraser_dab_origin(position, size)  # first displayed pixel
    return extent - first - size / 2


@lru_cache(maxsize=32)
def _eraser_dab(size: int, shape: str, pixel_art: bool, hardness: int, opacity: int) -> Image.Image:
    """Crée une empreinte sans anticrénelage en pixel art, douce en mode classique.

    The soft dab is computed pixel by pixel (about 1 s at 2048 px), so dabs are
    cached; callers only read them and must never modify the returned image.
    """
    size = max(1, int(size))
    maximum = round(255 * opacity / 100)
    dab = Image.new("L", (size, size), 0)
    if pixel_art or hardness >= 100:
        draw = ImageDraw.Draw(dab)
        # Pillow draws nothing for an ellipse narrower than three pixels: such a
        # small round dab is its whole box (as small elliptic selections are).
        if (shape == "square" and pixel_art) or size < 3:
            draw.rectangle((0, 0, size - 1, size - 1), fill=maximum)
        else:
            draw.ellipse((0, 0, size - 1, size - 1), fill=maximum)
        return dab
    pixels = dab.load()
    assert pixels is not None  # a new image is always loaded
    radius = size / 2
    inner = radius * hardness / 100
    center = (size - 1) / 2
    falloff = max(0.001, radius - inner)
    for y in range(size):
        for x in range(size):
            distance = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
            if distance <= inner:
                strength = 1.0
            elif distance >= radius:
                strength = 0.0
            else:
                strength = 1.0 - (distance - inner) / falloff
            pixels[x, y] = round(maximum * strength)
    return dab


def stamp_eraser_stroke(coverage: Image.Image, stroke: dict,
                        points: list[list[float]] | None = None) -> tuple[int, int, int, int] | None:
    """Add the dabs of ``stroke`` (or of ``points`` drawn with its settings) to ``coverage``.

    The single implementation of a stroke's shape, shared by the final render
    and the live preview. Returns the box of the changed pixels, None if none.
    """
    points = stroke.get("points", []) if points is None else points
    if not points:
        return None
    size = max(1, int(stroke.get("size", 1)))
    pixel_art = bool(stroke.get("pixel_art", True))
    shape = "square" if stroke.get("shape") == "square" else "circle"
    dab = _eraser_dab(
        size, shape, pixel_art,
        max(0, min(100, int(stroke.get("hardness", 100)))),
        max(1, min(100, int(stroke.get("opacity", 100)))),
    )
    centered = bool(stroke.get("pixel_centered", False))
    spacing = 0.5 if pixel_art else max(0.5, size * 0.2)
    width, height = coverage.size
    box: list[int] | None = None
    # Dabs placed beyond this frame cannot reach the image.
    frame = (-size - 1.0, -size - 1.0, width + size + 1.0, height + size + 1.0)
    # Les empreintes d'un même trait se combinent par maximum : l'opacité
    # choisie reste celle du trait, au lieu de s'additionner à chaque pas.
    for x, y in _interpolated_points(points, spacing, frame):
        left, top = eraser_dab_origin(x, size, centered), eraser_dab_origin(y, size, centered)
        if left >= width or top >= height or left + size <= 0 or top + size <= 0:
            continue  # entirely outside the image
        coverage.paste(ImageChops.lighter(coverage.crop((
            left, top, left + size, top + size
        )), dab), (left, top))
        if box is None:
            box = [left, top, left + size, top + size]
        else:
            box = [min(box[0], left), min(box[1], top), max(box[2], left + size), max(box[3], top + size)]
    if box is None:
        return None
    clipped = (max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3]))
    return clipped if clipped[0] < clipped[2] and clipped[1] < clipped[3] else None


def is_pencil_stroke(stroke: dict) -> bool:
    """Pencil strokes share the eraser's list (and replay order) and carry a colour."""
    return stroke.get("tool") == "pencil"


def apply_stroke_coverage(region: Image.Image, coverage: Image.Image, stroke: dict) -> Image.Image:
    """``region`` (RGBA) after one stroke whose dabs cover it by ``coverage`` (L, same size).

    The eraser lowers the alpha and keeps the colours; the pencil lays its
    colour over the pixels (premultiplied, so a soft dab on transparent pixels
    takes the pencil colour). Uncovered pixels are returned unchanged.
    """
    if not is_pencil_stroke(stroke):
        result = region.copy()
        result.putalpha(ImageChops.multiply(region.getchannel("A"), ImageChops.invert(coverage)))
        return result
    color = QColor(str(stroke.get("color", "")))
    paint = Image.new("RGBa", region.size, (color.red(), color.green(), color.blue(), 255))
    painted = Image.composite(paint, region.convert("RGBa"), coverage).convert("RGBA")
    # Unpremultiplying rounds the colour of what is left semi-transparent: a pixel that was
    # fully transparent gets the exact pencil colour, with the alpha the dab gave it.
    exact = Image.new("RGBA", region.size, (color.red(), color.green(), color.blue(), 0))
    exact.putalpha(painted.getchannel("A"))
    was_clear = region.getchannel("A").point([255] + [0] * 255)
    painted = Image.composite(exact, painted, was_clear)
    # Elsewhere, pixels the stroke did not touch are kept exactly as they were.
    return Image.composite(painted, region, coverage.point([0] + [255] * 255))


def apply_eraser_strokes(image: Image.Image, strokes: list[dict]) -> Image.Image:
    """Replay eraser and pencil strokes, without smoothing pixel art."""
    if not strokes:
        return image
    result = image.copy()
    for stroke in strokes:
        coverage = Image.new("L", result.size, 0)
        if stroke_box := stamp_eraser_stroke(coverage, stroke):
            # Only the touched area changes.
            region = apply_stroke_coverage(result.crop(stroke_box), coverage.crop(stroke_box), stroke)
            result.paste(region, stroke_box[:2])
    return result


class _ImageCache:
    """Rendus de calques image déjà calculés, limités par un budget mémoire.

    Une modification de calque reconstruit toute la scène : sans ce cache,
    chaque action décodait et recolorait de nouveau toutes les images.
    Works for QPixmap and Pillow images alike (4 bytes per pixel).
    """

    def __init__(self, budget_bytes: int):
        self._entries: OrderedDict[str, tuple[object, int]] = OrderedDict()
        self._budget = budget_bytes
        self._used = 0

    def get(self, key: str):
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[0]

    def put(self, key: str, image) -> None:
        size = image.width() * image.height() * 4 if isinstance(image, QPixmap) else image.width * image.height * 4
        if key in self._entries:
            self._used -= self._entries.pop(key)[1]
        if size > self._budget:
            return
        self._entries[key] = (image, size)
        self._used += size
        while self._used > self._budget:
            _key, (_image, freed) = self._entries.popitem(last=False)
            self._used -= freed

    def clear(self) -> None:
        self._entries.clear()
        self._used = 0


# Displayed layers (masks and flips applied).
PIXMAP_CACHE = _ImageCache(512 * 1024 * 1024)
# Layer renders before their mask, keyed by asset and replayed operations:
# the starting points of incremental renders (see render_layer_image).
RENDER_CACHE = _ImageCache(256 * 1024 * 1024)


def clear_render_caches() -> None:
    """Forget every cached render, when another document replaces the current one.

    Not on undo or redo: the history reuses the renders of the same document.
    """
    PIXMAP_CACHE.clear()
    RENDER_CACHE.clear()
    _LAST_SOURCE.clear()


def _render_key(layer: Layer) -> str:
    # Un identifiant d'image désigne toujours le même contenu : seuls les
    # réglages non destructifs et les retournements font varier le rendu.
    state = (layer.asset, sorted(layer.color_replacements.items()), layer.color_fills,
             layer.eraser_strokes, layer.mask, layer.flip_horizontal, layer.flip_vertical)
    return sha1(repr(state).encode("utf-8")).hexdigest()


def pil_to_qimage(image: Image.Image) -> QImage:
    data = image.tobytes("raw", "RGBA")
    return QImage(data, image.width, image.height, image.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def render_layer_edits(layer: Layer, document: Document) -> Image.Image:
    """Source pixels of an image layer with its edits, before its mask, not flipped."""
    asset = layer.image_asset()
    return render_layer_image(
        document.assets[asset], layer.color_replacements,
        layer.color_fills, layer.eraser_strokes, cache_key=asset,
    )


def layer_mask_image(layer: Layer, document: Document, size: tuple[int, int]) -> Image.Image | None:
    """Mask of an image layer at the size of its source pixels, or None without a mask."""
    if not layer.mask:
        return None
    mask = selection.decode(document.assets[layer.mask])
    if mask.size != size:
        mask = mask.resize(size, Image.Resampling.NEAREST)
    return mask


def render_layer_with_mask(layer: Layer, document: Document) -> Image.Image:
    """Source pixels of an image layer with its edits and mask, not flipped."""
    image = render_layer_edits(layer, document)
    mask = layer_mask_image(layer, document, image.size)
    return image if mask is None else selection.apply_alpha(image, mask)


def crop_image_layer(layer: Layer, document: Document,
                     box: tuple[int, int, int, int]) -> tuple[Layer, dict[str, bytes]]:
    """Copy of an image layer cropped to ``box`` (source pixels) that keeps its place on the canvas.

    The source image and the mask are cropped losslessly, eraser strokes and
    fill seeds are shifted, and the position is moved so that the visible
    pixels do not move whatever the scale, rotation or flips. Returns the
    layer and the new assets; raises ValueError when the edits cannot be
    replayed identically on the cropped image.
    """
    left, top, right, bottom = box
    if any(not stroke.get("pixel_centered", False) for stroke in layer.eraser_strokes):
        # Older eraser dabs are placed with round(), which rounds halves to even:
        # only an even shift of their points keeps every dab on the same pixels.
        left, top = left - left % 2, top - top % 2
        box = (left, top, right, bottom)
    with Image.open(BytesIO(document.assets[layer.image_asset()]), formats=ASSET_FORMATS) as source:
        width, height = source.size
        cropped = source.convert("RGBA").crop(box)
    trimmed = deepcopy(layer)
    assets: dict[str, bytes] = {}
    output = BytesIO()
    cropped.save(output, format="PNG")
    trimmed.asset = new_id()
    assets[trimmed.asset] = output.getvalue()
    if layer.mask:
        mask = selection.decode(document.assets[layer.mask])
        if mask.size != (width, height):
            mask = mask.resize((width, height), Image.Resampling.NEAREST)
        trimmed.mask = new_id()
        assets[trimmed.mask] = selection.encode(mask.crop(box))
    trimmed.color_fills = [{**fill, "x": fill["x"] - left, "y": fill["y"] - top} for fill in layer.color_fills]
    trimmed.eraser_strokes = [{**stroke, "points": [[x - left, y - top] for x, y in stroke["points"]]}
                              for stroke in layer.eraser_strokes]
    corner = QPointF(width - right if layer.flip_horizontal else left,
                     height - bottom if layer.flip_vertical else top)
    origin = layer_transform(layer).map(corner)
    trimmed.x, trimmed.y = origin.x(), origin.y()
    probe = Document(document.width, document.height, None, [trimmed], {**document.assets, **assets})
    expected = render_layer_with_mask(layer, document).crop(box)
    if render_layer_with_mask(trimmed, probe).tobytes() != expected.tobytes():
        raise ValueError("les retouches de ce calque ne peuvent pas être rejouées à l'identique après rognage")
    return trimmed, assets


# Last source image read by the colour tools: clicking again on the same layer
# does not decode it again. One entry only, released with the next layer.
_LAST_SOURCE: dict[str, Image.Image] = {}


def layer_source_pixel(layer: Layer, document: Document, x: int, y: int,
                       shown_size: tuple[int, int]) -> tuple[int, int, tuple[int, int, int, int]] | None:
    """Exact colour under the displayed pixel (x, y) of an image layer, with its source position.

    The displayed pixmap is premultiplied: it changes the colour of
    semi-transparent pixels, so tools read the source pixels instead (with the
    layer's edits and mask), mirrored like the display. None outside the layer.
    """
    width, height = shown_size
    if not (0 <= x < width and 0 <= y < height):
        return None
    source_x = width - 1 - x if layer.flip_horizontal else x
    source_y = height - 1 - y if layer.flip_vertical else y
    key = _render_key(layer)
    image = _LAST_SOURCE.get(key)
    if image is None:
        image = render_layer_with_mask(layer, document).convert("RGBA")
        _LAST_SOURCE.clear()
        _LAST_SOURCE[key] = image
    if not (source_x < image.width and source_y < image.height):
        return None
    pixel = cast(tuple[int, int, int, int], image.getpixel((source_x, source_y)))
    return source_x, source_y, pixel


def layer_pixmap(layer: Layer, document: Document) -> QPixmap:
    key = _render_key(layer)
    pixmap = PIXMAP_CACHE.get(key)
    if pixmap is not None:
        return pixmap
    try:
        pixmap = QPixmap.fromImage(pil_to_qimage(render_layer_with_mask(layer, document)))
    except Exception as exc:
        raise ValueError(f"Image illisible pour le calque « {layer.name} » : {exc}") from exc
    if pixmap.isNull():
        raise ValueError(f"Image illisible pour le calque « {layer.name} »")
    if layer.flip_horizontal or layer.flip_vertical:
        pixmap = pixmap.transformed(QTransform().scale(
            -1 if layer.flip_horizontal else 1,
            -1 if layer.flip_vertical else 1,
        ))
    PIXMAP_CACHE.put(key, pixmap)
    return pixmap


# What rendering a layer whose image is damaged or too large raises: tools report
# these to the user (UnidentifiedImageError is an OSError).
RENDER_ERRORS = (ValueError, OSError, Image.DecompressionBombError)
# Item data key set on the stand-in of an image layer whose pixels cannot be decoded.
UNREADABLE_ROLE = 1


def unreadable_layer_pixmap(layer: Layer, document: Document) -> QPixmap:
    """Hatched stand-in for an image layer whose pixels cannot be decoded, at its declared size."""
    width = height = 64
    try:
        with Image.open(BytesIO(document.assets[layer.image_asset()]), formats=ASSET_FORMATS) as source:
            if 0 < source.width * source.height <= MAX_PIXELS:
                width, height = source.size  # the header is often still readable
    except Exception:
        pass
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    color = QColor(COLORS["danger"])
    painter.fillRect(pixmap.rect(), QBrush(color, Qt.BrushStyle.BDiagPattern))
    painter.setPen(QPen(color, 2))
    painter.drawRect(pixmap.rect().adjusted(1, 1, -1, -1))
    painter.end()
    return pixmap


def create_graphic(layer: Layer, document: Document, tolerate_unreadable=None) -> QGraphicsItem:
    """Scene item of a layer. An unreadable image raises, unless ``tolerate_unreadable(layer)``
    is true: it is then shown hatched (see unreadable_layer_pixmap)."""
    item: QGraphicsItem
    if layer.kind == "image":
        unreadable = False
        try:
            pixmap = layer_pixmap(layer, document)
        except ValueError:
            if tolerate_unreadable is None or not tolerate_unreadable(layer):
                raise
            pixmap, unreadable = unreadable_layer_pixmap(layer, document), True
        pixmap_item = QGraphicsPixmapItem(pixmap)
        pixmap_item.setData(UNREADABLE_ROLE, unreadable)
        pixmap_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        item = pixmap_item
    elif layer.kind == "shape":
        item = ShapeGraphicItem(layer)
    else:
        # Un même item vectoriel rend le texte droit et courbé. Le texte reste
        # stocké dans le modèle et entièrement éditable.
        item = CurvedTextGraphicItem(layer)
    item.setData(0, layer.id)
    item.setPos(layer.x, layer.y)
    set_item_geometry(item, layer.sx, layer.sy, layer.rotation)
    item.setOpacity(layer.opacity)
    # A hidden folder hides its layers on the canvas and in every export.
    item.setVisible(document.is_visible(layer))
    return item


def make_scene(document: Document, interactive: bool, tolerate_unreadable=None) -> QGraphicsScene:
    """Scene of the document; ``tolerate_unreadable`` as in create_graphic.

    The canvas tolerates the images that were already damaged in an opened
    project, so that the rest stays editable; renders for output refuse them.
    """
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, document.width, document.height)
    for z, layer in enumerate(document.layers):
        item = create_graphic(layer, document, tolerate_unreadable)
        item.setZValue(z)
        if interactive:
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not layer.locked)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not layer.locked)
        scene.addItem(item)
    return scene


def render_document(document: Document, fit: QSize | None = None) -> QImage:
    """Rendu à la taille exacte du document, sans sélection ni poignées.

    With ``fit``, the document is drawn directly at the largest size that fits
    in it, keeping its proportions (thumbnails): no full-size image is made.
    The image is RGBA8888, the layout Pillow reads without converting it.
    """
    width, height = document.width, document.height
    if fit is not None:
        scale = min(fit.width() / width, fit.height() / height)
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(document.background) if document.background else Qt.GlobalColor.transparent)
    scene = make_scene(document, interactive=False)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, fit is not None)
    scene.render(painter, QRectF(0, 0, width, height), QRectF(0, 0, document.width, document.height))
    painter.end()
    return image


def qimage_png(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buf, "PNG"):  # type: ignore[call-overload]  # QIODevice overload missing from the stubs
        raise ValueError("Échec de l'encodage PNG")
    buf.close()
    return bytes(data.data())


# --- Bridges between Pillow masks and Qt -------------------------------------------

def mask_to_qimage(mask: Image.Image) -> QImage:
    """8-bit mask as a Qt alpha image (same byte layout, rows copied safely)."""
    return QImage(mask.tobytes(), mask.width, mask.height, mask.width,
                  QImage.Format.Format_Alpha8).copy()


def _qimage_as_pil(image: QImage, qt_format: QImage.Format, mode: str) -> Image.Image:
    """One copy only: Pillow reads the Qt buffer in place, then keeps its own copy."""
    if image.format() != qt_format:
        image = image.convertToFormat(qt_format)
    # constBits() is a memoryview, which Pillow reads (its stubs only list bytes).
    view = Image.frombuffer(mode, (image.width(), image.height()), cast(bytes, image.constBits()),
                            "raw", mode, image.bytesPerLine(), 1)
    return view.copy()  # the view must not outlive the QImage


def qimage_to_mask(image: QImage) -> Image.Image:
    return _qimage_as_pil(image, QImage.Format.Format_Alpha8, "L")


def qimage_to_pil(image: QImage) -> Image.Image:
    return _qimage_as_pil(image, QImage.Format.Format_RGBA8888, "RGBA")


def scale_rotation(sx: float, sy: float, rotation: float) -> QTransform:
    """Scale along the layer's own axes, then rotate: a rotated layer stays a rectangle."""
    return QTransform.fromScale(sx, sy) * QTransform().rotate(rotation)


def set_item_geometry(item: QGraphicsItem, sx: float, sy: float, rotation: float) -> None:
    """Give a scene item the layer's scale and rotation, in the order of ``layer_transform``.

    QGraphicsItem.setRotation() would rotate before the transform() scale: a
    rotated layer with sx != sy would be drawn sheared, and masks, trims and
    resize handles computed with layer_transform would miss its pixels.
    """
    item.setRotation(0)
    item.setTransform(scale_rotation(sx, sy, rotation))


def layer_transform(layer: Layer) -> QTransform:
    """Item-local to document coordinates, identical to the canvas item (see set_item_geometry)."""
    return scale_rotation(layer.sx, layer.sy, layer.rotation) * QTransform.fromTranslate(layer.x, layer.y)


def document_mask_to_layer(mask: Image.Image, layer: Layer, size: tuple[int, int],
                           smooth: bool = False) -> Image.Image:
    """Resample a document-space mask into the source pixels of an image layer.

    The result is aligned with the layer's source image (flips undone), so it
    can be stored as a layer mask that survives later moves and flips.
    """
    target = QImage(size[0], size[1], QImage.Format.Format_Alpha8)
    target.fill(0)
    inverse, invertible = layer_transform(layer).inverted()
    if invertible:
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        painter.setTransform(inverse)
        painter.drawImage(0, 0, mask_to_qimage(mask))
        painter.end()
    local = qimage_to_mask(target)
    if layer.flip_horizontal:
        local = local.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if layer.flip_vertical:
        local = local.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return local


def _displayed_orientation(mask: Image.Image, layer: Layer) -> Image.Image:
    """Source-aligned mask flipped like the displayed pixmap (flips are their own inverse)."""
    if layer.flip_horizontal:
        mask = mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if layer.flip_vertical:
        mask = mask.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return mask


def layer_mask_to_document(mask: Image.Image, layer: Layer, size: tuple[int, int],
                           smooth: bool = False) -> Image.Image:
    """Inverse of document_mask_to_layer: a source-aligned mask drawn where the layer is shown."""
    target = QImage(size[0], size[1], QImage.Format.Format_Alpha8)
    target.fill(0)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
    painter.setTransform(layer_transform(layer))
    painter.drawImage(0, 0, mask_to_qimage(_displayed_orientation(mask, layer)))
    painter.end()
    return qimage_to_mask(target)


def layer_source_position(layer: Layer, point: QPointF, size: tuple[int, int]) -> tuple[int, int] | None:
    """Source pixel of an image layer under a document point, flips undone; None off the layer."""
    inverse, invertible = layer_transform(layer).inverted()
    if not invertible:
        return None
    local = inverse.map(point)
    x, y = floor(local.x()), floor(local.y())
    width, height = size
    if not (0 <= x < width and 0 <= y < height):
        return None
    return (width - 1 - x if layer.flip_horizontal else x,
            height - 1 - y if layer.flip_vertical else y)


def layer_selection_outline(mask: Image.Image, layer: Layer) -> QPainterPath:
    """Document-space outline of a source-aligned mask, at the resolution of the layer's pixels.

    The canvas shows the source pixels of a scaled layer: a selection made on
    them is outlined pixel by pixel, even where the document grid is coarser
    or outside the frame. Too fragmented, it is outlined by its bounding box.
    """
    shown = _displayed_orientation(mask, layer)
    path = selection_outline(shown)
    if path is None:
        path = QPainterPath()
        box = shown.getbbox()
        if box is not None:
            path.addRect(QRectF(box[0], box[1], box[2] - box[0], box[3] - box[1]))
    return layer_transform(layer).map(path)


def render_layers(document: Document, layer_ids=None, with_background: bool = False) -> Image.Image:
    """Document-sized RGBA rendering of some layers (all visible ones by default)."""
    keep = None if layer_ids is None else set(layer_ids)
    layers = [layer for layer in document.layers if keep is None or layer.id in keep]
    partial = Document(document.width, document.height,
                       document.background if with_background else None, layers, document.assets,
                       document.folders)
    return qimage_to_pil(render_document(partial))


def render_layers_region(document: Document, layer_ids) -> tuple[Image.Image, tuple[int, int]] | None:
    """Visible pixels of some layers, cropped to their content, with the document position.

    Unlike render_layers, parts outside the canvas are kept, so that merging
    layers loses nothing. None when the layers show no pixel at all.
    """
    keep = set(layer_ids)
    partial = Document(document.width, document.height, None,
                       [layer for layer in document.layers if layer.id in keep], document.assets,
                       document.folders)
    scene = make_scene(partial, interactive=False)
    bounds = QRectF()
    for item in scene.items():
        if item.isVisible():
            bounds = bounds.united(item.sceneBoundingRect())
    if bounds.isEmpty():
        return None
    area = bounds.toAlignedRect()
    if area.width() * area.height() > MAX_PIXELS:
        raise ValueError("le résultat dépasserait 67 mégapixels")
    target = QImage(area.width(), area.height(), QImage.Format.Format_ARGB32)
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    scene.render(painter, QRectF(0, 0, area.width(), area.height()), QRectF(area))
    painter.end()
    trimmed = trim_transparent(qimage_to_pil(target))
    if trimmed is None:
        return None
    image, (left, top, _right, _bottom) = trimmed
    return image, (area.left() + left, area.top() + top)


def layers_bounds(document: Document, layer_ids) -> tuple[float, float, float, float] | None:
    """Document-space box (left, top, right, bottom) of some layers, hidden or not."""
    keep = set(layer_ids)
    bounds = QRectF()
    for layer in document.layers:
        if layer.id in keep:
            # Only the geometry matters: a damaged image counts with its declared size.
            item = create_graphic(layer, document, lambda _layer: True)
            bounds = bounds.united(item.sceneBoundingRect())
    if bounds.isNull():
        return None
    return bounds.left(), bounds.top(), bounds.right(), bounds.bottom()


def merge_changes_appearance(document: Document, layer_ids) -> bool:
    """True when merging these layers in place of the topmost one would change the image.

    The merged layer takes the place of the topmost source: an unselected
    visible layer lying between the sources then passes below the sources that
    were under it. The result differs only where such a layer overlaps them.
    """
    wanted = set(layer_ids)
    indices = [index for index, layer in enumerate(document.layers) if layer.id in wanted]
    if len(indices) < 2:
        return False
    for index in range(indices[0] + 1, indices[-1]):
        layer = document.layers[index]
        if layer.id in wanted or not document.is_visible(layer):
            continue
        below = [other.id for other in document.layers[indices[0]:index] if other.id in wanted]
        overlap = ImageChops.multiply(render_layers(document, [layer.id]).getchannel("A"),
                                      render_layers(document, below).getchannel("A"))
        if overlap.getbbox() is not None:
            return True
    return False


def selection_overlay(mask: Image.Image, show_mask: bool) -> QImage:
    """Tint drawn over the canvas: light cyan inside, or red outside in mask view."""
    if show_mask:
        color, alpha = QColor(COLORS["danger"]), selection.invert(mask).point(lambda v: v * 110 // 255)
    else:
        color, alpha = QColor(COLORS["primary"]), mask.point(lambda v: v * 45 // 255)
    tint = Image.new("RGBA", mask.size, (color.red(), color.green(), color.blue(), 0))
    tint.putalpha(alpha)
    return pil_to_qimage(tint)


def selection_outline(mask: Image.Image, max_rects: int = 20000) -> QPainterPath | None:
    """Outline of the selected pixels, or None when it is too fragmented to draw."""
    binary = mask.point([0] * 128 + [255] * 128)
    if binary.getbbox() is None:
        return QPainterPath()
    image = mask_to_qimage(binary).convertToFormat(QImage.Format.Format_ARGB32)
    region = QRegion(QBitmap.fromImage(image.createAlphaMask()))
    if region.rectCount() > max_rects:
        return None
    path = QPainterPath()
    path.addRegion(region)
    return path.simplified()


def checker_brush() -> QBrush:
    """Motif de damier dessiné une fois, puis répété par Qt."""
    tile = CHECKER_TILE
    pixmap = QPixmap(tile * 2, tile * 2)
    pixmap.fill(QColor(COLORS["checker_light"]))
    painter = QPainter(pixmap)
    dark = QColor(COLORS["checker_dark"])
    painter.fillRect(tile, 0, tile, tile, dark)
    painter.fillRect(0, tile, tile, tile, dark)
    painter.end()
    return QBrush(pixmap)
