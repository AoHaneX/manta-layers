"""Petits widgets réutilisés par la fenêtre principale."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QPlainTextEdit, QToolButton, QWidget

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
    """Poignée qui démarre le glissement d'une ligne de calque."""

    def __init__(self, layer_id: str, parent=None):
        super().__init__(parent)
        self.layer_id = layer_id
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
        mime.setData(LAYER_MIME_TYPE, self.layer_id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)
        self._press_position = None
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
        layer_id = bytes(event.mimeData().data(LAYER_MIME_TYPE)).decode("utf-8")
        target_item = self.itemAt(event.position().toPoint())
        if target_item is None:
            insertion = self.count()
        else:
            target_row = self.row(target_item)
            insertion = target_row + (
                event.position().y() > self.visualItemRect(target_item).center().y()
            )
        self.main_window.move_layer_to_display_position(layer_id, insertion)
        event.acceptProposedAction()


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
