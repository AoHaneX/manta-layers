"""Colour picker working anywhere on the desktop, outside Manta Layers too.

When it starts, each screen is captured once and shown frozen in a frameless
full-screen window: the pointer can then hover any application, and a click
reads the pixel under it. The captures only live while picking and are
released as soon as a colour is chosen or the picking is cancelled; nothing
is ever saved or recorded.

Captures are made per screen in device pixels, so pointer positions are
scaled by the ratio between the capture and the screen geometry (Windows
display scaling, mixed-DPI multi-screen setups).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import COLORS

LOUPE_PIXELS = 9  # sampled square shown magnified next to the pointer
LOUPE_ZOOM = 10


def sample_color(capture: QImage, logical: QPointF, logical_size) -> QColor | None:
    """Colour of ``capture`` under a position given in screen (logical) coordinates.

    ``logical_size`` is the screen size in logical pixels; the capture may be
    larger on scaled displays. None outside the capture.
    """
    if capture.isNull() or logical_size.width() <= 0 or logical_size.height() <= 0:
        return None
    x = int(logical.x() * capture.width() / logical_size.width())
    y = int(logical.y() * capture.height() / logical_size.height())
    if not (0 <= x < capture.width() and 0 <= y < capture.height()):
        return None
    return QColor(capture.pixel(x, y))


class _ScreenOverlay(QWidget):
    """Frozen picture of one screen; forwards clicks and Escape to the picker."""

    def __init__(self, picker: ScreenColorPicker, geometry: QRect, capture: QImage):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.picker = picker
        self.capture = capture
        self.pointer: QPointF | None = None
        self.setGeometry(geometry)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def color_at(self, position: QPointF) -> QColor | None:
        return sample_color(self.capture, position, self.size())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(QRectF(self.rect()), self.capture)
        if self.pointer is not None:
            self._paint_loupe(painter, self.pointer)
        painter.end()

    def _paint_loupe(self, painter: QPainter, pointer: QPointF) -> None:
        color = self.color_at(pointer)
        if color is None:
            return
        size = LOUPE_PIXELS * LOUPE_ZOOM
        box = QRectF(pointer.x() + 18, pointer.y() + 18, size + 12, size + 40)
        if box.right() > self.width():
            box.moveRight(pointer.x() - 18)
        if box.bottom() > self.height():
            box.moveBottom(pointer.y() - 18)
        painter.setPen(QPen(QColor(COLORS["primary"]), 2))
        painter.setBrush(QColor(COLORS["panel"]))
        painter.drawRoundedRect(box, 8, 8)
        ratio_x = self.capture.width() / max(1, self.width())
        ratio_y = self.capture.height() / max(1, self.height())
        center = QPoint(int(pointer.x() * ratio_x), int(pointer.y() * ratio_y))
        half = LOUPE_PIXELS // 2
        source = QRect(center.x() - half, center.y() - half, LOUPE_PIXELS, LOUPE_PIXELS)
        target = QRectF(box.left() + 6, box.top() + 6, size, size)
        painter.drawImage(target, self.capture.copy(source))  # nearest neighbour: pixels stay sharp
        painter.setPen(QPen(QColor(COLORS["copper"]), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(target.left() + half * LOUPE_ZOOM, target.top() + half * LOUPE_ZOOM,
                                LOUPE_ZOOM, LOUPE_ZOOM))
        swatch = QRectF(box.left() + 6, target.bottom() + 6, 22, 22)
        painter.setPen(QPen(QColor(COLORS["muted"]), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(swatch, 4, 4)
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(QRectF(swatch.right() + 8, swatch.top(), size - 30, 22),
                         Qt.AlignmentFlag.AlignVCenter, color.name().upper())

    def mouseMoveEvent(self, event):
        self.pointer = event.position()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            color = self.color_at(event.position())
            if color is not None:
                self.picker.finish(color)
                return
        self.picker.cancel()  # right click, or a click that read nothing

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.picker.cancel()
        else:
            super().keyPressEvent(event)


class ScreenColorPicker(QObject):
    """One picking session: ``picked`` (hex colour), ``cancelled`` or ``failed`` (message)."""

    picked = Signal(str)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.overlays: list[_ScreenOverlay] = []

    @property
    def active(self) -> bool:
        return bool(self.overlays)

    def start(self) -> bool:
        """Capture every screen and show the overlays; False (with ``failed``) when nothing can be captured."""
        for screen in QGuiApplication.screens():
            capture = screen.grabWindow(0).toImage()
            if capture.isNull() or capture.width() == 0:
                continue  # protected or unavailable screen: it is simply not offered
            overlay = _ScreenOverlay(self, screen.geometry(), capture)
            self.overlays.append(overlay)
        if not self.overlays:
            self.failed.emit("Capture de l'écran impossible : Windows ou l'application affichée la refuse.")
            return False
        for overlay in self.overlays:
            overlay.show()
            overlay.raise_()
        self.overlays[0].activateWindow()
        self.overlays[0].setFocus()
        return True

    def _close(self) -> None:
        overlays, self.overlays = self.overlays, []
        for overlay in overlays:
            overlay.capture = QImage()  # free the capture at once
            overlay.close()

    def finish(self, color: QColor) -> None:
        self._close()
        self.picked.emit(color.name().upper())

    def cancel(self) -> None:
        if self.overlays:
            self._close()
            self.cancelled.emit()
