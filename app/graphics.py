"""Canvas interactif et rendu sans les accessoires d'édition."""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from hashlib import sha1
from io import BytesIO
from math import atan2, cos, degrees, hypot, radians, sin
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
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
    QRadialGradient,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from . import selection
from .model import ASSET_FORMATS, MAX_PIXELS, Document, Layer
from .textpath import custom_points, drag_handle, handle_points, normalize_controls, normalize_shape, sample_path
from .theme import COLORS

if TYPE_CHECKING:
    from .window import MainWindow

MIN_ZOOM = 0.01
MAX_ZOOM = 64.0
CHECKER_TILE = 18
ROTATION_HANDLE_DISTANCE = 35  # pixels écran au-dessus du cadre


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
        available = {family.casefold(): family for family in QFontDatabase.families()}
        family = available.get(layer.font_family.casefold(), QFont().defaultFamily())
        self.font = QFont(family, layer.font_size)
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
        line_advances = [[metrics.horizontalAdvance(char) for char in line] for line in self.lines]
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
        for index, (line, advances, width) in enumerate(zip(self.lines, line_advances, widths)):
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
            for char, advance in zip(line, advances):
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


def _render_operations(replacements: dict[str, str], fills: list[dict], strokes: list[dict]) -> list[tuple]:
    """Non-destructive edits of an image layer, flattened in their replay order.

    Colour replacements come first, then eraser strokes and fills interleaved
    by ``after_strokes``. Each operation only depends on the image before it,
    which lets renders resume from a cached prefix.
    """
    operations: list[tuple] = []
    mapping = {tuple(QColor(old).getRgb()[:3]): tuple(QColor(new).getRgb()[:3])
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
            "fill", source.getRgb()[:3], target_color.getRgb()[:3],
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
    if not keys:
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
    x, y = seed
    if not (0 <= x < mask.width and 0 <= y < mask.height) or mask.getpixel(seed) == 0:
        return Image.new("L", mask.size, 0)
    region = mask.copy()
    ImageDraw.floodfill(region, seed, 128, thresh=0)
    return region.point([255 if value == 128 else 0 for value in range(256)])


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


def _interpolated_points(points: list[list[float]], spacing: float):
    if not points:
        return
    yield points[0][0], points[0][1]
    for start, end in zip(points, points[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = (dx * dx + dy * dy) ** 0.5
        steps = max(1, int(distance / max(0.25, spacing)) + 1)
        for index in range(1, steps + 1):
            ratio = index / steps
            yield start[0] + dx * ratio, start[1] + dy * ratio


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
        if shape == "square" and pixel_art:
            draw.rectangle((0, 0, size - 1, size - 1), fill=maximum)
        else:
            draw.ellipse((0, 0, size - 1, size - 1), fill=maximum)
        return dab
    pixels = dab.load()
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


def apply_eraser_strokes(image: Image.Image, strokes: list[dict]) -> Image.Image:
    """Applique des traits à l'alpha, sans toucher aux couleurs ni lisser le pixel art."""
    if not strokes:
        return image
    result = image.copy()
    alpha = result.getchannel("A")
    for stroke in strokes:
        points = stroke.get("points", [])
        if not points:
            continue
        size = max(1, int(stroke.get("size", 1)))
        pixel_art = bool(stroke.get("pixel_art", True))
        shape = "square" if stroke.get("shape") == "square" else "circle"
        dab = _eraser_dab(
            size, shape, pixel_art,
            max(0, min(100, int(stroke.get("hardness", 100)))),
            max(1, min(100, int(stroke.get("opacity", 100)))),
        )
        coverage = Image.new("L", result.size, 0)
        offset = (size - 1) / 2
        spacing = 0.5 if pixel_art else max(0.5, size * 0.2)
        # Les empreintes d'un même trait se combinent par maximum : l'opacité
        # choisie reste celle du trait, au lieu de s'additionner à chaque pas.
        for x, y in _interpolated_points(points, spacing):
            left, top = round(x - offset), round(y - offset)
            coverage.paste(ImageChops.lighter(coverage.crop((
                left, top, left + size, top + size
            )), dab), (left, top))
        inverse = ImageChops.invert(coverage)
        alpha = ImageChops.multiply(alpha, inverse)
    result.putalpha(alpha)
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


def layer_pixmap(layer: Layer, document: Document) -> QPixmap:
    key = _render_key(layer)
    pixmap = PIXMAP_CACHE.get(key)
    if pixmap is not None:
        return pixmap
    try:
        image = render_layer_image(
            document.assets[layer.asset], layer.color_replacements,
            layer.color_fills, layer.eraser_strokes, cache_key=layer.asset,
        )
        if layer.mask:
            mask = selection.decode(document.assets[layer.mask])
            if mask.size != image.size:
                mask = mask.resize(image.size, Image.Resampling.NEAREST)
            image = selection.apply_alpha(image, mask)
        pixmap = QPixmap.fromImage(pil_to_qimage(image))
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


def create_graphic(layer: Layer, document: Document) -> QGraphicsItem:
    if layer.kind == "image":
        item = QGraphicsPixmapItem(layer_pixmap(layer, document))
        item.setTransformationMode(Qt.TransformationMode.FastTransformation)
    else:
        # Un même item vectoriel rend le texte droit et courbé. Le texte reste
        # stocké dans le modèle et entièrement éditable.
        item = CurvedTextGraphicItem(layer)
    item.setData(0, layer.id)
    item.setPos(layer.x, layer.y)
    item.setTransform(QTransform.fromScale(layer.sx, layer.sy))
    item.setRotation(layer.rotation)
    item.setOpacity(layer.opacity)
    item.setVisible(layer.visible)
    return item


def make_scene(document: Document, interactive: bool) -> QGraphicsScene:
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, document.width, document.height)
    for z, layer in enumerate(document.layers):
        item = create_graphic(layer, document)
        item.setZValue(z)
        if interactive:
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not layer.locked)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not layer.locked)
        scene.addItem(item)
    return scene


