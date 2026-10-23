"""Canvas interactif et rendu sans les accessoires d'édition."""
from __future__ import annotations

from io import BytesIO
from math import atan2, cos, degrees, radians, sin
from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QImage, QKeySequence, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
)

from .model import Document, Layer


class TextGraphicItem(QGraphicsTextItem):
    """Texte éditable conservant un fond distinct de la couleur des caractères."""

    def __init__(self, text: str, background: str | None = None):
        super().__init__(text)
        self.background = QColor(background) if background else QColor()

    def paint(self, painter, option, widget=None):
        if self.background.isValid() and self.background.alpha() > 0:
            painter.fillRect(self.boundingRect(), self.background)
        super().paint(painter, option, widget)


class CurvedTextGraphicItem(QGraphicsItem):
    """Texte caractère par caractère sur une trajectoire, sans rasterisation."""

    def __init__(self, layer: Layer):
        super().__init__()
        self.text = layer.text.replace("\n", " ")
        self.font = QFont(layer.font_family, layer.font_size)
        self.color = QColor(layer.color)
        self.background = QColor(layer.text_background) if layer.text_background else QColor()
        self.curve_intensity = float(layer.curve_intensity)
        self.spacing = float(layer.character_spacing)
        self.alignment = layer.path_alignment
        self.orientation = layer.path_orientation
        self.flip_horizontal = bool(layer.flip_horizontal)
        self.flip_vertical = bool(layer.flip_vertical)
        self._rebuild_geometry()

    def _shape_value(self, t: float) -> float:
        # Dans les coordonnées Qt, une ordonnée négative monte : une valeur
        # positive produit donc un arc vers le haut, et une négative vers le bas.
        return -4.0 * t * (1.0 - t)

    def _rebuild_geometry(self):
        self.prepareGeometryChange()
        metrics = QFontMetricsF(self.font)
        advances = [metrics.horizontalAdvance(char) for char in self.text]
        positive_advances = [advance for advance in advances if advance > 0]
        minimum_advance = min(positive_advances, default=1.0)
        # L'espacement négatif peut rapprocher les lettres sans jamais faire
        # repartir le curseur en arrière ni inverser leur ordre.
        effective_spacing = max(self.spacing, -minimum_advance * 0.8)
        self.text_width = sum(advances) + max(0, len(advances) - 1) * effective_spacing
        self.max_amplitude = max(1.0, self.font.pointSizeF() * 2.0)
        self.amplitude = self.max_amplitude * self.curve_intensity / 100.0
        margin = max(4.0, self.font.pointSizeF())
        self.path_start_x = -margin
        self.path_width = max(1.0, self.text_width + margin * 2)
        # Géométrie stable pendant le glissement de la poignée : la ligne de
        # base et le cadre ne sautent pas quand l'intensité évolue.
        # La ligne droite reste au même emplacement que l'ancien texte droit.
        # La marge de courbure s'étend autour d'elle au lieu de décaler le texte.
        self.baseline = metrics.ascent() + 2
        self._bounds = QRectF(
            self.path_start_x, -self.max_amplitude, self.path_width,
            metrics.height() + self.max_amplitude * 2 + 4,
        )
        self.guide_path = QPainterPath(QPointF(self.path_start_x, self.baseline))
        samples = max(32, min(256, int(self.path_width / 4)))
        for index in range(1, samples + 1):
            t = index / samples
            self.guide_path.lineTo(
                self.path_start_x + self.path_width * t,
                self.baseline + self.amplitude * self._shape_value(t),
            )
        length = max(1.0, self.guide_path.length())
        spare = max(0.0, length - self.text_width)
        offset = 0.0 if self.alignment == "left" else spare if self.alignment == "right" else spare / 2
        self.placements = []
        cursor = offset
        for char, advance in zip(self.text, advances):
            center = cursor + advance / 2
            percent = self.guide_path.percentAtLength(max(0.0, min(length, center)))
            point = self.guide_path.pointAtPercent(percent)
            angle = -self.guide_path.angleAtPercent(percent) if self.orientation == "tangent" else 0.0
            self.placements.append((char, advance, point, angle))
            cursor += max(advance * 0.2, advance + effective_spacing)

    def boundingRect(self):
        return self._bounds

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        center = self._bounds.center()
        painter.save()
        painter.translate(center)
        painter.scale(-1 if self.flip_horizontal else 1, -1 if self.flip_vertical else 1)
        painter.translate(-center)
        if self.background.isValid() and self.background.alpha() > 0:
            painter.fillRect(self._bounds, self.background)
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
        center = self._bounds.center()
        transform = QTransform()
        transform.translate(center.x(), center.y())
        transform.scale(-1 if self.flip_horizontal else 1,
                        -1 if self.flip_vertical else 1)
        transform.translate(-center.x(), -center.y())
        return transform

    def visual_guide_path(self) -> QPainterPath:
        return self._visual_transform().map(self.guide_path)

    def set_curve_intensity(self, value: float):
        self.curve_intensity = max(-100.0, min(100.0, float(value)))
        self._rebuild_geometry()
        self.update()

    def curve_handle_local(self) -> QPointF:
        t = 0.5
        point = QPointF(
            self.path_start_x + self.path_width * t,
            self.baseline + self.amplitude * self._shape_value(t),
        )
        return self._visual_transform().map(point)

    def intensity_from_local(self, point: QPointF) -> float:
        inverse, invertible = self._visual_transform().inverted()
        if invertible:
            point = inverse.map(point)
        t = 0.5
        coefficient = self._shape_value(t)
        return max(-100.0, min(
            100.0,
            (point.y() - self.baseline) / (self.max_amplitude * coefficient) * 100,
        ))


