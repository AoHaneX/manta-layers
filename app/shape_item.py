"""Vector shape layers: geometry and canvas item.

A shape is drawn in a ``shape_width`` × ``shape_height`` box whose top-left
corner is the layer position; scale, rotation and opacity are the usual layer
transforms. Nothing is rasterised: every property stays editable.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, pi, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem

from .model import Layer

SHAPE_TYPE_LABELS = {
    "rectangle": "Rectangle / carré",
    "ellipse": "Ellipse / cercle",
    "line": "Ligne",
    "arrow": "Flèche",
    "polygon": "Polygone",
    "speech": "Bulle de dialogue",
    "thought": "Bulle de pensée",
    "banner": "Bandeau",
}
# Open shapes are only drawn with their outline.
OPEN_SHAPES = frozenset({"line", "arrow"})


def _polygon(points) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    return path


def arrow_head_length(layer: Layer) -> float:
    return min(layer.shape_width * 0.6, max(layer.shape_height, layer.stroke_width * 3))


def shape_path(layer: Layer) -> QPainterPath:
    """Outline of the shape in item coordinates (the arrow head is a separate filled path)."""
    width, height = layer.shape_width, layer.shape_height
    kind = layer.shape_type
    path = QPainterPath()
    if kind == "rectangle":
        radius = min(layer.corner_radius, width / 2, height / 2)
        path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    elif kind == "ellipse":
        path.addEllipse(QRectF(0, 0, width, height))
    elif kind == "polygon":
        sides = layer.polygon_sides
        path = _polygon([(width / 2 + width / 2 * sin(2 * pi * index / sides),
                          height / 2 - height / 2 * cos(2 * pi * index / sides)) for index in range(sides)])
    elif kind == "line":
        path.moveTo(0, height / 2)
        path.lineTo(width, height / 2)
    elif kind == "arrow":
        path.moveTo(0, height / 2)
        path.lineTo(max(0.0, width - arrow_head_length(layer) * 0.8), height / 2)
    elif kind == "speech":
        body_height = height * 0.78
        radius = min(height * 0.2, width * 0.2)
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, width, body_height), radius, radius)
        tail = _polygon([(width * 0.22, body_height - 1), (width * 0.12, height), (width * 0.38, body_height - 1)])
        path = body.united(tail)
    elif kind == "thought":
        body = QPainterPath()
        body.addEllipse(QRectF(width * 0.08, 0, width * 0.92, height * 0.76))
        for cx, cy, r in ((0.2, 0.18, 0.17), (0.45, 0.06, 0.2), (0.75, 0.12, 0.18), (0.9, 0.42, 0.14),
                          (0.68, 0.66, 0.16), (0.36, 0.66, 0.17), (0.14, 0.48, 0.15)):
            lobe = QPainterPath()
            lobe.addEllipse(QPointF(width * cx, height * cy), width * r, height * r * 1.25)
            body = body.united(lobe)
        path = body
        for cx, cy, r in ((0.12, 0.86, 0.05), (0.04, 0.96, 0.03)):
            path.addEllipse(QPointF(width * cx, height * cy), width * r, width * r)
    elif kind == "banner":
        notch = min(width * 0.12, height * 0.6)
        path = _polygon([(0, 0), (width, 0), (width - notch, height / 2), (width, height), (0, height),
                         (notch, height / 2)])
    return path


DEFAULT_SHAPE_SIZE = (160.0, 110.0)
MIN_DRAG = 2.0  # below, a click creates a shape of the default size


def shape_from_drag(kind: str, start: tuple[float, float], end: tuple[float, float],
                    constrain: bool, color: str) -> Layer:
    """New shape layer drawn from ``start`` to ``end`` (document coordinates).

    Closed shapes fill the dragged box (a square box with ``constrain``), filled
    with ``color``. Lines and arrows go from ``start`` to ``end`` (multiples of
    45° with ``constrain``), drawn with ``color``.
    """
    (x0, y0), (x1, y1) = start, end
    layer = Layer(name=SHAPE_TYPE_LABELS.get(kind, "Forme").split(" /")[0], kind="shape", shape_type=kind)
    if kind in OPEN_SHAPES:
        length = hypot(x1 - x0, y1 - y0)
        angle = degrees(atan2(y1 - y0, x1 - x0)) if length >= MIN_DRAG else 0.0
        if constrain:
            angle = round(angle / 45) * 45
        layer.shape_width = max(length, MIN_DRAG) if length >= MIN_DRAG else DEFAULT_SHAPE_SIZE[0]
        layer.stroke_color, layer.stroke_width, layer.fill_color = color, 6.0, None
        layer.shape_height = 24.0 if kind == "arrow" else 12.0
        layer.rotation = angle
        # The start of the line, at mid-height of the box, stays under the press.
        half = layer.shape_height / 2
        layer.x, layer.y = x0 + sin(radians(angle)) * half, y0 - cos(radians(angle)) * half
    else:
        width, height = abs(x1 - x0), abs(y1 - y0)
        if width < MIN_DRAG and height < MIN_DRAG:
            width, height = DEFAULT_SHAPE_SIZE
            x0, y0 = x0 - width / 2, y0 - height / 2
            x1, y1 = x0 + width, y0 + height
        if constrain:
            width = height = max(width, height)
        layer.x = x0 if x1 >= x0 else x0 - width
        layer.y = y0 if y1 >= y0 else y0 - height
        layer.shape_width, layer.shape_height = max(width, MIN_DRAG), max(height, MIN_DRAG)
        layer.fill_color, layer.stroke_color, layer.stroke_width = color, "#000000", 0.0
    layer.normalize_shape_fields()
    return layer


def arrow_head_path(layer: Layer) -> QPainterPath:
    width, height = layer.shape_width, layer.shape_height
    head = arrow_head_length(layer)
    return _polygon([(width, height / 2), (width - head, height / 2 - head / 2), (width - head, height / 2 + head / 2)])


class ShapeGraphicItem(QGraphicsItem):
    """Canvas item of a shape layer, drawn with antialiasing from the model."""

    def __init__(self, layer: Layer):
        super().__init__()
        self.apply_layer(layer)

    def apply_layer(self, layer: Layer) -> None:
        self.prepareGeometryChange()
        self.kind = layer.shape_type
        self.path = shape_path(layer)
        self.head = arrow_head_path(layer) if self.kind == "arrow" else QPainterPath()
        self.fill = QColor(layer.fill_color) if layer.fill_color and self.kind not in OPEN_SHAPES else QColor()
        stroke = layer.stroke_color if layer.stroke_width > 0 else None
        self.pen = QPen(QColor(stroke), layer.stroke_width) if stroke else QPen(Qt.PenStyle.NoPen)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap if self.kind in OPEN_SHAPES else Qt.PenCapStyle.FlatCap)
        outline = self.path.united(self.head) if not self.head.isEmpty() else QPainterPath(self.path)
        if stroke:
            stroker = QPainterPathStroker()
            stroker.setWidth(layer.stroke_width)
            outline = outline.united(stroker.createStroke(outline))
        # Open shapes keep their whole box, so that handles stay usable on a thin line.
        box = QRectF(0, 0, layer.shape_width, layer.shape_height)
        self._bounds = outline.boundingRect().united(box)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def paint(self, painter: QPainter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self.pen)
        painter.setBrush(QBrush(self.fill) if self.fill.isValid() else Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path)
        if not self.head.isEmpty():
            color = self.pen.color() if self.pen.style() != Qt.PenStyle.NoPen else QColor()
            if color.isValid():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPath(self.head)
        painter.restore()
