"""Petits widgets réutilisés par la fenêtre principale."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QToolButton,
    QWidget,
)
from shiboken6 import isValid

if TYPE_CHECKING:
    from .window import MainWindow

LAYER_MIME_TYPE = "application/x-manta-layers-layer"


class CommitPlainTextEdit(QPlainTextEdit):
    """Zone multiligne qui valide une seule fois lorsque l'utilisateur la quitte."""

    editingFinished = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


class InlineTextEditor(QPlainTextEdit):
    """Editor floating over the canvas to type a text layer in place.

    Ctrl+Enter or leaving the editor validates; Escape cancels. Opening a menu
    (popup focus) does not count as leaving.
    """

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._finished = False
        self.setPlainText(text)
        self.setPlaceholderText("Saisissez le texte… (Ctrl+Entrée pour valider, Échap pour annuler)")
        self.setToolTip("Ctrl+Entrée pour valider · Échap pour annuler")
        cursor = self.textCursor()
        cursor.select(cursor.SelectionType.Document)
        self.setTextCursor(cursor)

    def finish(self, accept: bool) -> None:
        if self._finished:
            return
        self._finished = True
        if accept:
            self.committed.emit(self.toPlainText())
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.finish(False)
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.finish(True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.finish(True)


class LayerDragHandle(QToolButton):
    """Poignée qui démarre le glissement d'une ligne de calque (ou de dossier)."""

    def __init__(self, layer_id: str, parent=None, kind: str = "layer"):
        super().__init__(parent)
        self.layer_id = layer_id
        self.kind = kind
        self._press_position: QPoint | None = None
        self.setObjectName("layerDragHandle")
        self.setText("≡")
        self.setToolTip("Maintenir et glisser pour réordonner le calque")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedSize(24, 27)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_position is None or
                not event.buttons() & Qt.MouseButton.LeftButton or
                (event.position().toPoint() - self._press_position).manhattanLength() < QApplication.startDragDistance()):
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(LAYER_MIME_TYPE, f"{self.kind}:{self.layer_id}".encode("utf-8"))
        drag.setMimeData(mime)
        self._press_position = None
        drag.exec(Qt.DropAction.MoveAction)
        # The drop rebuilds the layer list, row widgets (this handle) included: on
        # platforms whose drag loop runs deferred deletions, the handle is gone.
        if isValid(self):
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        self._press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class LayerListWidget(QListWidget):
    """Liste recevant les calques déplacés depuis leur poignée."""

    def __init__(self, window: MainWindow):
        super().__init__()
        # Not named "window": that would hide QWidget.window().
        self.main_window = window
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(LAYER_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(LAYER_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(LAYER_MIME_TYPE):
            super().dropEvent(event)
            return
        payload = bytes(event.mimeData().data(LAYER_MIME_TYPE)).decode("utf-8")
        kind, _separator, item_id = payload.partition(":")
        if not item_id:  # payload of an older drag: a bare layer id
            kind, item_id = "layer", payload
        target_item = self.itemAt(event.position().toPoint())
        upper = target_item is not None and (
            event.position().y() <= self.visualItemRect(target_item).center().y()
        )
        self.main_window.drop_in_layer_list(kind, item_id, target_item, upper)
        event.acceptProposedAction()

    def contextMenuEvent(self, event):
        self.main_window.show_layer_context_menu(self.itemAt(event.pos()), event.globalPos())
        event.accept()


class OpacityControl(QWidget):
    """Layer opacity, 0 to 100 %: a slider and its value, kept in step.

    ``previewed`` follows every change, for an immediate display. ``committed``
    is emitted once a value is chosen: at the end of a slider drag, or for each
    step made with the keyboard, the wheel or a click on the track (the window
    groups those steps into one history entry).
    """

    previewed = Signal(int)
    committed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel("Opacité")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setPageStep(10)
        self.slider.setValue(100)
        self.slider.setToolTip("Opacité du calque sélectionné")
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setSuffix(" %")
        self.spin.setValue(100)
        self.spin.setKeyboardTracking(False)  # a typed value counts once validated
        self.spin.setToolTip("Opacité du calque sélectionné")
        label.setBuddy(self.slider)
        layout.addWidget(label)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.spin)
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(lambda: self.committed.emit(self.slider.value()))
        self.spin.valueChanged.connect(self._spin_changed)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, percent: int) -> None:
        """Show a layer's opacity, without emitting anything."""
        for widget in (self.slider, self.spin):
            widget.blockSignals(True)
            widget.setValue(percent)
            widget.blockSignals(False)

    def _slider_changed(self, percent: int) -> None:
        self.spin.blockSignals(True)
        self.spin.setValue(percent)
        self.spin.blockSignals(False)
        self.previewed.emit(percent)
        if not self.slider.isSliderDown():
            self.committed.emit(percent)  # keyboard, wheel or click on the track

    def _spin_changed(self, percent: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(percent)
        self.slider.blockSignals(False)
        self.previewed.emit(percent)
        self.committed.emit(percent)


class SidebarBackground(QWidget):
    """Fond du panneau gauche, recadré depuis le haut et la droite si nécessaire."""

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self._source = QPixmap(str(image_path))
        self._scaled = QPixmap()
        self._scaled_for = QSize()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._source.isNull():
            return
        if self._scaled_for != self.size():
            self._scaled = self._source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.FastTransformation,
            )
            self._scaled_for = self.size()
        painter = QPainter(self)
        # Ancrage bas-gauche : le sol marin reste visible en petit format.
        painter.drawPixmap(0, self.height() - self._scaled.height(), self._scaled)