def image_with_replacements(
    contents: bytes, replacements: dict[str, str], fills: list[dict] | None = None
) -> bytes:
    """Applique les remplacements au rendu sans modifier l'image source du projet."""
    fills = fills or []
    if not replacements and not fills:
        return contents
    with Image.open(BytesIO(contents)) as source:
        image = source.convert("RGBA")
    mapping = {tuple(QColor(old).getRgb()[:3]): tuple(QColor(new).getRgb()[:3])
               for old, new in replacements.items()
               if QColor(old).isValid() and QColor(new).isValid()}
    for source_rgb, target_rgb in mapping.items():
        image = _apply_color_fill(image, source_rgb, target_rgb, 0, "global", None, False)
    for fill in fills:
        source = QColor(str(fill.get("source", "")))
        target_color = QColor(str(fill.get("target", "")))
        if not source.isValid() or not target_color.isValid():
            continue
        source_rgb = source.getRgb()[:3]
        target_rgb = target_color.getRgb()[:3]
        tolerance = max(0, min(255, int(fill.get("tolerance", 0))))
        mode = "global" if fill.get("mode") == "global" else "contiguous"
        seed = (int(fill.get("x", -1)), int(fill.get("y", -1)))
        image = _apply_color_fill(
            image, source_rgb, target_rgb, tolerance, mode, seed,
            bool(fill.get("preserve_shading", False)),
        )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


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


def _eraser_dab(size: int, shape: str, pixel_art: bool, hardness: int, opacity: int) -> Image.Image:
    """Crée une empreinte sans anticrénelage en pixel art, douce en mode classique."""
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
        for x, y in _interpolated_points(points, spacing):
            left, top = round(x - offset), round(y - offset)
            coverage.paste(ImageChops.screen(coverage.crop((
                left, top, left + size, top + size
            )), dab), (left, top))
        inverse = ImageChops.invert(coverage)
        alpha = ImageChops.multiply(alpha, inverse)
    result.putalpha(alpha)
    return result


def create_graphic(layer: Layer, document: Document) -> QGraphicsItem:
    if layer.kind == "image":
        pixmap = QPixmap()
        rendered = image_with_replacements(
            document.assets[layer.asset], layer.color_replacements, layer.color_fills
        )
        if layer.eraser_strokes:
            with Image.open(BytesIO(rendered)) as rendered_source:
                erased = apply_eraser_strokes(rendered_source.convert("RGBA"), layer.eraser_strokes)
            output = BytesIO()
            erased.save(output, format="PNG")
            rendered = output.getvalue()
        if not pixmap.loadFromData(rendered):
            raise ValueError(f"Image illisible pour le calque {layer.name}")
        if layer.flip_horizontal or layer.flip_vertical:
            pixmap = pixmap.transformed(QTransform().scale(
                -1 if layer.flip_horizontal else 1,
                -1 if layer.flip_vertical else 1,
            ))
        item = QGraphicsPixmapItem(pixmap)
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