def render_document(document: Document) -> QImage:
    """Rendu à la taille exacte du document, sans sélection ni poignées."""
    image = QImage(document.width, document.height, QImage.Format.Format_ARGB32)
    image.fill(QColor(document.background) if document.background else Qt.GlobalColor.transparent)
    scene = make_scene(document, interactive=False)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    scene.render(painter, QRectF(0, 0, document.width, document.height),
                 QRectF(0, 0, document.width, document.height))
    painter.end()
    return image


def qimage_png(image: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buf, "PNG"):
        raise ValueError("Échec de l'encodage PNG")
    buf.close()
    return bytes(data)


# --- Bridges between Pillow masks and Qt -------------------------------------------

def mask_to_qimage(mask: Image.Image) -> QImage:
    """8-bit mask as a Qt alpha image (same byte layout, rows copied safely)."""
    return QImage(mask.tobytes(), mask.width, mask.height, mask.width,
                  QImage.Format.Format_Alpha8).copy()


def qimage_to_mask(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_Alpha8)
    stride = image.bytesPerLine()
    data = bytes(image.constBits())[:stride * image.height()]
    return Image.frombytes("L", (image.width(), image.height()), data, "raw", "L", stride)


def qimage_to_pil(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    stride = image.bytesPerLine()
    data = bytes(image.constBits())[:stride * image.height()]
    return Image.frombytes("RGBA", (image.width(), image.height()), data, "raw", "RGBA", stride)


def layer_transform(layer: Layer) -> QTransform:
    """Item-local to document coordinates, identical to the canvas item."""
    return (QTransform.fromScale(layer.sx, layer.sy) * QTransform().rotate(layer.rotation)
            * QTransform.fromTranslate(layer.x, layer.y))


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


def render_layers(document: Document, layer_ids=None, with_background: bool = False) -> Image.Image:
    """Document-sized RGBA rendering of some layers (all visible ones by default)."""
    keep = None if layer_ids is None else set(layer_ids)
    layers = [layer for layer in document.layers if keep is None or layer.id in keep]
    partial = Document(document.width, document.height,
                       document.background if with_background else None, layers, document.assets)
    return qimage_to_pil(render_document(partial))


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


class CanvasView(QGraphicsView):
    """Sélection, déplacement à la souris, quatre poignées et rotation."""

    def __init__(self, window: MainWindow):
        super().__init__()
        # Not named "window": that would hide QWidget.window().
        self.main_window = window
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan_last = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(COLORS["canvas"]))
        self._checker = checker_brush()
        self.mode = None
        self.old_layer = None
        self.drag_item = None
        self.handle_index = None
        self.selection_drag = None
        # Pixels being moved with Ctrl+drag inside the selection.
        self.lift = None
        self.selection_overlay_image: QImage | None = None
        self.selection_path: QPainterPath | None = None
        self.selection_box: tuple[int, int, int, int] | None = None
        self.fixed_world = None
        self.fixed_local = None
        self.corner_local = None
        self.angle_offset = 0
        self.fixed_center = None
        self.eraser_item = None
        self.eraser_points: list[QPointF] = []
        self.eraser_cursor_local: QPointF | None = None
        self.eraser_preview_image: QImage | None = None
        self.eraser_source_image: QImage | None = None
        self.eraser_mask: QImage | None = None
        self.eraser_original_pixmap: QPixmap | None = None
        self.eraser_preview_last: QPointF | None = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self.scene():
            return
        area = QRectF(0, 0, self.main_window.document.width, self.main_window.document.height).intersected(rect)
        if area.isEmpty():
            return
        background = self.main_window.document.background
        painter.save()
        if background:
            painter.fillRect(area, QColor(background))
        else:
            painter.setBrushOrigin(0, 0)
            painter.fillRect(area, self._checker)
        painter.restore()

    def selected_graphic(self):
        for item in self.scene().selectedItems() if self.scene() else []:
            if self.main_window.document.layer(item.data(0)):
                return item
        return None

    def graphic_for(self, layer_id: str | None):
        if not layer_id or self.scene() is None:
            return None
        return next((item for item in self.scene().items() if item.data(0) == layer_id), None)

    def tool_target_graphic(self):
        """Graphique du calque visé par les outils, même s'il n'est plus sélectionné."""
        return self.graphic_for(self.main_window.tool_target_id())

    def local_handles(self, item):
        bounds = item.boundingRect()
        x, y, w, h = bounds.x(), bounds.y(), bounds.width(), bounds.height()
        return [QPointF(x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(x, y + h)]

    def rotation_point(self, item):
        # Distance constante à l'écran, quels que soient l'échelle du calque et le zoom.
        bounds = item.boundingRect()
        top = item.mapToScene(QPointF(bounds.center().x(), bounds.top()))
        center = item.mapToScene(bounds.center())
        direction = top - center
        length = hypot(direction.x(), direction.y())
        if length < 1e-9:
            direction, length = QPointF(0, -1), 1.0
        distance = ROTATION_HANDLE_DISTANCE / self.transform().m11()
        return top + direction * (distance / length)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if not self.scene():
            return
        painter.save()
        factor = self.transform().m11()
        border_pen = QPen(QColor(COLORS["canvas_border"]), 1)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, self.main_window.document.width, self.main_window.document.height))
        self._draw_selection(painter)
        # Transform and shape handles only make sense without an active tool.
        item = None if self.main_window.any_tool_active() else self.selected_graphic()
        layer = self.main_window.document.layer(item.data(0)) if item else None
        if isinstance(item, CurvedTextGraphicItem) and layer:
            if layer.show_curve_guide:
                guide_pen = QPen(QColor(COLORS["primary"]), 1)
                guide_pen.setCosmetic(True)
                guide_pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(guide_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(item.sceneTransform().map(item.visual_guide_path()))
            polygon = [item.mapToScene(point) for point in item.control_polygon_local()]
            if polygon:
                # Bézier tangents of the custom shape: start -> P1 and P2 -> end.
                tangent_pen = QPen(QColor(COLORS["muted"]), 1)
                tangent_pen.setCosmetic(True)
                tangent_pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(tangent_pen)
                painter.drawLine(polygon[0], polygon[1])
                painter.drawLine(polygon[2], polygon[3])
            if not layer.locked:
                radius = 7 / factor
                painter.setPen(QPen(QColor(COLORS["background"]), 1 / factor))
                painter.setBrush(QColor(COLORS["primary"]))
                for handle in item.shape_handles_local():
                    painter.drawEllipse(item.mapToScene(handle), radius, radius)
        if item:
            size = 9 / factor
            painter.setBrush(QColor(COLORS["primary"]))
            painter.setPen(QPen(QColor(COLORS["background"]), 1 / factor))
            for local in self.local_handles(item):
                p = item.mapToScene(local)
                painter.drawRect(QRectF(p.x() - size/2, p.y() - size/2, size, size))
            p = self.rotation_point(item)
            painter.setBrush(QColor(COLORS["rotation_handle"]))
            painter.drawEllipse(p, size/2, size/2)
        target = self.eraser_item or self.tool_target_graphic()
        if self.main_window.eraser_active and isinstance(target, QGraphicsPixmapItem):
            local = self.eraser_cursor_local
            if local is not None:
                size = self.main_window.eraser_size.value()
                offset = (size - 1) / 2
                path = QPainterPath()
                if self.main_window.eraser_pixel_art.isChecked():
                    left, top = round(local.x() - offset), round(local.y() - offset)
                    bounds = QRectF(left, top, size, size)
                else:
                    bounds = QRectF(local.x() - offset, local.y() - offset, size, size)
                if self.main_window.eraser_shape.currentData() == "square" and self.main_window.eraser_pixel_art.isChecked():
                    path.addRect(bounds)
                else:
                    path.addEllipse(bounds)
                scene_path = target.sceneTransform().map(path)
                preview_pen = QPen(QColor(COLORS["primary"]), 1)
                preview_pen.setCosmetic(True)
                painter.setPen(preview_pen)
                fill = QColor(COLORS["primary"])
                fill.setAlpha(45)
                painter.setBrush(fill)
                painter.drawPath(scene_path)
            if len(self.eraser_points) > 1:
                path = QPainterPath(self.eraser_points[0])
                for point in self.eraser_points[1:]:
                    path.lineTo(point)
                scene_path = target.sceneTransform().map(path)
                stroke_color = QColor(COLORS["primary"])
                stroke_color.setAlpha(150)
                stroke_pen = QPen(stroke_color, 2)
                stroke_pen.setCosmetic(True)
                painter.setPen(stroke_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(scene_path)
        painter.restore()

    def update_selection_visual(self, mask, show_mask: bool) -> None:
        """Recompute the tint and outline once per selection change."""
        if mask is None or selection.is_empty(mask):
            self.selection_overlay_image = self.selection_path = self.selection_box = None
        else:
            self.selection_overlay_image = selection_overlay(mask, show_mask)
            self.selection_path = selection_outline(mask)
            self.selection_box = selection.bounds(mask)
        self.viewport().update()

    def _selection_pens(self) -> tuple[QPen, QPen]:
        # White under black dashes: visible on any background, at any zoom.
        under = QPen(QColor("white"), 1)
        under.setCosmetic(True)
        over = QPen(QColor("black"), 1, Qt.PenStyle.DashLine)
        over.setCosmetic(True)
        return under, over

    def _draw_selection(self, painter: QPainter) -> None:
        document = self.main_window.document
        if self.selection_overlay_image is not None:
            painter.drawImage(QRectF(0, 0, document.width, document.height), self.selection_overlay_image)
        outlines = []
        if self.selection_path is not None:
            outlines.append(self.selection_path)
        elif self.selection_box is not None:
            box = QPainterPath()
            left, top, right, bottom = self.selection_box
            box.addRect(QRectF(left, top, right - left, bottom - top))
            outlines.append(box)
        if self.selection_drag is not None:
            outlines.append(self._drag_shape_path())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for path in outlines:
            for pen in self._selection_pens():
                painter.setPen(pen)
                painter.drawPath(path)
        if self.lift is not None:
            painter.setOpacity(0.85)
            painter.drawPixmap(self.lift["origin"] + self.lift["delta"], self.lift["pixmap"])
            painter.setOpacity(1.0)

    def _drag_rect(self) -> QRectF:
        rect = QRectF(self.selection_drag["start"], self.selection_drag["end"]).normalized()
        if self.main_window.selection_pixel_perfect.isChecked():
            rect = QRectF(round(rect.left()), round(rect.top()),
                          round(rect.right()) - round(rect.left()), round(rect.bottom()) - round(rect.top()))
        return rect

    def _drag_shape_path(self) -> QPainterPath:
        path = QPainterPath()
        rect = self._drag_rect()
        if self.selection_drag["tool"] == "ellipse":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        return path

    def _selection_press(self, event) -> None:
        scene_position = self.mapToScene(event.position().toPoint())
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            lift = self.main_window.lift_selection(scene_position)
            if lift is not None:
                self.lift = {**lift, "start": scene_position, "delta": QPointF(0, 0)}
            return
        if self.main_window.selection_tool == "wand":
            self.main_window.apply_magic_wand(scene_position, modifiers)
            return
        self.selection_drag = {"tool": self.main_window.selection_tool, "start": scene_position,
                               "end": scene_position, "modifiers": modifiers}

    def _hit_handle(self, item, viewport_pos):
        if isinstance(item, CurvedTextGraphicItem):
            for index, local in enumerate(item.shape_handles_local()):
                if (self.mapFromScene(item.mapToScene(local)) - viewport_pos).manhattanLength() <= 15:
                    return "shape", index
        targets = [("resize", i, item.mapToScene(pt)) for i, pt in enumerate(self.local_handles(item))]
        targets.append(("rotate", None, self.rotation_point(item)))
        for mode, index, world in targets:
            if (self.mapFromScene(world) - viewport_pos).manhattanLength() <= 13:
                return mode, index
        return None, None

    def _start_eraser_stroke(self, event) -> None:
        layer_id = self.main_window.tool_target_id()
        item = self.graphic_for(layer_id)
        layer = self.main_window.document.layer(layer_id)
        if not layer or not isinstance(item, QGraphicsPixmapItem):
            self.main_window.statusBar().showMessage(
                "La gomme nécessite un calque image sélectionné", 3000
            )
            return
        if layer.locked:
            self.main_window.statusBar().showMessage(
                "Déverrouillez le calque pour utiliser la gomme", 3000
            )
            return
        local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
        if not item.boundingRect().contains(local):
            return
        self.eraser_item = item
        self.eraser_original_pixmap = item.pixmap()
        source = item.pixmap().toImage().convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied
        )
        self.eraser_source_image = source
        self.eraser_preview_image = source.copy()
        self.eraser_mask = None
        if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and self.main_window.last_eraser_point
                and self.main_window.last_eraser_layer_id == layer.id):
            self.eraser_points = [QPointF(*self.main_window.last_eraser_point), local]
        else:
            self.eraser_points = [local]
        self._apply_eraser_preview_segment(self.eraser_points[0], local)
        self.eraser_preview_last = local
        self.eraser_cursor_local = local

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # Un outil actif ne modifie jamais la sélection : il continue de
            # viser le dernier calque choisi.
            if self.main_window.eraser_active:
                self._start_eraser_stroke(event)
                self.viewport().update()
                event.accept()
                return
            if self.main_window.picker_active:
                item = self.itemAt(event.position().toPoint())
                self.main_window.sample_canvas_color(item, self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.paint_mode:
                self.main_window.paint_canvas_color(self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.text_tool_active:
                self.main_window.begin_inline_text_create(self.mapToScene(event.position().toPoint()))
                event.accept()
                return
            if self.main_window.selection_tool:
                self._selection_press(event)
                self.viewport().update()
                event.accept()
                return
            item = self.selected_graphic()
            layer = self.main_window.document.layer(item.data(0)) if item else None
            if item and layer and not layer.locked:
                mode, handle = self._hit_handle(item, event.position().toPoint())
                if mode:
                    self.mode = mode
                    self.old_layer = self.main_window.document.clone()
                    self.drag_item = item
                    self.handle_index = handle
                    if mode == "resize":
                        local = self.local_handles(item)
                        self.corner_local = local[handle]
                        self.fixed_local = local[(handle + 2) % 4]
                        self.fixed_world = item.mapToScene(self.fixed_local)
                    elif mode == "rotate":
                        self.fixed_center = item.mapToScene(item.boundingRect().center())
                        sp = self.mapToScene(event.position().toPoint())
                        self.angle_offset = degrees(atan2(sp.y()-self.fixed_center.y(), sp.x()-self.fixed_center.x())) - layer.rotation
                    event.accept()
                    return
            at = self.itemAt(event.position().toPoint())
            at_layer = self.main_window.document.layer(at.data(0)) if at else None
            if at_layer and not at_layer.locked:
                self.mode = "move"
                self.old_layer = self.main_window.document.clone()
                self.drag_item = at
        super().mousePressEvent(event)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        # Double-clicking a text edits its content directly on the canvas.
        if event.button() == Qt.MouseButton.LeftButton and not self.main_window.any_tool_active():
            item = self.itemAt(event.position().toPoint())
            layer = self.main_window.document.layer(item.data(0)) if item else None
            if isinstance(item, CurvedTextGraphicItem) and layer and not layer.locked:
                self.mode = self.drag_item = self.old_layer = None
                self.main_window.begin_inline_text_edit(layer.id)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        # Copy, cut and paste are window actions whose shortcuts are handled before
        # this event. Delete is also an action; it stays here, with its Backspace
        # alias, for a canvas whose window is not shown (its shortcuts are inactive).
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # With an active selection, Delete erases its content instead of the layer.
            self.main_window.delete_selection_or_layer()
            event.accept()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in arrows and not self.main_window.any_tool_active():
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = arrows[event.key()]
            if self.main_window.nudge_layer(dx * step, dy * step):
                event.accept()
                return
        if event.key() == Qt.Key.Key_BracketLeft:
            self.main_window.adjust_eraser_size(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_BracketRight:
            self.main_window.adjust_eraser_size(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item and self.main_window.document.layer(item.data(0)):
            self.main_window.select_layer(item.data(0))
        self.main_window.show_canvas_context_menu(event.globalPos())
        event.accept()

    def dragEnterEvent(self, event):
        if self.main_window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.main_window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.main_window.image_paths_from_mime(event.mimeData())
        if paths:
            self.main_window._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._pan_last is not None:
            pos = event.position().toPoint()
            delta = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self.selection_drag is not None or self.lift is not None:
            position = self.mapToScene(event.position().toPoint())
            if self.selection_drag is not None:
                self.selection_drag["end"] = position
            else:
                delta = position - self.lift["start"]
                self.lift["delta"] = QPointF(round(delta.x()), round(delta.y()))
            self.viewport().update()
            event.accept()
            return
        if self.main_window.eraser_active:
            item = self.eraser_item or self.tool_target_graphic()
            if item and isinstance(item, QGraphicsPixmapItem):
                local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
                self.eraser_cursor_local = local
                if self.eraser_item is item and event.buttons() & Qt.MouseButton.LeftButton:
                    if not self.eraser_points or (local - self.eraser_points[-1]).manhattanLength() >= 0.25:
                        self.eraser_points.append(local)
                        self._apply_eraser_preview_segment(self.eraser_preview_last or local, local)
                        self.eraser_preview_last = local
                self.viewport().update()
            event.accept()
            return
        if self.mode in ("resize", "rotate", "shape") and self.drag_item:
            item = self.drag_item
            old = self.old_layer.layer(item.data(0))
            mouse = self.mapToScene(event.position().toPoint())
            if self.mode == "shape" and isinstance(item, CurvedTextGraphicItem):
                # Live deformation; the model is only updated on release.
                item.drag_shape_handle(self.handle_index, item.mapFromScene(mouse))
                self.main_window.show_text_shape(item.path_shape, item.curve_intensity)
            elif self.mode == "resize":
                d = mouse - self.fixed_world
                r = radians(old.rotation)
                dx = cos(r)*d.x() + sin(r)*d.y()
                dy = -sin(r)*d.x() + cos(r)*d.y()
                local_dx = self.corner_local.x() - self.fixed_local.x()
                local_dy = self.corner_local.y() - self.fixed_local.y()
                sx = max(0.05, min(50, dx / local_dx))
                sy = max(0.05, min(50, dy / local_dy))
                item.setTransform(QTransform.fromScale(sx, sy))
                off_x = cos(r)*sx*self.fixed_local.x() - sin(r)*sy*self.fixed_local.y()
                off_y = sin(r)*sx*self.fixed_local.x() + cos(r)*sy*self.fixed_local.y()
                item.setPos(self.fixed_world - QPointF(off_x, off_y))
            else:
                heading = degrees(atan2(mouse.y()-self.fixed_center.y(), mouse.x()-self.fixed_center.x()))
                angle = heading - self.angle_offset
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    angle = round(angle / 15) * 15
                item.setRotation(angle)
                shift = self.fixed_center - item.mapToScene(item.boundingRect().center())
                item.setPos(item.pos() + shift)
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton and self.main_window.eraser_active
                and self.eraser_item and self.eraser_points):
            layer_id = self.eraser_item.data(0)
            points = self.eraser_points
            last = points[-1]
            # L'aperçu est retiré avant validation : si le trait est refusé,
            # le calque ne garde pas un effacement absent du document.
            self.cancel_eraser_preview()
            self.main_window.commit_eraser_stroke(layer_id, points)
            self.main_window.last_eraser_point = (last.x(), last.y())
            self.main_window.last_eraser_layer_id = layer_id
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.selection_drag is not None:
            drag, rect = self.selection_drag, self._drag_rect()
            self.selection_drag = None
            self.main_window.apply_selection_shape(drag["tool"], rect, drag["modifiers"])
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.lift is not None:
            delta, self.lift = self.lift["delta"], None
            self.main_window.move_selection_content(int(delta.x()), int(delta.y()))
            self.viewport().update()
            event.accept()
            return
        mode, item, before = self.mode, self.drag_item, self.old_layer
        if mode == "shape" and item and before and isinstance(item, CurvedTextGraphicItem):
            self.main_window.commit_text_shape(before, item.data(0), item.path_shape,
                                          item.curve_intensity, item.controls)
            self.mode = self.drag_item = self.old_layer = None
            self.viewport().update()
            event.accept()
            return
        if mode not in ("resize", "rotate"):
            super().mouseReleaseEvent(event)
        if item and before and mode:
            src = before.layer(item.data(0))
            if src:
                sx = item.transform().m11()
                sy = item.transform().m22()
                state = (item.pos().x(), item.pos().y(), sx, sy, item.rotation())
                old_state = (src.x, src.y, src.sx, src.sy, src.rotation)
                if any(abs(a-b) > 0.001 for a,b in zip(state, old_state)):
                    self.main_window.commit_canvas_transform(before, src.id, state,
                                                        "Déplacer" if mode == "move" else "Redimensionner" if mode == "resize" else "Faire pivoter")
        self.mode = self.drag_item = self.old_layer = None
        self.viewport().update()
        event.accept()

    def leaveEvent(self, event):
        if not self.eraser_item:
            self.eraser_cursor_local = None
            self.viewport().update()
        super().leaveEvent(event)

    def _apply_eraser_preview_segment(self, start: QPointF, end: QPointF) -> None:
        """Met à jour uniquement l'aperçu affiché pendant le trait courant."""
        if self.eraser_preview_image is None or self.eraser_item is None:
            return
        if self.eraser_mask is None or self.eraser_mask.size() != self.eraser_preview_image.size():
            self.eraser_source_image = self.eraser_preview_image.copy()
            self.eraser_mask = QImage(self.eraser_preview_image.size(),
                                      QImage.Format.Format_ARGB32_Premultiplied)
            self.eraser_mask.fill(Qt.GlobalColor.transparent)
        pixel_art = self.main_window.eraser_pixel_art.isChecked()
        size = self.main_window.eraser_size.value()
        opacity = self.main_window.eraser_opacity.value() / 100
        dx, dy = end.x() - start.x(), end.y() - start.y()
        distance = (dx * dx + dy * dy) ** 0.5
        spacing = 0.5 if pixel_art else max(0.5, size * 0.2)
        steps = max(1, int(distance / spacing) + 1)
        offset = (size - 1) / 2
        # Le masque mémorise la forme du trait à pleine intensité ; l'opacité est
        # appliquée une seule fois, comme dans le rendu final du calque.
        painter = QPainter(self.eraser_mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not pixel_art)
        painter.setPen(Qt.PenStyle.NoPen)
        dirty = None
        for index in range(steps + 1):
            ratio = index / steps
            x, y = start.x() + dx * ratio, start.y() + dy * ratio
            if pixel_art:
                bounds = QRectF(round(x - offset), round(y - offset), size, size)
                painter.setBrush(QColor(0, 0, 0, 255))
                if self.main_window.eraser_shape.currentData() == "square":
                    painter.drawRect(bounds)
                else:
                    painter.drawEllipse(bounds)
            else:
                radius = size / 2
                bounds = QRectF(x - radius, y - radius, size, size)
                gradient = QRadialGradient(QPointF(x, y), radius)
                hardness = self.main_window.eraser_hardness.value() / 100
                gradient.setColorAt(0, QColor(0, 0, 0, 255))
                gradient.setColorAt(hardness, QColor(0, 0, 0, 255))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                painter.setBrush(QBrush(gradient))
                painter.drawEllipse(bounds)
            dirty = bounds if dirty is None else dirty.united(bounds)
        painter.end()
        area = dirty.toAlignedRect().adjusted(-1, -1, 1, 1).intersected(self.eraser_preview_image.rect())
        if not area.isEmpty():
            painter = QPainter(self.eraser_preview_image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(area.topLeft(), self.eraser_source_image, area)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            painter.setOpacity(opacity)
            painter.drawImage(area.topLeft(), self.eraser_mask, area)
            painter.end()
        self.eraser_item.setPixmap(QPixmap.fromImage(self.eraser_preview_image))

    def _reset_eraser_preview(self) -> None:
        self.eraser_item = None
        self.eraser_points = []
        self.eraser_preview_image = None
        self.eraser_source_image = None
        self.eraser_mask = None
        self.eraser_original_pixmap = None
        self.eraser_preview_last = None

    def cancel_eraser_preview(self) -> None:
        if self.eraser_item is not None and self.eraser_original_pixmap is not None:
            try:
                self.eraser_item.setPixmap(self.eraser_original_pixmap)
            except RuntimeError:
                pass
        self._reset_eraser_preview()

    def cancel_selection_drag(self) -> None:
        self.selection_drag = None
        self.lift = None
        self.viewport().update()

    def zoom_by(self, factor: float) -> None:
        """Zoom borné : le pas est raccourci au lieu d'être refusé près des limites."""
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if abs(target - current) > 1e-9:
            self.scale(target / current, target / current)
        self.main_window.update_zoom()

    def wheelEvent(self, event):
        self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def fit_document(self):
        if self.scene():
            region = QRectF(0, 0, self.main_window.document.width, self.main_window.document.height)
            self.fitInView(region, Qt.AspectRatioMode.KeepAspectRatio)
            current = self.transform().m11()
            clamped = max(MIN_ZOOM, min(MAX_ZOOM, current))
            if clamped != current:
                self.scale(clamped / current, clamped / current)
                self.centerOn(region.center())
            self.main_window.update_zoom()
