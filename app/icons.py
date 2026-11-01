"""Pictogrammes vectoriels de l'interface, indépendants des emojis installés."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import COLORS


def _blank_pixmap(size: int) -> QPixmap:
    """Transparent square drawn in logical pixels but stored at the screen density.

    Without a device pixel ratio, icons are upscaled and blurred at 150 % or 200 %
    display scaling. QPainter maps the logical coordinates used below automatically.
    """
    screen = QGuiApplication.primaryScreen()
    ratio = max(2.0, math.ceil(screen.devicePixelRatio())) if screen is not None else 2.0
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def lock_icon(locked: bool) -> QIcon:
    """Cadenas vectoriel lisible, indépendant des emojis installés."""
    pixmap = _blank_pixmap(18)
    painter = QPainter(pixmap)
    # Sur l'état verrouillé, le bouton est cyan : le cadenas doit donc rester
    # bleu nuit pour conserver un contraste net au lieu de disparaître dans le fond.
    color = QColor(COLORS["background"] if locked else COLORS["muted"])
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, 2))
    painter.setBrush(color if locked else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(3, 8, 12, 8), 2, 2)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(5, 2, 8, 11), 0, 180 * 16)
    painter.end()
    return QIcon(pixmap)


def eye_icon(visible: bool) -> QIcon:
    """Icône de visibilité lisible sur les deux états du bouton."""
    pixmap = _blank_pixmap(18)
    painter = QPainter(pixmap)
    color = QColor(COLORS["background"] if visible else COLORS["muted"])
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color, 1.8))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(2, 5, 14, 8))
    painter.setBrush(color)
    painter.drawEllipse(QRectF(7, 7, 4, 4))
    if not visible:
        painter.setPen(QPen(color, 2))
        painter.drawLine(3, 3, 15, 15)
    painter.end()
    return QIcon(pixmap)


def layer_kind_icon(kind: str) -> QPixmap:
    """Pictogramme stable pour différencier image et texte sans dépendre d'un emoji."""
    pixmap = _blank_pixmap(18)
    painter = QPainter(pixmap)
    color = QColor(COLORS["muted"])
    painter.setPen(QPen(color, 1.6))
    if kind == "text":
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 18, 18), Qt.AlignmentFlag.AlignCenter, "T")
    elif kind == "folder":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outline = QPainterPath(QPointF(2, 5))
        for x, y in ((7, 5), (8.5, 3.5), (16, 3.5), (16, 15), (2, 15)):
            outline.lineTo(x, y)
        outline.closeSubpath()
        painter.drawPath(outline)
        painter.drawLine(QPointF(2, 7), QPointF(16, 7))
    elif kind == "shape":
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawRect(QRectF(2, 7, 9, 9))
        painter.drawEllipse(QRectF(7, 2, 9, 9))
    else:
        painter.drawRoundedRect(QRectF(2, 3, 14, 12), 2, 2)
        painter.drawEllipse(QRectF(11, 5, 2, 2))
        painter.drawLine(4, 13, 8, 9)
        painter.drawLine(8, 9, 11, 12)
        painter.drawLine(11, 12, 14, 9)
    painter.end()
    return pixmap


def alignment_icon(alignment: str) -> QIcon:
    """Petite icône d'alignement indépendante de la police du système."""
    pixmap = _blank_pixmap(20)
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(COLORS["muted"]), 1.8))
    widths = (13, 9, 13, 7)
    for index, width in enumerate(widths):
        if alignment == "left":
            x = 3
        elif alignment == "right":
            x = 17 - width
        else:
            x = (20 - width) / 2
        y = 4 + index * 4
        painter.drawLine(QPointF(x, y), QPointF(x + width, y))
    painter.end()
    return QIcon(pixmap)


def sidebar_arrow_icon(points_right: bool) -> QIcon:
    """Flèche vectorielle nette pour la languette du panneau gauche."""
    pixmap = _blank_pixmap(18)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(COLORS["background"]), 2.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if points_right:
        painter.drawLine(QPointF(6, 3.5), QPointF(11.5, 9))
        painter.drawLine(QPointF(11.5, 9), QPointF(6, 14.5))
    else:
        painter.drawLine(QPointF(12, 3.5), QPointF(6.5, 9))
        painter.drawLine(QPointF(6.5, 9), QPointF(12, 14.5))
    painter.end()
    return QIcon(pixmap)


def history_arrow_icon(redo: bool) -> QIcon:
    """Flèche d'historique courbe et antialiasée."""
    pixmap = _blank_pixmap(24)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor(COLORS["muted"])
    pen = QPen(color, 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(5 if not redo else 19, 15))
    path.cubicTo(
        QPointF(7 if not redo else 17, 7),
        QPointF(15 if not redo else 9, 6),
        QPointF(19 if not redo else 5, 12),
    )
    painter.drawPath(path)
    painter.setBrush(color)
    if redo:
        arrow = QPainterPath(QPointF(19, 15))
        arrow.lineTo(QPointF(13.5, 14))
        arrow.lineTo(QPointF(17.5, 10))
    else:
        arrow = QPainterPath(QPointF(5, 15))
        arrow.lineTo(QPointF(10.5, 14))
        arrow.lineTo(QPointF(6.5, 10))
    arrow.closeSubpath()
    painter.drawPath(arrow)
    painter.end()
    return QIcon(pixmap)


def color_tool_icon(tool: str) -> QIcon:
    """Dessine les outils couleur sans dépendre des emojis du système."""
    pixmap = _blank_pixmap(20)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor(COLORS["muted"])
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if tool in ("select_rect", "select_ellipse"):
        pen = QPen(color, 1.6, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if tool == "select_rect":
            painter.drawRect(QRectF(3, 4, 14, 12))
        else:
            painter.drawEllipse(QRectF(3, 4, 14, 12))
    elif tool == "wand":
        painter.drawLine(4, 16, 13, 7)
        painter.setPen(QPen(color, 1.4))
        for x1, y1, x2, y2 in ((15, 2, 15, 6), (13, 4, 17, 4), (17, 9, 19, 9), (10, 2, 11, 3)):
            painter.drawLine(x1, y1, x2, y2)
    elif tool == "text":
        painter.drawLine(4, 4, 16, 4)
        painter.drawLine(10, 4, 10, 17)
        painter.drawLine(7, 17, 13, 17)
    elif tool == "picker":
        painter.drawLine(5, 15, 15, 5)
        painter.drawLine(4, 12, 8, 16)
        painter.drawEllipse(QRectF(13, 3, 4, 4))
    elif tool == "eraser":
        painter.save()
        painter.translate(10, 10)
        painter.rotate(-35)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(-6, -4, 12, 8), 2, 2)
        painter.setPen(QPen(QColor(COLORS["background"]), 1.4))
        painter.drawLine(1, -4, 1, 4)
        painter.restore()
    else:
        painter.save()
        painter.translate(9, 9)
        painter.rotate(-25)
        painter.drawRoundedRect(QRectF(-5, -5, 10, 11), 2, 2)
        painter.restore()
        painter.drawLine(5, 16, 15, 16)
        if tool == "bucket_global":
            painter.drawLine(15, 4, 19, 4)
            painter.drawLine(17, 2, 17, 6)
    painter.end()
    return QIcon(pixmap)