class CanvasView(QGraphicsView):
    """Sélection, déplacement à la souris, quatre poignées et rotation."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan_last = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#071221"))
        self.mode = None
        self.old_layer = None
        self.drag_item = None
        self.drag_start = None
        self.fixed_world = None
        self.fixed_local = None
        self.corner_local = None
        self.angle_offset = 0
        self.fixed_center = None
        self.eraser_item = None
        self.eraser_points: list[QPointF] = []
        self.eraser_cursor_local: QPointF | None = None
        self.eraser_preview_image: QImage | None = None
        self.eraser_original_pixmap: QPixmap | None = None
        self.eraser_preview_last: QPointF | None = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self.scene():
            return
        region = QRectF(0, 0, self.window.document.width, self.window.document.height)
        painter.save()
        painter.setClipRect(region)
        background = self.window.document.background
        if background:
            painter.fillRect(region, QColor(background))
        else:
            tile = 18
            start_x = max(0, int(rect.left() // tile) * tile)
            start_y = max(0, int(rect.top() // tile) * tile)
            for y in range(start_y, min(int(rect.bottom()) + tile, self.window.document.height), tile):
                for x in range(start_x, min(int(rect.right()) + tile, self.window.document.width), tile):
                    color = "#DDE4EC" if (x // tile + y // tile) % 2 else "#F9FCFF"
                    painter.fillRect(QRectF(x, y, tile, tile), QColor(color))
        painter.restore()

    def selected_graphic(self):
        for item in self.scene().selectedItems() if self.scene() else []:
            if self.window.document.layer(item.data(0)):
                return item
        return None

    def local_handles(self, item):
        bounds = item.boundingRect()
        x, y, w, h = bounds.x(), bounds.y(), bounds.width(), bounds.height()
        return [QPointF(x, y), QPointF(x + w, y), QPointF(x + w, y + h), QPointF(x, y + h)]

    def rotation_point(self, item):
        b = item.boundingRect()
        return item.mapToScene(QPointF(b.center().x(), b.top() - 35))

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if not self.scene():
            return
        painter.save()
        border_pen = QPen(QColor("#4A6883"), 1)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0, 0, self.window.document.width, self.window.document.height))
        item = self.selected_graphic()
        layer = self.window.document.layer(item.data(0)) if item else None
        if isinstance(item, CurvedTextGraphicItem) and layer:
            if layer.show_curve_guide:
                guide_pen = QPen(QColor("#4DD6E7"), 1)
                guide_pen.setCosmetic(True)
                guide_pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(guide_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(item.sceneTransform().map(item.visual_guide_path()))
            handle = item.mapToScene(item.curve_handle_local())
            factor = max(0.08, self.transform().m11())
            radius = 7 / factor
            painter.setPen(QPen(QColor("#00192D"), 1 / factor))
            painter.setBrush(QColor("#4DD6E7"))
            painter.drawEllipse(handle, radius, radius)
        if item and not self.window.eraser_active:
            factor = max(0.08, self.transform().m11())
            size = 9 / factor
            painter.setBrush(QColor("#36D7FF"))
            painter.setPen(QPen(QColor("#03182C"), 1 / factor))
            for local in self.local_handles(item):
                p = item.mapToScene(local)
                painter.drawRect(QRectF(p.x() - size/2, p.y() - size/2, size, size))
            p = self.rotation_point(item)
            painter.setBrush(QColor("#FFD86B"))
            painter.drawEllipse(p, size/2, size/2)
        if self.window.eraser_active and item and isinstance(item, QGraphicsPixmapItem):
            local = self.eraser_cursor_local
            if local is not None:
                size = self.window.eraser_size.value()
                offset = (size - 1) / 2
                path = QPainterPath()
                if self.window.eraser_pixel_art.isChecked():
                    left, top = round(local.x() - offset), round(local.y() - offset)
                    bounds = QRectF(left, top, size, size)
                else:
                    bounds = QRectF(local.x() - offset, local.y() - offset, size, size)
                if self.window.eraser_shape.currentData() == "square" and self.window.eraser_pixel_art.isChecked():
                    path.addRect(bounds)
                else:
                    path.addEllipse(bounds)
                scene_path = item.sceneTransform().map(path)
                preview_pen = QPen(QColor("#4DD6E7"), 1)
                preview_pen.setCosmetic(True)
                painter.setPen(preview_pen)
                painter.setBrush(QColor(77, 214, 231, 45))
                painter.drawPath(scene_path)
            if len(self.eraser_points) > 1:
                path = QPainterPath(self.eraser_points[0])
                for point in self.eraser_points[1:]:
                    path.lineTo(point)
                scene_path = item.sceneTransform().map(path)
                stroke_pen = QPen(QColor(77, 214, 231, 150), 2)
                stroke_pen.setCosmetic(True)
                painter.setPen(stroke_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(scene_path)
        painter.restore()

    def _hit_handle(self, item, viewport_pos):
        if isinstance(item, CurvedTextGraphicItem):
            curve_handle = item.mapToScene(item.curve_handle_local())
            if (self.mapFromScene(curve_handle) - viewport_pos).manhattanLength() <= 15:
                return "curve", None
        targets = [("resize", i, item.mapToScene(pt)) for i, pt in enumerate(self.local_handles(item))]
        targets.append(("rotate", None, self.rotation_point(item)))
        for mode, index, world in targets:
            if (self.mapFromScene(world) - viewport_pos).manhattanLength() <= 13:
                return mode, index
        return None, None

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window.eraser_active:
                item = self.selected_graphic()
                layer = self.window.document.layer(item.data(0)) if item else None
                if not item or not isinstance(item, QGraphicsPixmapItem) or not layer:
                    self.window.statusBar().showMessage(
                        "La gomme nécessite un calque image sélectionné", 3000
                    )
                    event.accept()
                    return
                if layer.locked:
                    self.window.statusBar().showMessage(
                        "Déverrouillez le calque pour utiliser la gomme", 3000
                    )
                    event.accept()
                    return
                local = item.mapFromScene(self.mapToScene(event.position().toPoint()))
                if not item.boundingRect().contains(local):
                    event.accept()
                    return
                self.eraser_item = item
                self.eraser_original_pixmap = item.pixmap()
                self.eraser_preview_image = item.pixmap().toImage().convertToFormat(
                    QImage.Format.Format_ARGB32
                )
                if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        and self.window.last_eraser_point
                        and self.window.last_eraser_layer_id == layer.id):
                    self.eraser_points = [QPointF(*self.window.last_eraser_point), local]
                else:
                    self.eraser_points = [local]
                start = self.eraser_points[0]
                self._apply_eraser_preview_segment(start, local)
                self.eraser_preview_last = local
                self.eraser_cursor_local = local
                self.viewport().update()
                event.accept()
                return
            if self.window.picker_active:
                item = self.itemAt(event.position().toPoint())
                if item and self.window.sample_canvas_color(item, self.mapToScene(event.position().toPoint())):
                    event.accept()
                    return
            if self.window.paint_mode:
                item = self.itemAt(event.position().toPoint())
                if item and self.window.paint_canvas_color(item, self.mapToScene(event.position().toPoint())):
                    event.accept()
                    return
            item = self.selected_graphic()
            layer = self.window.document.layer(item.data(0)) if item else None
            if item and layer and not layer.locked:
                mode, handle = self._hit_handle(item, event.position().toPoint())
                if mode:
                    self.mode = mode
                    self.old_layer = self.window.document.clone()
                    self.drag_item = item
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
            at_layer = self.window.document.layer(at.data(0)) if at else None
            if at_layer and not at_layer.locked:
                self.mode = "move"
                self.old_layer = self.window.document.clone()
                self.drag_item = at
        super().mousePressEvent(event)
        self.viewport().update()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.window.copy_layer()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Cut):
            self.window.cut_layer()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.window.paste_image()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.window.delete_layer()
            event.accept()
            return
        if event.key() == Qt.Key.Key_BracketLeft:
            self.window.adjust_eraser_size(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_BracketRight:
            self.window.adjust_eraser_size(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item and self.window.document.layer(item.data(0)):
            self.window.select_layer(item.data(0))
        self.window.show_canvas_context_menu(event.globalPos())
        event.accept()

    def dragEnterEvent(self, event):
        if self.window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.window.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.window.image_paths_from_mime(event.mimeData())
        if paths:
            self.window._import_paths(paths)
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
        if self.window.eraser_active:
            item = self.eraser_item or self.selected_graphic()
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
        if self.mode in ("resize", "rotate", "curve") and self.drag_item:
            item = self.drag_item
            old = self.old_layer.layer(item.data(0))
            mouse = self.mapToScene(event.position().toPoint())
            if self.mode == "curve" and isinstance(item, CurvedTextGraphicItem):
                local = item.mapFromScene(mouse)
                intensity = item.intensity_from_local(local)
                item.set_curve_intensity(intensity)
                self.window.curve_intensity.blockSignals(True)
                self.window.curve_intensity.setValue(round(intensity))
                self.window.curve_intensity.blockSignals(False)
                self.window.curve_value.blockSignals(True)
                self.window.curve_value.setValue(round(intensity))
                self.window.curve_value.blockSignals(False)
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
        if (event.button() == Qt.MouseButton.LeftButton and self.window.eraser_active
                and self.eraser_item and self.eraser_points):
            layer_id = self.eraser_item.data(0)
            self.window.commit_eraser_stroke(layer_id, self.eraser_points)
            last = self.eraser_points[-1]
            self.window.last_eraser_point = (last.x(), last.y())
            self.window.last_eraser_layer_id = layer_id
            self.eraser_item = None
            self.eraser_points = []
            self.eraser_preview_image = None
            self.eraser_original_pixmap = None
            self.eraser_preview_last = None
            self.viewport().update()
            event.accept()
            return
        mode, item, before = self.mode, self.drag_item, self.old_layer
        if mode == "curve" and item and before and isinstance(item, CurvedTextGraphicItem):
            self.window.commit_curve_handle(before, item.data(0), item.curve_intensity)
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
                    self.window.commit_canvas_transform(before, src.id, state,
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
        painter = QPainter(self.eraser_preview_image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        pixel_art = self.window.eraser_pixel_art.isChecked()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, not pixel_art)
        size = self.window.eraser_size.value()
        opacity = self.window.eraser_opacity.value() / 100
        dx, dy = end.x() - start.x(), end.y() - start.y()
        distance = (dx * dx + dy * dy) ** 0.5
        spacing = 0.5 if pixel_art else max(0.5, size * 0.2)
        steps = max(1, int(distance / spacing) + 1)
        offset = (size - 1) / 2
        for index in range(steps + 1):
            ratio = index / steps
            x, y = start.x() + dx * ratio, start.y() + dy * ratio
            if pixel_art:
                bounds = QRectF(round(x - offset), round(y - offset), size, size)
                painter.setBrush(QColor(0, 0, 0, round(255 * opacity)))
                painter.setPen(Qt.PenStyle.NoPen)
                if self.window.eraser_shape.currentData() == "square":
                    painter.drawRect(bounds)
                else:
                    painter.drawEllipse(bounds)
            else:
                radius = size / 2
                gradient = QRadialGradient(QPointF(x, y), radius)
                strength = round(255 * opacity)
                hardness = self.window.eraser_hardness.value() / 100
                gradient.setColorAt(0, QColor(0, 0, 0, strength))
                gradient.setColorAt(hardness, QColor(0, 0, 0, strength))
                gradient.setColorAt(1, QColor(0, 0, 0, 0))
                painter.setBrush(QBrush(gradient))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QRectF(x - radius, y - radius, size, size))
        painter.end()
        self.eraser_item.setPixmap(QPixmap.fromImage(self.eraser_preview_image))

    def cancel_eraser_preview(self) -> None:
        if self.eraser_item is not None and self.eraser_original_pixmap is not None:
            try:
                self.eraser_item.setPixmap(self.eraser_original_pixmap)
            except RuntimeError:
                pass
        self.eraser_item = None
        self.eraser_points = []
        self.eraser_preview_image = None
        self.eraser_original_pixmap = None
        self.eraser_preview_last = None

    def wheelEvent(self, event):
        zoom = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = self.transform().m11()
        if 0.08 <= current * zoom <= 8:
            self.scale(zoom, zoom)
            self.window.update_zoom()
        event.accept()

    def fit_document(self):
        if self.scene():
            self.fitInView(QRectF(0,0,self.window.document.width,self.window.document.height), Qt.AspectRatioMode.KeepAspectRatio)
            self.window.update_zoom()
