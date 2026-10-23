"""Fenêtre principale de Manta Layers, éditeur simple à calques pour Windows."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from shutil import copy2

from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QSize, QRectF, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QFontDatabase, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFontComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLayout, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QSpinBox, QSplitter, QGraphicsPixmapItem, QTabWidget, QToolButton,
    QUndoView, QVBoxLayout, QWidget, QLineEdit, QPlainTextEdit,
)

from .graphics import CanvasView, make_scene, qimage_png, render_document
from .model import Document
from .storage import open_project, save_project
from .theme import COLORS, STYLE

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
FONTS_DIR = ROOT / "fonts"


class CommitPlainTextEdit(QPlainTextEdit):
    """Zone multiligne qui valide une seule fois lorsque l'utilisateur la quitte."""

    editingFinished = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()


def lock_icon(locked: bool) -> QIcon:
    """Cadenas vectoriel lisible, indépendant des emojis installés."""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    # Sur l'état verrouillé, le bouton est cyan : le cadenas doit donc rester
    # bleu nuit pour conserver un contraste net au lieu de disparaître dans le fond.
    color = QColor("#00192D" if locked else "#ACC9D4")
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
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    color = QColor("#00192D" if visible else "#ACC9D4")
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
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    color = QColor("#ACC9D4")
    painter.setPen(QPen(color, 1.6))
    if kind == "text":
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(15)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")
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
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor("#ACC9D4"), 1.8))
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
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#001219"), 2.6)
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
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#ACC9D4"), 2.2)
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
    painter.setBrush(QColor("#ACC9D4"))
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
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    color = QColor("#ACC9D4")
    painter.setPen(QPen(color, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if tool == "picker":
        painter.drawLine(5, 15, 15, 5)
        painter.drawLine(4, 12, 8, 16)
        painter.drawEllipse(QRectF(13, 3, 4, 4))
    elif tool == "eraser":
        painter.save()
        painter.translate(10, 10)
        painter.rotate(-35)
        painter.setBrush(QColor("#ACC9D4"))
        painter.drawRoundedRect(QRectF(-6, -4, 12, 8), 2, 2)
        painter.setPen(QPen(QColor("#00192D"), 1.4))
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


LAYER_MIME_TYPE = "application/x-manta-layers-layer"


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

    def __init__(self, window):
        super().__init__()
        self.window = window
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
            insertion = target_row + (event.position().y() > self.visualItemRect(target_item).center().y())
        self.window.move_layer_to_display_position(layer_id, insertion)
        event.acceptProposedAction()

class DocumentCommand(QUndoCommand):
    def __init__(self, win: "MainWindow", before: Document, after: Document,
                 description: str, selected_before: str | None, selected_after: str | None):
        super().__init__(description)
        self.win = win
        self.before = before
        self.after = after
        self.selected_before = selected_before
        self.selected_after = selected_after

    def undo(self):
        self.win.install_document(self.before.clone(), self.selected_before)

    def redo(self):
        self.win.install_document(self.after.clone(), self.selected_after)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.project_path: Path | None = None
        self.selected_id: str | None = None
        self.refreshing = False
        self.picker_active = False
        self.picker_target = "tools"
        self.picker_text_layer_id: str | None = None
        self.paint_mode: str | None = None
        self.eraser_active = False
        self.last_eraser_point: tuple[float, float] | None = None
        self.last_eraser_layer_id: str | None = None
        self.sampled_color: str | None = None
        self.replacement_color = "#4DD6E7"
        self._updating_color_fields = False
        self.variation_colors: list[str] = []
        self.left_sidebar_expanded = True
        self.left_sidebar_width = 190
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.custom_font_ids: list[int] = []
        self.load_custom_fonts()
        self.setWindowIcon(QIcon(str(ASSETS / "manta.png")))
        self.setAcceptDrops(True)
        self.setMinimumSize(1060, 680)
        self.resize(1440, 870)
        self.setStyleSheet(STYLE)
        self._build_layout()
        self._build_actions()
        self.undo_stack.indexChanged.connect(self.update_title)
        self.undo_stack.cleanChanged.connect(self.update_title)
        self._load_demo()

    def load_custom_fonts(self):
        """Charge les polices conservées dans le répertoire local de l'application."""
        try:
            FONTS_DIR.mkdir(exist_ok=True)
            for path in sorted(FONTS_DIR.iterdir()):
                if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                    font_id = QFontDatabase.addApplicationFont(str(path))
                    if font_id >= 0:
                        self.custom_font_ids.append(font_id)
        except OSError:
            pass

    def import_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des polices", "", "Polices (*.ttf *.otf *.ttc);;Tous les fichiers (*)"
        )
        if not paths:
            return
        imported = []
        FONTS_DIR.mkdir(exist_ok=True)
        for raw_path in paths:
            source = Path(raw_path)
            if source.suffix.lower() not in FONT_SUFFIXES:
                continue
            destination = FONTS_DIR / source.name
            if destination.exists():
                answer = QMessageBox.question(
                    self, "Police déjà présente",
                    f"Remplacer la police {source.name} ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    continue
            try:
                copy2(source, destination)
                font_id = QFontDatabase.addApplicationFont(str(destination))
                if font_id < 0:
                    raise ValueError("format de police non pris en charge")
                self.custom_font_ids.append(font_id)
                imported.extend(QFontDatabase.applicationFontFamilies(font_id))
            except Exception as exc:
                QMessageBox.warning(self, "Import de police impossible", f"{source.name}\n{exc}")
        if imported:
            self.statusBar().showMessage(
                "Police(s) ajoutée(s) : " + ", ".join(dict.fromkeys(imported)), 6000
            )

    def update_properties_panel_visibility(self, tab_index: int):
        visible = tab_index == 0
        self.properties_label.setVisible(visible)
        self.properties_panel.setVisible(visible)
        if hasattr(self, "tools_tab") and tab_index != self.tabs.indexOf(self.tools_tab):
            self.deactivate_active_tools()
        self._schedule_right_panel_layout()

    def deactivate_active_tools(self):
        """Quitter l'onglet Outils rend toujours le canvas neutre."""
        if not (self.eraser_active or self.picker_active or self.paint_mode is not None):
            return

        self.canvas.cancel_eraser_preview()
        self.eraser_active = False
        self.picker_active = False
        self.picker_text_layer_id = None
        self.paint_mode = None

        for button in (
            self.eraser_btn, self.picker_btn, self.text_picker_btn,
            self.text_background_picker_btn, self.paint_bucket_btn,
            self.paint_global_btn,
        ):
            button.setChecked(False)
        if hasattr(self, "eraser_action"):
            self.eraser_action.setChecked(False)

        self.canvas.eraser_item = None
        self.canvas.eraser_points = []
        self.canvas.eraser_cursor_local = None
        self.update_tool_options_visibility()
        self._refresh_color_tool_cursor()
        self.canvas.viewport().update()

    def _schedule_right_panel_layout(self):
        """Recalcule la hauteur naturelle du panneau sans bloquer l'interface."""
        if hasattr(self, "right_content") and hasattr(self, "property_form"):
            QTimer.singleShot(0, self._update_right_panel_layout)

    def _update_right_panel_layout(self):
        """Empêche les contrôles de se comprimer : le panneau externe défile à la place."""
        if not hasattr(self, "right_content"):
            return

        self.property_form.invalidate()
        self.property_form.activate()
        property_height = max(1, self.property_form.sizeHint().height() + 4)
        self.properties_panel.setFixedHeight(property_height)

        current_tab = self.tabs.currentWidget()
        if current_tab is not None and current_tab.layout() is not None:
            current_tab.layout().invalidate()
            current_tab.layout().activate()
        tab_content_height = current_tab.sizeHint().height() if current_tab is not None else 0
        tab_height = max(365, tab_content_height + self.tabs.tabBar().sizeHint().height() + 18)
        self.tabs.setFixedHeight(tab_height)

        self.right_content.layout().invalidate()
        self.right_content.layout().activate()
        self.right_content.adjustSize()
        self.right_content.updateGeometry()

    def _build_layout(self):
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.main_splitter = splitter
        self.setCentralWidget(splitter)

        left = QWidget()
        self.left_panel = left
        left.setObjectName("sidePanel")
        left.setMinimumWidth(155)
        left.setMaximumWidth(225)
        left_layout = QVBoxLayout(left)
        self.left_layout = left_layout
        left_layout.setSpacing(9)
        self.left_collapsible_widgets = []
        self.left_toggle = QPushButton()
        self.left_toggle.setObjectName("sidebarToggle")
        self.left_toggle.setIcon(sidebar_arrow_icon(False))
        self.left_toggle.setIconSize(QSize(18, 18))
        self.left_toggle.setToolTip("Replier le panneau d'utilitaires")
        self.left_toggle.clicked.connect(self.toggle_left_sidebar)
        logo = QLabel()
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(QPixmap(str(ASSETS / "manta.png")).scaled(
            190, 124, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        left_layout.addWidget(logo)
        self.left_collapsible_widgets.append(logo)
        title = QLabel("MANTA LAYERS")
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title)
        self.left_collapsible_widgets.append(title)
        subtitle = QLabel("Éditeur d'images à calques\nBlue Shrimp · ReefKit")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        left_layout.addWidget(subtitle)
        self.left_collapsible_widgets.append(subtitle)
        self.doc_info = QPushButton()
        self.doc_info.setObjectName("docInfo")
        self.doc_info.setToolTip("Modifier les dimensions finales du document")
        self.doc_info.clicked.connect(self.resize_document)
        left_layout.addWidget(self.doc_info)
        self.left_collapsible_widgets.append(self.doc_info)
        left_layout.addSpacing(17)
        tools_label = QLabel("UTILITAIRES")
        tools_label.setObjectName("sectionTitle")
        left_layout.addWidget(tools_label)
        self.left_collapsible_widgets.append(tools_label)
        self.utility_buttons = {}
        for key, text, method in [
            ("import", "+ Importer des images", self.add_images),
            ("add_text", "T  Ajouter du texte", self.add_text),
            ("duplicate", "⧉ Dupliquer le calque", self.duplicate_layer),
            ("flip_horizontal", "⇆ Retourner horizontalement", self.flip_layer_horizontal),
            ("flip_vertical", "⇅ Retourner verticalement", self.flip_layer_vertical),
            ("lock", "▣ Verrouiller le calque", self.toggle_lock),
            ("delete", "× Supprimer le calque", self.delete_layer),
            ("fit", "▣ Cadrer le document", lambda: self.canvas.fit_document()),
        ]:
            btn = QPushButton(text)
            if text.startswith("+ Importer"):
                btn.setProperty("variant", "primary")
            elif text.startswith("× Supprimer"):
                btn.setProperty("variant", "danger")
            btn.clicked.connect(method)
            left_layout.addWidget(btn)
            self.utility_buttons[key] = btn
            self.left_collapsible_widgets.append(btn)
        self.update_utility_buttons()
        left_layout.addStretch(1)

        history_controls = QWidget()
        history_layout = QHBoxLayout(history_controls)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(7)
        self.left_undo_btn = QToolButton()
        self.left_undo_btn.setObjectName("leftHistoryButton")
        self.left_undo_btn.setIcon(history_arrow_icon(False))
        self.left_undo_btn.setIconSize(QSize(24, 24))
        self.left_undo_btn.setToolTip("Annuler · Ctrl+Z")
        self.left_undo_btn.setEnabled(self.undo_stack.canUndo())
        self.left_undo_btn.clicked.connect(self.undo_stack.undo)
        self.undo_stack.canUndoChanged.connect(self.left_undo_btn.setEnabled)
        self.left_redo_btn = QToolButton()
        self.left_redo_btn.setObjectName("leftHistoryButton")
        self.left_redo_btn.setIcon(history_arrow_icon(True))
        self.left_redo_btn.setIconSize(QSize(24, 24))
        self.left_redo_btn.setToolTip("Rétablir · Ctrl+Y")
        self.left_redo_btn.setEnabled(self.undo_stack.canRedo())
        self.left_redo_btn.clicked.connect(self.undo_stack.redo)
        self.undo_stack.canRedoChanged.connect(self.left_redo_btn.setEnabled)
        history_layout.addWidget(self.left_undo_btn)
        history_layout.addWidget(self.left_redo_btn)
        left_layout.addWidget(history_controls)
        self.left_collapsible_widgets.append(history_controls)

        new_project_btn = QPushButton("Nouveau projet")
        new_project_btn.clicked.connect(self.new_document)
        left_layout.addWidget(new_project_btn)
        self.left_collapsible_widgets.append(new_project_btn)
        save_project_btn = QPushButton("Sauvegarder le projet")
        save_project_btn.clicked.connect(self.save_document)
        left_layout.addWidget(save_project_btn)
        self.left_collapsible_widgets.append(save_project_btn)
        save_image_btn = QPushButton("Sauvegarder l'image")
        save_image_btn.setProperty("variant", "primary")
        save_image_btn.clicked.connect(self.export_image)
        left_layout.addWidget(save_image_btn)
        self.left_collapsible_widgets.append(save_image_btn)
        splitter.addWidget(left)

        self.canvas = CanvasView(self)
        self.left_toggle.setParent(self.canvas.viewport())
        self.left_toggle.setFixedSize(27, 34)
        self.left_toggle.move(5, 8)
        self.left_toggle.raise_()
        splitter.addWidget(self.canvas)

        right = QWidget()
        right.setObjectName("sidePanel")
        right.setMinimumWidth(270)
        right.setMaximumWidth(405)
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll = QScrollArea()
        right_scroll.setObjectName("rightPanelScroll")
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.right_scroll = right_scroll
        right_content = QWidget()
        right_content.setObjectName("sidePanel")
        right_content.setMinimumWidth(245)
        self.right_content = right_content
        right_content_layout = QVBoxLayout(right_content)
        right_content_layout.setContentsMargins(10, 10, 10, 10)
        right_content_layout.setSpacing(8)
        right_content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(365)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.layer_list = LayerListWidget(self)
        self.layer_list.setMinimumHeight(170)
        self.layer_list.currentItemChanged.connect(self.on_layer_list_select)
        self.tabs.addTab(self.layer_list, "Calques")
        self.history = QUndoView(self.undo_stack)
        self.history.setEmptyLabel("Document initial")
        self.tabs.addTab(self.history, "Historique")
        tools = QWidget()
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(10, 12, 10, 12)
        add_text_tool = QPushButton("T  Ajouter un calque texte")
        add_text_tool.clicked.connect(self.add_text)
        tools_layout.addWidget(add_text_tool)
        self.color_tools_label = QLabel("Couleur")
        tools_layout.addWidget(self.color_tools_label)
        color_editor = QWidget()
        color_editor.setObjectName("colorEditor")
        self.color_editor = color_editor
        color_layout = QHBoxLayout(color_editor)
        color_layout.setContentsMargins(8, 8, 8, 8)
        color_layout.setSpacing(10)
        self.color_preview = QPushButton()
        self.color_preview.setFixedSize(54, 76)
        self.color_preview.setToolTip("Cliquer pour choisir une couleur")
        self.color_preview.clicked.connect(self.choose_replacement_color)
        preview_column = QWidget()
        preview_layout = QVBoxLayout(preview_column)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(5)
        preview_layout.addWidget(self.color_preview)
        self.picker_btn = QToolButton()
        self.picker_btn.setObjectName("colorTool")
        self.picker_btn.setCheckable(True)
        self.picker_btn.setIcon(color_tool_icon("picker"))
        self.picker_btn.setIconSize(QSize(20, 20))
        self.picker_btn.setToolTip("Prélever une couleur sur le canvas")
        self.picker_btn.clicked.connect(
            lambda checked: self.activate_picker("tools", checked)
        )
        preview_layout.addWidget(self.picker_btn)
        color_layout.addWidget(preview_column)
        color_fields = QWidget()
        color_fields_layout = QFormLayout(color_fields)
        color_fields_layout.setContentsMargins(0, 0, 0, 0)
        color_fields_layout.setSpacing(5)
        self.sampled_color_input = QLineEdit()
        self.sampled_rgb_input = QLineEdit()
        self.sampled_hsl_input = QLineEdit()
        self.sampled_color_input.setPlaceholderText("#4DD6E7")
        self.sampled_rgb_input.setPlaceholderText("77, 214, 231")
        self.sampled_hsl_input.setPlaceholderText("187, 76 %, 60 %")
        self.sampled_color_input.textChanged.connect(self.update_color_from_hex)
        self.sampled_rgb_input.textChanged.connect(self.update_color_from_rgb)
        self.sampled_hsl_input.textChanged.connect(self.update_color_from_hsl)
        color_fields_layout.addRow("HEX", self.sampled_color_input)
        color_fields_layout.addRow("RVB", self.sampled_rgb_input)
        color_fields_layout.addRow("HSL", self.sampled_hsl_input)
        color_layout.addWidget(color_fields, stretch=1)
        tools_layout.addWidget(color_editor)
        paint_tools = QWidget()
        paint_tools_layout = QHBoxLayout(paint_tools)
        paint_tools_layout.setContentsMargins(0, 0, 0, 0)
        self.paint_bucket_btn = QToolButton()
        self.paint_bucket_btn.setObjectName("colorTool")
        self.paint_bucket_btn.setCheckable(True)
        self.paint_bucket_btn.setIcon(color_tool_icon("bucket"))
        self.paint_bucket_btn.setIconSize(QSize(20, 20))
        self.paint_bucket_btn.setToolTip("Pot de peinture : remplir les pixels contigus")
        self.paint_bucket_btn.clicked.connect(
            lambda checked: self.toggle_paint_mode("contiguous", checked)
        )
        self.paint_global_btn = QToolButton()
        self.paint_global_btn.setObjectName("colorTool")
        self.paint_global_btn.setCheckable(True)
        self.paint_global_btn.setIcon(color_tool_icon("bucket_global"))
        self.paint_global_btn.setIconSize(QSize(20, 20))
        self.paint_global_btn.setToolTip("Pot + : remplacer cette couleur partout sur le calque")
        self.paint_global_btn.clicked.connect(
            lambda checked: self.toggle_paint_mode("global", checked)
        )
        paint_tools_layout.addWidget(self.paint_bucket_btn)
        paint_tools_layout.addWidget(self.paint_global_btn)
        self.eraser_btn = QToolButton()
        self.eraser_btn.setObjectName("colorTool")
        self.eraser_btn.setCheckable(True)
        self.eraser_btn.setIcon(color_tool_icon("eraser"))
        self.eraser_btn.setIconSize(QSize(20, 20))
        self.eraser_btn.setToolTip("Gomme (E)")
        self.eraser_btn.clicked.connect(self.set_eraser_active)
        paint_tools_layout.addWidget(self.eraser_btn)
        paint_tools_layout.addStretch(1)
        tools_layout.addWidget(paint_tools)
        self.paint_settings = QWidget()
        paint_settings_layout = QFormLayout(self.paint_settings)
        paint_settings_layout.setContentsMargins(0, 0, 0, 0)
        paint_settings_layout.setSpacing(5)
        self.paint_tolerance = QSpinBox()
        self.paint_tolerance.setRange(0, 255)
        self.paint_tolerance.setValue(15)
        self.paint_tolerance.setToolTip(
            "Écart maximal autorisé sur chacun des canaux rouge, vert et bleu"
        )
        self.preserve_shading = QCheckBox("Préserver ombres et reflets")
        self.preserve_shading.setToolTip(
            "Recoloriser en conservant les nuances de luminosité d'origine"
        )
        paint_settings_layout.addRow("Tolérance", self.paint_tolerance)
        paint_settings_layout.addRow("Recolorisation", self.preserve_shading)
        tools_layout.addWidget(self.paint_settings)
        self.eraser_settings = QWidget()
        self.eraser_settings.setObjectName("eraserSettings")
        eraser_layout = QFormLayout(self.eraser_settings)
        eraser_layout.setContentsMargins(0, 6, 0, 0)
        eraser_layout.setSpacing(5)
        self.eraser_size_preset = QComboBox()
        for size in (1, 2, 4, 8, 16, 32):
            self.eraser_size_preset.addItem(f"{size} × {size} px", size)
        self.eraser_size_preset.addItem("Personnalisée", None)
        self.eraser_size_preset.setCurrentIndex(3)
        self.eraser_size_preset.currentIndexChanged.connect(self.update_eraser_size_preset)
        self.eraser_size = QSpinBox()
        self.eraser_size.setRange(1, 2048)
        self.eraser_size.setValue(8)
        self.eraser_size.setSuffix(" px")
        self.eraser_size.setEnabled(False)
        self.eraser_shape = QComboBox()
        self.eraser_shape.addItem("Carré", "square")
        self.eraser_shape.addItem("Cercle", "circle")
        self.eraser_pixel_art = QCheckBox("Mode Pixel Art")
        self.eraser_pixel_art.setChecked(True)
        self.eraser_pixel_art.toggled.connect(self.update_eraser_mode_controls)
        self.eraser_hardness = QSpinBox()
        self.eraser_hardness.setRange(0, 100)
        self.eraser_hardness.setValue(100)
        self.eraser_hardness.setSuffix(" %")
        self.eraser_hardness.setEnabled(False)
        self.eraser_opacity = QSpinBox()
        self.eraser_opacity.setRange(1, 100)
        self.eraser_opacity.setSingleStep(25)
        self.eraser_opacity.setValue(100)
        self.eraser_opacity.setSuffix(" %")
        eraser_layout.addRow("Taille gomme", self.eraser_size_preset)
        eraser_layout.addRow("Taille libre", self.eraser_size)
        eraser_layout.addRow("Forme", self.eraser_shape)
        eraser_layout.addRow("Mode", self.eraser_pixel_art)
        eraser_layout.addRow("Dureté", self.eraser_hardness)
        eraser_layout.addRow("Opacité", self.eraser_opacity)
        tools_layout.addWidget(self.eraser_settings)
        self.alternative_label = QLabel("Alternative :")
        tools_layout.addWidget(self.alternative_label)
        self.variations_widget = QWidget()
        variations_layout = QHBoxLayout(self.variations_widget)
        variations_layout.setContentsMargins(0, 0, 0, 0)
        variations_layout.setSpacing(4)
        self.variation_buttons = []
        for index in range(9):
            swatch = QToolButton()
            swatch.setFixedSize(25, 25)
            swatch.clicked.connect(lambda _checked=False, i=index: self.choose_variation(i))
            variations_layout.addWidget(swatch)
            self.variation_buttons.append(swatch)
        tools_layout.addWidget(self.variations_widget)
        self.set_current_color(self.replacement_color)
        self.update_tool_options_visibility()
        tools_layout.addStretch(1)
        self.tools_tab = tools
        self.tabs.addTab(tools, "Outils")
        self.tabs.currentChanged.connect(self.update_properties_panel_visibility)
        right_content_layout.addWidget(self.tabs)
        self.properties_label = QLabel("PROPRIÉTÉS DU CALQUE")
        self.properties_label.setObjectName("sectionTitle")
        right_content_layout.addWidget(self.properties_label)
        self.properties_panel = QWidget()
        self.properties_panel.setObjectName("propertyCard")
        self.properties_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.property_form = QFormLayout(self.properties_panel)
        self.property_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.property_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.property_form.setVerticalSpacing(8)
        self.property_form.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.inputs = {}
        for key, label, minimum, maximum, decimals, step in [
            ("x", "Position X", -16000, 16000, 1, 10),
            ("y", "Position Y", -16000, 16000, 1, 10),
            ("sx", "Échelle X", 0.05, 50, 2, .05),
            ("sy", "Échelle Y", 0.05, 50, 2, .05),
            ("rotation", "Rotation (°)", -3600, 3600, 1, 5),
            ("opacity", "Opacité (%)", 0, 100, 0, 5),
        ]:
            w = QDoubleSpinBox()
            w.setRange(minimum, maximum)
            w.setDecimals(decimals)
            w.setSingleStep(step)
            w.setKeyboardTracking(False)
            w.editingFinished.connect(self.commit_properties)
            self.property_form.addRow(label, w)
            self.inputs[key] = w
        self.name_input = QLineEdit()
        self.name_input.editingFinished.connect(self.commit_properties)
        self.property_form.insertRow(0, "Nom du calque", self.name_input)
        self.text_input = CommitPlainTextEdit()
        self.text_input.setMinimumHeight(76)
        self.text_input.setMaximumHeight(120)
        self.text_input.setPlaceholderText("Saisissez le texte…")
        self.text_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_input.editingFinished.connect(self.commit_properties)
        self.property_form.addRow("Contenu texte", self.text_input)
        self.text_alignment_control = QWidget()
        alignment_layout = QHBoxLayout(self.text_alignment_control)
        alignment_layout.setContentsMargins(0, 0, 0, 0)
        alignment_layout.setSpacing(5)
        self.text_alignment_group = QButtonGroup(self)
        self.text_alignment_group.setExclusive(True)
        self.text_alignment_buttons = {}
        for alignment, tooltip in (
            ("left", "Aligner à gauche"),
            ("center", "Centrer"),
            ("right", "Aligner à droite"),
        ):
            button = QToolButton()
            button.setObjectName("textAlignment")
            button.setCheckable(True)
            button.setIcon(alignment_icon(alignment))
            button.setIconSize(QSize(20, 20))
            button.setToolTip(tooltip)
            button.clicked.connect(self.commit_properties)
            self.text_alignment_group.addButton(button)
            self.text_alignment_buttons[alignment] = button
            alignment_layout.addWidget(button)
        alignment_layout.addStretch(1)
        self.text_alignment_buttons["center"].setChecked(True)
        self.property_form.addRow("Alignement", self.text_alignment_control)
        self.font_combo = QFontComboBox()
        self.font_combo.currentFontChanged.connect(lambda _: self.commit_properties())
        self.property_form.addRow("Police", self.font_combo)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 300)
        self.font_size.setKeyboardTracking(False)
        self.font_size.editingFinished.connect(self.commit_properties)
        self.property_form.addRow("Taille du texte", self.font_size)
        self.text_color_swatch = QPushButton()
        self.text_color_swatch.setFixedSize(36, 28)
        self.text_color_swatch.setToolTip("Choisir la couleur du texte")
        self.text_color_swatch.clicked.connect(self.choose_color)
        self.color_btn = QPushButton("#000000")
        self.color_btn.clicked.connect(self.choose_color)
        self.text_color_control = QWidget()
        text_color_layout = QHBoxLayout(self.text_color_control)
        text_color_layout.setContentsMargins(0, 0, 0, 0)
        text_color_layout.setSpacing(6)
        text_preview_column = QWidget()
        text_preview_layout = QVBoxLayout(text_preview_column)
        text_preview_layout.setContentsMargins(0, 0, 0, 0)
        text_preview_layout.setSpacing(4)
        text_preview_layout.addWidget(self.text_color_swatch)
        self.text_picker_btn = QToolButton()
        self.text_picker_btn.setObjectName("colorTool")
        self.text_picker_btn.setCheckable(True)
        self.text_picker_btn.setIcon(color_tool_icon("picker"))
        self.text_picker_btn.setIconSize(QSize(18, 18))
        self.text_picker_btn.setToolTip("Prélever la couleur du texte sur le canvas")
        self.text_picker_btn.clicked.connect(
            lambda checked: self.activate_picker("text", checked)
        )
        text_preview_layout.addWidget(self.text_picker_btn)
        text_color_layout.addWidget(text_preview_column)
        text_color_layout.addWidget(self.color_btn, stretch=1)
        self.property_form.addRow("Couleur du texte", self.text_color_control)
        self.text_background_swatch = QPushButton()
        self.text_background_swatch.setFixedSize(36, 28)
        self.text_background_swatch.setToolTip("Choisir la couleur de fond du texte")
        self.text_background_swatch.clicked.connect(self.choose_text_background)
        self.text_background_btn = QPushButton("Transparent")
        self.text_background_btn.clicked.connect(self.choose_text_background)
        self.text_background_clear = QToolButton()
        self.text_background_clear.setObjectName("colorTool")
        self.text_background_clear.setText("×")
        self.text_background_clear.setToolTip("Rendre le fond transparent")
        self.text_background_clear.clicked.connect(self.clear_text_background)
        self.text_background_control = QWidget()
        background_layout = QHBoxLayout(self.text_background_control)
        background_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.setSpacing(6)
        background_preview_column = QWidget()
        background_preview_layout = QVBoxLayout(background_preview_column)
        background_preview_layout.setContentsMargins(0, 0, 0, 0)
        background_preview_layout.setSpacing(4)
        background_preview_layout.addWidget(self.text_background_swatch)
        self.text_background_picker_btn = QToolButton()
        self.text_background_picker_btn.setObjectName("colorTool")
        self.text_background_picker_btn.setCheckable(True)
        self.text_background_picker_btn.setIcon(color_tool_icon("picker"))
        self.text_background_picker_btn.setIconSize(QSize(18, 18))
        self.text_background_picker_btn.setToolTip("Prélever la couleur de fond sur le canvas")
        self.text_background_picker_btn.clicked.connect(
            lambda checked: self.activate_picker("text_background", checked)
        )
        background_preview_layout.addWidget(self.text_background_picker_btn)
        background_layout.addWidget(background_preview_column)
        background_layout.addWidget(self.text_background_btn, stretch=1)
        background_layout.addWidget(self.text_background_clear)
        self.property_form.addRow("Couleur de fond", self.text_background_control)
        self.curve_control = QWidget()
        curve_layout = QHBoxLayout(self.curve_control)
        curve_layout.setContentsMargins(0, 0, 0, 0)
        curve_layout.setSpacing(6)
        self.curve_intensity = QSlider(Qt.Orientation.Horizontal)
        self.curve_intensity.setRange(-100, 100)
        self.curve_intensity.setValue(0)
        self.curve_intensity.setToolTip("Courbure : négatif vers le bas, positif vers le haut")
        self.curve_intensity.valueChanged.connect(self.preview_curve_intensity)
        self.curve_intensity.sliderReleased.connect(self.commit_properties)
        self.curve_value = QSpinBox()
        self.curve_value.setRange(-100, 100)
        self.curve_value.setFixedWidth(66)
        self.curve_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curve_value.setToolTip("Valeur de courbure")
        self.curve_value.valueChanged.connect(self.set_curve_from_value)
        self.curve_value.editingFinished.connect(self.commit_properties)
        self.curve_reset_btn = QToolButton()
        self.curve_reset_btn.setText("0")
        self.curve_reset_btn.setToolTip("Remettre le texte droit")
        self.curve_reset_btn.clicked.connect(self.reset_curve_only)
        curve_layout.addWidget(self.curve_intensity, stretch=1)
        curve_layout.addWidget(self.curve_value)
        curve_layout.addWidget(self.curve_reset_btn)
        self.property_form.addRow("Courbure", self.curve_control)
        self.character_spacing = QDoubleSpinBox()
        self.character_spacing.setRange(-50, 200)
        self.character_spacing.setDecimals(1)
        self.character_spacing.setSuffix(" px")
        self.character_spacing.setKeyboardTracking(False)
        self.character_spacing.editingFinished.connect(self.commit_properties)
        self.property_form.addRow("Espacement", self.character_spacing)
        self.lock_btn = QPushButton("Verrouiller / déverrouiller")
        self.lock_btn.clicked.connect(self.toggle_lock)
        self.property_form.addRow("Édition", self.lock_btn)
        self.text_property_widgets = (
            self.text_input, self.text_alignment_control, self.font_combo, self.font_size,
            self.text_color_control, self.text_background_control, self.curve_control,
            self.character_spacing,
            self.lock_btn
        )
        right_content_layout.addWidget(self.properties_panel)
        right_content_layout.addStretch(1)
        right_scroll.setWidget(right_content)
        r_layout.addWidget(right_scroll)
        self._schedule_right_panel_layout()
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 925, 315])
        self.zoom_label = QLabel("100 %")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().showMessage("Prêt · Déplacez les objets sur le canvas")

    def _action(self, menu, label: str, callback, shortcut=None, icon=None):
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if icon:
            act.setIcon(QIcon(str(icon)))
        act.triggered.connect(callback)
        menu.addAction(act)
        return act

    def _build_actions(self):
        f = self.menuBar().addMenu("Fichier")
        new = self._action(f, "Nouveau projet…", self.new_document, "Ctrl+N")
        op = self._action(f, "Ouvrir un projet…", self.open_document, "Ctrl+O")
        f.addSeparator()
        imp = self._action(f, "Importer une image…", self.add_images, "Ctrl+I")
        self._action(f, "Ajouter du texte…", self.add_text, "Ctrl+T")
        self._action(f, "Importer une police…", self.import_fonts)
        f.addSeparator()
        ex = self._action(f, "Sauvegarder l'image…", self.export_image, "Ctrl+S")
        sv = self._action(f, "Sauvegarder le projet", self.save_document, "Ctrl+Shift+S")
        self._action(f, "Sauvegarder le projet sous…", self.save_as_document)
        f.addSeparator()
        self._action(f, "Quitter", self.close, "Alt+F4")

        e = self.menuBar().addMenu("Édition")
        self.undo_action = self.undo_stack.createUndoAction(self, "Annuler")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        e.addAction(self.undo_action)
        self.redo_action = self.undo_stack.createRedoAction(self, "Rétablir")
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        e.addAction(self.redo_action)
        e.addSeparator()
        self.copy_action = self._action(e, "Copier le calque", self.copy_layer, "Ctrl+C")
        self.cut_action = self._action(e, "Couper le calque", self.cut_layer, "Ctrl+X")
        self.paste_action = self._action(e, "Coller l'image", self.paste_image, "Ctrl+V")
        e.addSeparator()
        self._action(e, "Dupliquer le calque", self.duplicate_layer, "Ctrl+D")
        self._action(e, "Retourner horizontalement", self.flip_layer_horizontal)
        self._action(e, "Retourner verticalement", self.flip_layer_vertical)
        self._action(e, "Verrouiller / déverrouiller", self.toggle_lock)
        self.delete_action = self._action(e, "Supprimer le calque", self.delete_layer, "Delete")
        tools_menu = self.menuBar().addMenu("Outils")
        self.eraser_action = QAction(color_tool_icon("eraser"), "Gomme (E)", self)
        self.eraser_action.setCheckable(True)
        self.eraser_action.triggered.connect(self.set_eraser_active)
        tools_menu.addAction(self.eraser_action)
        self.eraser_shortcut = QShortcut(QKeySequence("E"), self.canvas)
        self.eraser_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.eraser_shortcut.activated.connect(
            lambda: self.set_eraser_active(not self.eraser_active)
        )
        v = self.menuBar().addMenu("Affichage")
        self._action(v, "Afficher / masquer le panneau d'utilitaires", self.toggle_left_sidebar, "F9")
        self._action(v, "Ajuster à la fenêtre", self.canvas.fit_document, "Ctrl+0")
        self._action(v, "Zoom +", lambda: self.change_zoom(1.2), "Ctrl++")
        self._action(v, "Zoom -", lambda: self.change_zoom(1/1.2), "Ctrl+-")
        h = self.menuBar().addMenu("Aide")
        self._action(h, "À propos", self.about)
    def toggle_left_sidebar(self):
        self.left_sidebar_expanded = not self.left_sidebar_expanded
        if self.left_sidebar_expanded:
            sizes = self.main_splitter.sizes()
            self.left_panel.show()
            self.main_splitter.setSizes([
                self.left_sidebar_width,
                max(1, sizes[1] - self.left_sidebar_width), sizes[2],
            ])
            self.left_toggle.setIcon(sidebar_arrow_icon(False))
            self.left_toggle.setToolTip("Replier le panneau d'utilitaires")
        else:
            self.left_sidebar_width = max(155, self.main_splitter.sizes()[0])
            self.left_panel.hide()
            self.left_toggle.setIcon(sidebar_arrow_icon(True))
            self.left_toggle.setToolTip("Ouvrir le panneau d'utilitaires")

    def _load_demo(self):
        demo = ROOT / "exemples" / "Manta_Demo.manta"
        if demo.exists():
            try:
                self.document = open_project(demo)
            except Exception:
                self.document = Document()
        self.install_document(self.document, self.document.layers[-1].id if self.document.layers else None)
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.canvas.fit_document()
        self.update_title()

    def install_document(self, doc: Document, selected: str | None):
        self.refreshing = True
        self.document = doc
        self.selected_id = selected if doc.layer(selected) else None
        self.canvas_scene = make_scene(doc, interactive=True)
        self.canvas.setScene(self.canvas_scene)
        self.canvas_scene.selectionChanged.connect(self.on_scene_select)
        self.layer_list.clear()
        for layer in reversed(doc.layers):
            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, layer.id)
            self.layer_list.addItem(row)
            controls = QWidget()
            controls_layout = QHBoxLayout(controls)
            controls_layout.setContentsMargins(3, 1, 3, 1)
            controls_layout.setSpacing(3)
            drag_handle = LayerDragHandle(layer.id)
            controls_layout.addWidget(drag_handle)
            visible = QToolButton()
            visible.setObjectName("layerAction")
            visible.setCheckable(True)
            visible.setChecked(layer.visible)
            visible.setIcon(eye_icon(layer.visible))
            visible.setIconSize(QSize(18, 18))
            visible.setFixedSize(32, 27)
            visible.setToolTip("Masquer le calque" if layer.visible else "Afficher le calque")
            visible.clicked.connect(
                lambda checked, layer_id=layer.id: self.set_layer_visibility(layer_id, checked)
            )
            controls_layout.addWidget(visible)
            kind = QLabel()
            kind.setPixmap(layer_kind_icon(layer.kind))
            kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
            kind.setFixedSize(20, 27)
            kind.setToolTip("Calque texte" if layer.kind == "text" else "Calque image")
            controls_layout.addWidget(kind)
            name = QPushButton(layer.name)
            name.setObjectName("layerName")
            name.setToolTip(layer.name)
            name.setFlat(True)
            name.setMinimumWidth(0)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            name.clicked.connect(lambda _checked=False, layer_id=layer.id: self.select_layer(layer_id))
            controls_layout.addWidget(name, stretch=1)
            for symbol, tooltip, direction in (("▲", "Monter le calque", 1),
                                                ("▼", "Descendre le calque", -1)):
                button = QToolButton()
                button.setObjectName("layerAction")
                button.setText(symbol)
                button.setToolTip(tooltip)
                button.setFixedSize(30, 27)
                button.setEnabled(not layer.locked)
                button.clicked.connect(
                    lambda _checked=False, layer_id=layer.id, delta=direction:
                    self.reorder_layer(delta, layer_id)
                )
                controls_layout.addWidget(button)
            lock = QToolButton()
            lock.setObjectName("layerAction")
            lock.setIcon(lock_icon(layer.locked))
            lock.setIconSize(QSize(18, 18))
            lock.setToolTip("Déverrouiller le calque" if layer.locked else "Verrouiller le calque")
            lock.setCheckable(True)
            lock.setChecked(layer.locked)
            lock.setFixedSize(32, 27)
            lock.clicked.connect(
                lambda _checked=False, layer_id=layer.id: self.toggle_lock(layer_id)
            )
            controls_layout.addWidget(lock)
            row.setSizeHint(QSize(row.sizeHint().width(), 34))
            self.layer_list.setItemWidget(row, controls)
            if layer.id == self.selected_id:
                self.layer_list.setCurrentItem(row)
        for item in self.canvas_scene.items():
            if item.data(0) == self.selected_id:
                item.setSelected(True)
                break
        self.doc_info.setText(f"{doc.width} × {doc.height} px · {len(doc.layers)} calque(s)")
        self._refresh_properties()
        self.update_utility_buttons()
        self.refreshing = False
        self.canvas.viewport().update()
        self.update_title()

    def update_utility_buttons(self):
        """N'affiche dans la colonne gauche que les actions actuellement possibles."""
        if not hasattr(self, "utility_buttons"):
            return
        layer = self.document.layer(self.selected_id)
        editable = bool(layer and not layer.locked)
        for key in ("duplicate", "flip_horizontal", "flip_vertical", "delete"):
            self.utility_buttons[key].setVisible(editable)
        self.utility_buttons["lock"].setVisible(layer is not None)
        if layer is not None:
            self.utility_buttons["lock"].setText(
                "▣ Déverrouiller le calque" if layer.locked
                else "▣ Verrouiller le calque"
            )
    def select_layer(self, layer_id: str | None):
        if self.refreshing:
            return
        self.refreshing = True
        self.selected_id = layer_id if self.document.layer(layer_id) else None
        for i in range(self.layer_list.count()):
            row = self.layer_list.item(i)
            if row.data(Qt.ItemDataRole.UserRole) == self.selected_id:
                self.layer_list.setCurrentItem(row)
                break
        else:
            self.layer_list.setCurrentRow(-1)
        scene = self.canvas.scene()
        if scene is not None:
            for item in scene.items():
                if self.document.layer(item.data(0)):
                    item.setSelected(item.data(0) == self.selected_id)
        self._refresh_properties()
        self.update_utility_buttons()
        self.refreshing = False
        self.canvas.viewport().update()

    def on_scene_select(self):
        if self.refreshing:
            return
        scene = self.canvas.scene()
        if scene is None:
            return
        selected = scene.selectedItems()
        if selected:
            self.select_layer(selected[0].data(0))
        else:
            self.select_layer(None)

    def on_layer_list_select(self, current, previous):
        if not self.refreshing:
            self.select_layer(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def set_layer_visibility(self, layer_id: str, visible: bool):
        if self.refreshing:
            return
        layer = self.document.layer(layer_id)
        if layer and layer.visible != visible:
            self.mutate("Afficher / masquer le calque",
                        lambda doc: setattr(doc.layer(layer_id), "visible", visible), layer_id)

    def _refresh_properties(self):
        layer = self.document.layer(self.selected_id)
        is_text = bool(layer and layer.kind == "text")
        for widget in self.text_property_widgets:
            self.property_form.setRowVisible(widget, is_text)
        editable_widgets = [self.name_input, self.text_input, self.font_combo, self.font_size,
                            self.text_color_control, self.text_background_control,
                            self.text_alignment_control, self.curve_control,
                            self.character_spacing, *self.inputs.values()]
        widgets = [*editable_widgets, self.lock_btn]
        for w in widgets:
            w.setEnabled(layer is not None)
        if not layer:
            self.name_input.setText("")
            self.text_input.setPlainText("")
            self.paint_bucket_btn.setEnabled(False)
            self.paint_global_btn.setEnabled(False)
            self._schedule_right_panel_layout()
            return
        self.name_input.setText(layer.name)
        for w in editable_widgets:
            w.setEnabled(not layer.locked)
        for key, spin in self.inputs.items():
            spin.setValue(layer.opacity * 100 if key == "opacity" else getattr(layer, key))
        self.text_input.setPlainText(layer.text)
        for w in (self.text_input, self.font_combo, self.font_size,
                  self.text_color_control, self.text_background_control):
            w.setEnabled(is_text and not layer.locked)
        self.font_combo.setCurrentFont(QFont(layer.font_family))
        self.font_size.setValue(layer.font_size)
        self.curve_intensity.setValue(round(layer.curve_intensity))
        self.curve_value.setValue(round(layer.curve_intensity))
        self.character_spacing.setValue(layer.character_spacing)
        self.text_alignment_buttons.get(
            layer.path_alignment, self.text_alignment_buttons["center"]
        ).setChecked(True)
        self.color_btn.setText(layer.color.upper())
        self.text_color_swatch.setStyleSheet(
            f"background-color: {layer.color}; border: 1px solid #ACC9D4; border-radius: 5px;"
        )
        background = layer.text_background if is_text else None
        self.text_background_btn.setText(background.upper() if background else "Transparent")
        self.text_background_swatch.setStyleSheet(
            f"background-color: {background}; border: 1px solid #ACC9D4; border-radius: 5px;"
            if background else
            "background-color: transparent; border: 1px dashed #ACC9D4; border-radius: 5px;"
        )
        self.text_background_clear.setEnabled(bool(background) and not layer.locked)
        self.lock_btn.setText("Déverrouiller" if layer.locked else "Verrouiller")
        can_paint = layer.kind == "image" and not layer.locked
        self.paint_bucket_btn.setEnabled(can_paint)
        self.paint_global_btn.setEnabled(can_paint)
        self._schedule_right_panel_layout()

    def mutate(self, description: str, fn, select_after: str | None = None):
        before = self.document.clone()
        after = self.document.clone()
        fn(after)
        self.undo_stack.push(DocumentCommand(self, before, after, description,
                                             self.selected_id,
                                             select_after if select_after is not None else self.selected_id))
        self.statusBar().showMessage(description, 3000)

    def commit_canvas_transform(self, before, layer_id, state, description):
        after = before.clone()
        layer = after.layer(layer_id)
        layer.x, layer.y, layer.sx, layer.sy, layer.rotation = state
        self.undo_stack.push(DocumentCommand(self, before, after, description, layer_id, layer_id))

    def commit_properties(self, *_args):
        if self.refreshing:
            return
        old = self.document.layer(self.selected_id)
        if not old or old.locked:
            return
        settings = {k: (spin.value() / 100 if k == "opacity" else spin.value())
                    for k, spin in self.inputs.items()}
        settings.update(name=self.name_input.text().strip() or old.name)
        if old.kind == "text":
            settings.update(text=self.text_input.toPlainText(), font_family=self.font_combo.currentFont().family(),
                            font_size=self.font_size.value(),
                            text_deformation="curve",
                            curve_intensity=float(self.curve_intensity.value()),
                            character_spacing=self.character_spacing.value(),
                            path_alignment=self.current_text_alignment(),
                            path_orientation="tangent",
                            show_curve_guide=True)
        if all(getattr(old, k) == val for k,val in settings.items()):
            return
        self.mutate("Modifier les propriétés", lambda doc: [setattr(doc.layer(old.id), k, v)
                                                               for k,v in settings.items()], old.id)

    def preview_curve_intensity(self, value: int):
        self.curve_value.blockSignals(True)
        self.curve_value.setValue(value)
        self.curve_value.blockSignals(False)
        if self.refreshing:
            return
        item = self.canvas.selected_graphic()
        if hasattr(item, "set_curve_intensity"):
            item.set_curve_intensity(value)
            self.canvas.viewport().update()

    def set_curve_from_value(self, value: int):
        self.curve_intensity.setValue(value)

    def reset_curve_only(self):
        self.curve_intensity.setValue(0)
        self.commit_properties()

    def current_text_alignment(self) -> str:
        for alignment, button in self.text_alignment_buttons.items():
            if button.isChecked():
                return alignment
        return "center"

    def reset_text_deformation(self):
        layer = self.document.layer(self.selected_id)
        if not layer or layer.kind != "text" or layer.locked:
            return
        def reset(doc):
            target = doc.layer(layer.id)
            target.text_deformation = "curve"
            target.curve_intensity = 0.0
            target.character_spacing = 0.0
            target.path_alignment = "center"
            target.path_orientation = "tangent"
            target.show_curve_guide = True
        self.mutate("Réinitialiser la déformation du texte", reset, layer.id)

    def commit_curve_handle(self, before: Document, layer_id: str, intensity: float):
        source = before.layer(layer_id)
        if not source or abs(source.curve_intensity - intensity) < 0.01:
            return
        after = before.clone()
        after.layer(layer_id).curve_intensity = intensity
        self.undo_stack.push(DocumentCommand(
            self, before, after, "Ajuster la courbure du texte", layer_id, layer_id
        ))

    def choose_color(self):
        old = self.document.layer(self.selected_id)
        if old and old.kind == "text":
            color = QColorDialog.getColor(QColor(old.color), self, "Couleur du texte")
            if color.isValid() and color.name().upper() != old.color.upper():
                self.mutate("Couleur du texte", lambda doc: setattr(doc.layer(old.id), "color", color.name().upper()), old.id)

    def choose_text_background(self):
        old = self.document.layer(self.selected_id)
        if not old or old.kind != "text" or old.locked:
            return
        initial = QColor(old.text_background or "#FFFFFF")
        color = QColorDialog.getColor(initial, self, "Couleur de fond du texte")
        if not color.isValid():
            return
        value = None if color.alpha() == 0 else color.name().upper()
        if value != old.text_background:
            self.mutate(
                "Couleur de fond du texte",
                lambda doc: setattr(doc.layer(old.id), "text_background", value),
                old.id,
            )

    def clear_text_background(self):
        old = self.document.layer(self.selected_id)
        if old and old.kind == "text" and not old.locked and old.text_background:
            self.mutate(
                "Fond du texte transparent",
                lambda doc: setattr(doc.layer(old.id), "text_background", None),
                old.id,
            )

    def activate_picker(self, target: str, active: bool):
        if not active:
            self.deactivate_picker()
            return
        self.set_eraser_active(False)
        if target in ("text", "text_background"):
            layer = self.document.layer(self.selected_id)
            if not layer or layer.kind != "text" or layer.locked:
                self.text_picker_btn.setChecked(False)
                self.text_background_picker_btn.setChecked(False)
                self.statusBar().showMessage(
                    "Sélectionnez un calque texte déverrouillé", 3000
                )
                return
            self.picker_text_layer_id = layer.id
        else:
            self.picker_text_layer_id = None
        self.paint_mode = None
        self.paint_bucket_btn.setChecked(False)
        self.paint_global_btn.setChecked(False)
        self.update_tool_options_visibility()
        self.picker_target = target
        self.picker_active = True
        self.picker_btn.setChecked(target == "tools")
        self.text_picker_btn.setChecked(target == "text")
        self.text_background_picker_btn.setChecked(target == "text_background")
        self._refresh_color_tool_cursor()
        self.statusBar().showMessage("Cliquez sur un pixel d'un calque image", 3000)

    def deactivate_picker(self):
        self.picker_active = False
        self.picker_btn.setChecked(False)
        self.text_picker_btn.setChecked(False)
        self.text_background_picker_btn.setChecked(False)
        self._refresh_color_tool_cursor()

    def _refresh_color_tool_cursor(self):
        if self.eraser_active:
            cursor = Qt.CursorShape.BlankCursor
        else:
            active = self.picker_active or self.paint_mode is not None
            cursor = Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        self.canvas.setCursor(cursor)

    def toggle_paint_mode(self, mode: str, active: bool):
        if active:
            self.set_eraser_active(False)
            self.picker_active = False
            self.picker_btn.setChecked(False)
            self.text_picker_btn.setChecked(False)
            self.text_background_picker_btn.setChecked(False)
            self.paint_mode = mode
            self.paint_bucket_btn.setChecked(mode == "contiguous")
            self.paint_global_btn.setChecked(mode == "global")
            message = (
                "Cliquez dans une zone à remplir"
                if mode == "contiguous"
                else "Cliquez sur la couleur à remplacer dans tout le calque"
            )
            self.statusBar().showMessage(message, 4000)
        elif self.paint_mode == mode:
            self.paint_mode = None
        self.update_tool_options_visibility()
        self._refresh_color_tool_cursor()

    def set_eraser_active(self, active: bool):
        self.canvas.cancel_eraser_preview()
        self.eraser_active = bool(active)
        if self.eraser_active:
            self.picker_active = False
            self.paint_mode = None
            self.picker_btn.setChecked(False)
            self.text_picker_btn.setChecked(False)
            self.text_background_picker_btn.setChecked(False)
            self.paint_bucket_btn.setChecked(False)
            self.paint_global_btn.setChecked(False)
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Gomme active · glisser pour effacer · [ et ] changent la taille", 4500
            )
        self.eraser_btn.setChecked(self.eraser_active)
        if hasattr(self, "eraser_action"):
            self.eraser_action.setChecked(self.eraser_active)
        self.canvas.eraser_item = None
        self.canvas.eraser_points = []
        self.canvas.eraser_cursor_local = None
        self.update_tool_options_visibility()
        self._refresh_color_tool_cursor()
        self.canvas.viewport().update()

    def update_tool_options_visibility(self):
        """N'affiche que les réglages utiles à l'outil actuellement actif."""
        eraser = self.eraser_active
        bucket = self.paint_mode is not None and not eraser
        self.eraser_settings.setVisible(eraser)
        self.paint_settings.setVisible(bucket)
        for widget in (
            self.color_tools_label, self.color_editor,
            self.alternative_label, self.variations_widget,
        ):
            widget.setVisible(not eraser)
        self._schedule_right_panel_layout()

    def update_eraser_size_preset(self, _index=None):
        size = self.eraser_size_preset.currentData()
        custom = size is None
        self.eraser_size.setEnabled(custom)
        if not custom:
            self.eraser_size.setValue(size)
        self.canvas.viewport().update()

    def update_eraser_mode_controls(self, pixel_art: bool):
        self.eraser_hardness.setEnabled(not pixel_art)
        if not pixel_art:
            circle_index = self.eraser_shape.findData("circle")
            self.eraser_shape.setCurrentIndex(circle_index)
        self.eraser_shape.setEnabled(pixel_art)
        self.canvas.viewport().update()

    def adjust_eraser_size(self, direction: int):
        presets = [1, 2, 4, 8, 16, 32]
        current = self.eraser_size.value()
        if current in presets:
            index = max(0, min(len(presets) - 1, presets.index(current) + direction))
            value = presets[index]
            self.eraser_size_preset.setCurrentIndex(index)
        else:
            value = max(1, min(2048, current + direction))
            self.eraser_size_preset.setCurrentIndex(self.eraser_size_preset.count() - 1)
            self.eraser_size.setValue(value)
        self.statusBar().showMessage(f"Taille de gomme : {value} px", 1800)
        self.canvas.viewport().update()

    def commit_eraser_stroke(self, layer_id: str, points: list[QPointF]):
        layer = self.document.layer(layer_id)
        item = self.canvas.selected_graphic()
        if not layer or layer.kind != "image" or layer.locked or item is None:
            self.statusBar().showMessage("Trait de gomme ignoré : calque non modifiable", 3000)
            return
        width, height = item.pixmap().width(), item.pixmap().height()
        source_points = []
        for point in points:
            x = width - 1 - point.x() if layer.flip_horizontal else point.x()
            y = height - 1 - point.y() if layer.flip_vertical else point.y()
            source_points.append([x, y])
        stroke = {
            "points": source_points,
            "size": self.eraser_size.value(),
            "shape": self.eraser_shape.currentData(),
            "pixel_art": self.eraser_pixel_art.isChecked(),
            "hardness": self.eraser_hardness.value(),
            "opacity": self.eraser_opacity.value(),
        }
        self.mutate(
            "Trait de gomme",
            lambda doc: doc.layer(layer_id).eraser_strokes.append(stroke),
            layer_id,
        )

    def sample_canvas_color(self, item, scene_position) -> bool:
        layer = self.document.layer(item.data(0))
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("La pipette fonctionne sur les calques image", 3000)
            return False
        local = item.mapFromScene(scene_position)
        x, y = int(local.x()), int(local.y())
        image = item.pixmap().toImage()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        color = image.pixelColor(x, y)
        if color.alpha() == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return False
        sampled = color.name().upper()
        if self.picker_target in ("text", "text_background"):
            text_layer = self.document.layer(self.picker_text_layer_id)
            if not text_layer or text_layer.kind != "text" or text_layer.locked:
                self.deactivate_picker()
                self.statusBar().showMessage("Le calque texte n'est plus modifiable", 3000)
                return False
            attribute = "text_background" if self.picker_target == "text_background" else "color"
            description = "Couleur de fond du texte" if attribute == "text_background" else "Couleur du texte"
            self.mutate(
                description,
                lambda doc: setattr(doc.layer(text_layer.id), attribute, sampled),
                text_layer.id,
            )
        else:
            self.select_layer(layer.id)
            self.sampled_color = sampled
            self.set_current_color(sampled)
        self.deactivate_picker()
        self.statusBar().showMessage(f"Couleur prélevée : {sampled}", 4000)
        return True

    def paint_canvas_color(self, item, scene_position) -> bool:
        layer = self.document.layer(item.data(0))
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("Le pot fonctionne sur les calques image", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le modifier", 3000)
            return True
        local = item.mapFromScene(scene_position)
        x, y = int(local.x()), int(local.y())
        image = item.pixmap().toImage()
        if not (0 <= x < image.width() and 0 <= y < image.height()):
            return False
        color = image.pixelColor(x, y)
        if color.alpha() == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return True
        clicked_source = color.name().upper()
        source = self.sampled_color or clicked_source
        target = self.replacement_color.upper()
        if source == target:
            self.statusBar().showMessage("La couleur choisie est déjà appliquée", 3000)
            return True
        source_rgb = QColor(source).getRgb()[:3]
        clicked_rgb = color.getRgb()[:3]
        tolerance = self.paint_tolerance.value()
        if any(abs(current - reference) > tolerance
               for current, reference in zip(clicked_rgb, source_rgb)):
            self.statusBar().showMessage(
                "La couleur cliquée est hors de la tolérance de la couleur prélevée", 3500
            )
            return True
        seed_x = image.width() - 1 - x if layer.flip_horizontal else x
        seed_y = image.height() - 1 - y if layer.flip_vertical else y
        fill = {
            "mode": self.paint_mode,
            "source": source,
            "target": target,
            "x": seed_x,
            "y": seed_y,
            "tolerance": self.paint_tolerance.value(),
            "preserve_shading": self.preserve_shading.isChecked(),
        }
        description = (
            "Recoloriser une zone" if self.preserve_shading.isChecked()
            else "Remplir une zone"
        ) if self.paint_mode == "contiguous" else (
            "Recoloriser le calque" if self.preserve_shading.isChecked()
            else "Remplacer une couleur sur le calque"
        )
        self.mutate(
            description,
            lambda doc: doc.layer(layer.id).color_fills.append(fill),
            layer.id,
        )
        return True

    def set_current_color(self, color: str, skip_field: str | None = None):
        selected = QColor(color)
        if not selected.isValid():
            return
        self.replacement_color = selected.name().upper()
        self.color_preview.setStyleSheet(
            f"background-color: {self.replacement_color}; border: 1px solid #ACC9D4; border-radius: 6px;"
        )
        hue = selected.hslHue() if selected.hslHue() >= 0 else 0
        saturation = round(selected.hslSaturationF() * 100)
        lightness = round(selected.lightnessF() * 100)
        values = {
            "hex": self.replacement_color,
            "rgb": f"{selected.red()}, {selected.green()}, {selected.blue()}",
            "hsl": f"{hue}, {saturation} %, {lightness} %",
        }
        fields = {
            "hex": self.sampled_color_input,
            "rgb": self.sampled_rgb_input,
            "hsl": self.sampled_hsl_input,
        }
        self._updating_color_fields = True
        for name, field in fields.items():
            if name != skip_field:
                field.setText(values[name])
        self._updating_color_fields = False
        self.refresh_color_variations(selected)

    def update_color_from_hex(self, value: str):
        if self._updating_color_fields:
            return
        value = value.strip()
        if len(value) == 7 and value.startswith("#") and QColor(value).isValid():
            self.set_current_color(value, "hex")

    def update_color_from_rgb(self, value: str):
        if self._updating_color_fields:
            return
        try:
            parts = [int(part.strip()) for part in value.replace("RGB", "").replace("(", "").replace(")", "").split(",")]
        except ValueError:
            return
        if len(parts) == 3 and all(0 <= part <= 255 for part in parts):
            self.set_current_color(QColor(*parts).name(), "rgb")

    def update_color_from_hsl(self, value: str):
        if self._updating_color_fields:
            return
        cleaned = value.replace("HSL", "").replace("°", "").replace("%", "").replace("(", "").replace(")", "")
        try:
            hue, saturation, lightness = [float(part.strip()) for part in cleaned.split(",")]
        except (ValueError, TypeError):
            return
        if 0 <= hue <= 360 and 0 <= saturation <= 100 and 0 <= lightness <= 100:
            color = QColor.fromHslF((hue % 360) / 360, saturation / 100, lightness / 100)
            self.set_current_color(color.name(), "hsl")

    def refresh_color_variations(self, color: QColor):
        hue = color.hslHueF() if color.hslHueF() >= 0 else 0.0
        saturation = color.hslSaturationF()
        base_lightness = color.lightnessF()
        self.variation_colors = []
        for index, button in enumerate(self.variation_buttons):
            delta = (index - 4) * 0.10
            variation = QColor.fromHslF(hue, saturation, max(0.0, min(1.0, base_lightness + delta)))
            value = variation.name().upper()
            self.variation_colors.append(value)
            button.setToolTip(f"{delta * 100:+.0f} % · {value}")
            button.setStyleSheet(
                f"background: {value}; border: 1px solid #ACC9D4; border-radius: 5px; padding: 0;"
            )

    def choose_variation(self, index: int):
        if 0 <= index < len(self.variation_colors):
            self.set_current_color(self.variation_colors[index])

    def choose_replacement_color(self):
        color = QColorDialog.getColor(QColor(self.replacement_color), self, "Couleur de remplacement")
        if color.isValid():
            self.set_current_color(color.name())

    def toggle_lock(self, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            description = "Déverrouiller le calque" if layer.locked else "Verrouiller le calque"
            self.mutate(description, lambda doc: setattr(doc.layer(layer.id), "locked", not layer.locked), layer.id)

    def selected_image_item(self):
        scene = self.canvas.scene()
        if scene is None:
            return None
        return next((item for item in scene.items()
                     if item.data(0) == self.selected_id and isinstance(item, QGraphicsPixmapItem)), None)

    def copy_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText():
            focused.copy()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection():
            focused.copy()
            return True
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à copier", 3000)
            return False
        QApplication.clipboard().setImage(item.pixmap().toImage())
        self.statusBar().showMessage(f"Calque copié : {layer.name}", 3000)
        return True

    def cut_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText() and not focused.isReadOnly():
            focused.cut()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection() and not focused.isReadOnly():
            focused.cut()
            return True
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque image à couper", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le couper", 3000)
            return False
        if self.copy_layer():
            self.delete_layer()
            return True
        return False

    def paste_image(self) -> bool:
        clipboard = QApplication.clipboard()
        image: QImage = clipboard.image()
        if image.isNull():
            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            if isinstance(focused, QPlainTextEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            self.statusBar().showMessage("Le presse-papiers ne contient pas d'image", 3000)
            return False
        data = qimage_png(image)
        holder = {}

        def add(doc):
            holder["id"] = doc.add_image_bytes(data, "Image collée").id

        self.mutate("Coller une image", add)
        self.select_layer(holder["id"])
        self.tabs.setCurrentIndex(0)
        return True

    def flip_layer_horizontal(self):
        self._flip_selected_layer("flip_horizontal", "Retourner horizontalement")

    def flip_layer_vertical(self):
        self._flip_selected_layer("flip_vertical", "Retourner verticalement")

    def _flip_selected_layer(self, attribute: str, description: str):
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque", 3000)
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le retourner", 3000)
            return
        self.mutate(description,
                    lambda doc: setattr(doc.layer(layer.id), attribute,
                                        not getattr(doc.layer(layer.id), attribute)), layer.id)

    def show_canvas_context_menu(self, global_position):
        layer = self.document.layer(self.selected_id)
        is_image = bool(layer and layer.kind == "image")
        editable_image = bool(is_image and not layer.locked)
        editable_layer = bool(layer and not layer.locked)
        menu = QMenu(self)
        menu.setObjectName("canvasContextMenu")
        copy_action = menu.addAction("Copier\tCtrl+C")
        cut_action = menu.addAction("Couper\tCtrl+X")
        paste_action = menu.addAction("Coller\tCtrl+V")
        copy_action.setEnabled(is_image)
        cut_action.setEnabled(editable_image)
        paste_action.setEnabled(not QApplication.clipboard().image().isNull())
        copy_action.triggered.connect(self.copy_layer)
        cut_action.triggered.connect(self.cut_layer)
        paste_action.triggered.connect(self.paste_image)
        duplicate_action = menu.addAction("Dupliquer\tCtrl+D")
        duplicate_action.setEnabled(bool(layer and not layer.locked))
        duplicate_action.triggered.connect(self.duplicate_layer)
        menu.addSeparator()
        lock_action = menu.addAction("Déverrouiller" if layer and layer.locked else "Verrouiller")
        lock_action.setEnabled(layer is not None)
        lock_action.triggered.connect(self.toggle_lock)
        horizontal = menu.addAction("Retourner horizontalement")
        vertical = menu.addAction("Retourner verticalement")
        horizontal.setEnabled(editable_layer)
        vertical.setEnabled(editable_layer)
        horizontal.triggered.connect(self.flip_layer_horizontal)
        vertical.triggered.connect(self.flip_layer_vertical)
        menu.addSeparator()
        save_layer_action = menu.addAction("Enregistrer le calque sous…")
        save_layer_action.setEnabled(is_image)
        save_layer_action.triggered.connect(self.export_selected_layer)
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer")
        delete_action.setEnabled(bool(layer and not layer.locked))
        delete_action.triggered.connect(self.delete_layer)
        menu.exec(global_position)

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des images", "",
                     "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Tous les fichiers (*)")
        self._import_paths(paths)

    def _import_paths(self, paths):
        if not paths:
            return
        images = []
        for p in paths:
            try:
                images.append((Path(p).read_bytes(), Path(p).stem))
            except Exception as exc:
                QMessageBox.warning(self, "Import impossible", f"{p}\n{exc}")
        for data, name in images:
            try:
                # Prévalidation, pour éviter une commande vide si le fichier est corrompu.
                test = Document(self.document.width, self.document.height)
                test.add_image_bytes(data, name)
                def add(doc):
                    new = doc.add_image_bytes(data, name)
                    self._last_import_id = new.id
                self.mutate(f"Importer {name}", add)
                self.select_layer(self._last_import_id)
            except Exception as exc:
                QMessageBox.warning(self, "Image non prise en charge", f"{name}\n{exc}")

    def add_text(self):
        content, ok = QInputDialog.getText(self, "Nouveau calque texte", "Votre texte :")
        if not ok or not content.strip():
            return
        holder = {}
        def add(doc):
            holder['id'] = doc.add_text(content).id
        self.mutate("Ajouter un texte", add)
        self.select_layer(holder['id'])
        self.tabs.setCurrentIndex(0)

    def delete_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            self.mutate("Supprimer le calque", lambda doc: doc.layers.remove(doc.layer(layer.id)))
            self.select_layer(None)
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le supprimer", 3000)

    def duplicate_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            result = {}
            self.mutate("Dupliquer le calque", lambda doc: result.update(id=doc.duplicate_layer(layer.id).id))
            self.select_layer(result['id'])
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le dupliquer", 3000)

    def reorder_layer(self, direction: int, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            idx = self.document.layers.index(layer)
            if 0 <= idx + direction < len(self.document.layers):
                self.mutate("Changer l'ordre des calques", lambda doc: doc.reorder_layer(layer.id, direction), layer.id)

    def move_layer_to_display_position(self, layer_id: str, insertion: int):
        """Convertit une position visuelle haut->bas vers l'ordre interne bas->haut."""
        display_ids = [layer.id for layer in reversed(self.document.layers)]
        if layer_id not in display_ids:
            return
        current = display_ids.index(layer_id)
        insertion = max(0, min(insertion, len(display_ids)))
        display_ids.pop(current)
        if insertion > current:
            insertion -= 1
        insertion = max(0, min(insertion, len(display_ids)))
        display_ids.insert(insertion, layer_id)
        if display_ids == [layer.id for layer in reversed(self.document.layers)]:
            return

        def apply_order(doc):
            by_id = {layer.id: layer for layer in doc.layers}
            doc.layers = [by_id[id_] for id_ in reversed(display_ids)]

        self.mutate("Réordonner le calque par glisser-déposer", apply_order, layer_id)

    def new_document(self):
        if not self.maybe_save():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Nouveau projet")
        dialog.setMinimumWidth(340)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        width_input = QSpinBox()
        width_input.setRange(1, 16384)
        width_input.setValue(1280)
        width_input.setSuffix(" px")
        height_input = QSpinBox()
        height_input.setRange(1, 16384)
        height_input.setValue(720)
        height_input.setSuffix(" px")
        background_input = QComboBox()
        background_input.addItems(["Transparent", "Blanc", "Noir"])
        form.addRow("Largeur", width_input)
        form.addRow("Hauteur", height_input)
        form.addRow("Fond", background_input)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        create_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        create_button.setText("Créer")
        create_button.setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width = width_input.value()
        height = height_input.value()
        choice = background_input.currentText()
        background = {"Transparent": None, "Blanc": "#FFFFFF", "Noir": "#000000"}[choice]
        self.project_path = None
        self.undo_stack.clear()
        self.install_document(Document(width, height, background), None)
        self.undo_stack.setClean()
        self.canvas.fit_document()

    def resize_document(self):
        width, ok = QInputDialog.getInt(
            self, "Dimensions du document", "Largeur finale (pixels) :",
            self.document.width, 1, 16384
        )
        if not ok:
            return
        height, ok = QInputDialog.getInt(
            self, "Dimensions du document", "Hauteur finale (pixels) :",
            self.document.height, 1, 16384
        )
        if not ok or (width == self.document.width and height == self.document.height):
            return

        def resize(doc):
            doc.width = width
            doc.height = height

        self.mutate(f"Redimensionner le document en {width} × {height} px", resize, self.selected_id)
        self.canvas.fit_document()

    def maybe_save(self) -> bool:
        if self.undo_stack.isClean():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText("Enregistrer les modifications du document ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        save_button = box.button(QMessageBox.StandardButton.Save)
        discard_button = box.button(QMessageBox.StandardButton.Discard)
        save_button.setObjectName("saveButton")
        discard_button.setObjectName("discardButton")
        save_button.setProperty("variant", "primary")
        discard_button.setProperty("variant", "danger")
        save_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['primary']};
                border: 1px solid {COLORS['primary']};
                border-radius: 8px;
                color: {COLORS['background']};
                font-weight: 600;
                min-width: 72px;
                padding: 8px 14px;
            }}
            QPushButton:hover {{ background-color: {COLORS['primary_hover']}; }}
            QPushButton:pressed {{ background-color: {COLORS['primary_pressed']}; }}
        """)
        discard_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['danger']};
                border: 1px solid {COLORS['danger']};
                border-radius: 8px;
                color: {COLORS['background']};
                font-weight: 600;
                min-width: 72px;
                padding: 8px 14px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; }}
            QPushButton:pressed {{ background-color: #C95760; }}
        """)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        result = box.standardButton(box.clickedButton())
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save_document()
        return True

    def open_document(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", "",
            "Projet Manta Layers (*.manta);;Ancien projet Manta Layers (*.mcrab)"
        )
        if not path:
            return
        try:
            doc = open_project(path)
            opened_path = Path(path)
            self.project_path = opened_path if opened_path.suffix.lower() == ".manta" else None
            self.undo_stack.clear()
            self.install_document(doc, None)
            self.undo_stack.setClean()
            self.canvas.fit_document()
            self.statusBar().showMessage(f"Projet chargé : {Path(path).name}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Projet illisible", str(exc))

    def save_document(self) -> bool:
        if self.project_path is None:
            return self.save_as_document()
        try:
            save_project(self.document, self.project_path)
            self.undo_stack.setClean()
            self.statusBar().showMessage(f"Enregistré : {self.project_path.name}", 5000)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))
            return False

    def save_as_document(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder le projet", "MantaLayers.manta", "Projet Manta Layers (*.manta)"
        )
        if not path:
            return False
        self.project_path = Path(path).with_suffix(".manta")
        return self.save_document()

    def export_image(self):
        path, filter_ = QFileDialog.getSaveFileName(self, "Exporter l'image", "MantaLayers.png",
                     "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)")
        if not path:
            return
        dest = Path(path)
        if dest.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            dest = dest.with_suffix(".jpg" if "JPEG" in filter_ else ".webp" if "WebP" in filter_ else ".png")
        try:
            if self.document.width * self.document.height > 120_000_000:
                raise ValueError("Document trop grand pour l'export (> 120 millions de pixels)")
            image = Image.open(BytesIO(qimage_png(render_document(self.document)))).convert("RGBA")
            extension = dest.suffix.lower()
            if extension in (".jpg", ".jpeg"):
                base = Image.new("RGB", image.size, (255, 255, 255))
                base.paste(image, mask=image.getchannel("A"))
                base.save(dest, format="JPEG", quality=95)
            elif extension == ".webp":
                image.save(dest, format="WEBP", quality=95, method=4)
            else:
                image.save(dest, format="PNG", optimize=True)
            self.statusBar().showMessage(f"Export terminé : {dest}", 6000)
        except Exception as exc:
            QMessageBox.critical(self, "Export impossible", str(exc))

    def export_selected_layer(self):
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à enregistrer", 3000)
            return
        safe_name = "".join(character if character not in '<>:"/\\|?*' else "_"
                            for character in layer.name).strip() or "Calque"
        path, filter_ = QFileDialog.getSaveFileName(
            self, "Enregistrer le calque sous", f"{safe_name}.png",
            "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            destination = destination.with_suffix(
                ".jpg" if "JPEG" in filter_ else ".webp" if "WebP" in filter_ else ".png"
            )
        try:
            image = Image.open(BytesIO(qimage_png(item.pixmap().toImage()))).convert("RGBA")
            if destination.suffix.lower() in (".jpg", ".jpeg"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                background.save(destination, format="JPEG", quality=95)
            elif destination.suffix.lower() == ".webp":
                image.save(destination, format="WEBP", quality=95, method=4)
            else:
                image.save(destination, format="PNG", optimize=True)
            self.statusBar().showMessage(f"Calque enregistré : {destination}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement du calque impossible", str(exc))

    def update_title(self, *_):
        name = self.project_path.name if self.project_path else "Sans titre"
        modified = " *" if not self.undo_stack.isClean() else ""
        self.setWindowTitle(f"{name}{modified} — Manta Layers 0.1.0 | ReefKit")

    def update_zoom(self):
        self.zoom_label.setText(f"{self.canvas.transform().m11() * 100:.0f} %")

    def change_zoom(self, factor):
        now = self.canvas.transform().m11()
        if 0.08 <= now * factor <= 8:
            self.canvas.scale(factor, factor)
            self.update_zoom()

    def about(self):
        QMessageBox.about(self, "À propos de Manta Layers", """<h3>Manta Layers 0.1.0</h3>
        <p>Éditeur d'images local à calques · Univers Blue Shrimp / ReefKit.</p>
        <p>Images, textes droits, calques, transformations, historique, projets natifs et exports.</p>
        <p>Le texte courbé et les masques sont prévus pour les prochaines versions.</p>""")

    def dragEnterEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.image_paths_from_mime(event.mimeData())
        if paths:
            self._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def image_paths_from_mime(mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES]

    def closeEvent(self, event):
        if self.maybe_save():
            self.refreshing = True
            event.accept()
        else:
            event.ignore()
