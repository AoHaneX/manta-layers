"""Rows of the layer panel: layers (with their selection box) and folders.

The rows only build widgets and forward clicks to the main window, which owns
the document and every undoable change.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QWidget

from .icons import eye_icon, layer_kind_icon, lock_icon
from .model import Folder, Layer
from .widgets import LayerDragHandle

if TYPE_CHECKING:
    from .window import MainWindow

FOLDER_INDENT = 18
# Item data role telling folder rows from layer rows in the panel list.
FOLDER_ROLE = Qt.ItemDataRole.UserRole + 1
KIND_TOOLTIPS = {
    "text": "Calque texte", "image": "Calque image", "shape": "Forme",
    "animation": "Calque animé (GIF ou APNG)",
}


class FolderNameButton(QPushButton):
    """Folder name: a click selects nothing, a double click renames."""

    def __init__(self, window: MainWindow, folder: Folder):
        super().__init__(folder.name)
        self._window = window
        self._folder_id = folder.id
        self.setObjectName("layerName")
        self.setToolTip(f"{folder.name} · double-clic pour renommer")
        self.setFlat(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def mouseDoubleClickEvent(self, event):
        self._window.rename_folder(self._folder_id)
        event.accept()


def _row(indent: int = 0) -> tuple[QWidget, QHBoxLayout]:
    controls = QWidget()
    controls.setObjectName("layerRow")
    # Plain QWidgets only paint a style sheet background with this attribute.
    controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QHBoxLayout(controls)
    layout.setContentsMargins(3 + indent, 1, 3, 1)
    layout.setSpacing(3)
    return controls, layout


def _visibility_button(visible: bool, hide_tip: str, show_tip: str, on_click) -> QToolButton:
    button = QToolButton()
    button.setObjectName("layerAction")
    button.setCheckable(True)
    button.setChecked(visible)
    button.setIcon(eye_icon(visible))
    button.setIconSize(QSize(18, 18))
    button.setFixedSize(32, 27)
    button.setToolTip(hide_tip if visible else show_tip)
    button.clicked.connect(on_click)
    return button


def set_row_checked(controls: QWidget, checked: bool) -> None:
    """Highlight a row whose layer is part of the multiple selection."""
    controls.setProperty("checked", checked)
    controls.style().unpolish(controls)
    controls.style().polish(controls)


def build_layer_row(window: MainWindow, layer: Layer, checked: bool) -> QWidget:
    controls, layout = _row(FOLDER_INDENT if layer.folder else 0)
    drag_handle = LayerDragHandle(layer.id)
    drag_handle.setEnabled(not layer.locked)
    layout.addWidget(drag_handle)
    check = QCheckBox()
    check.setObjectName("layerCheck")
    check.setChecked(checked)
    check.setToolTip("Inclure dans la sélection multiple")
    check.setAccessibleName(f"Sélectionner le calque {layer.name}")
    check.toggled.connect(lambda state, layer_id=layer.id: window.set_layer_checked(layer_id, state))
    layout.addWidget(check)
    layout.addWidget(_visibility_button(
        layer.visible, "Masquer le calque", "Afficher le calque",
        lambda state, layer_id=layer.id: window.set_layer_visibility(layer_id, state),
    ))
    kind = QLabel()
    icon_kind = "animation" if layer.is_animated else layer.kind
    kind.setPixmap(layer_kind_icon(icon_kind))
    kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
    kind.setFixedSize(20, 27)
    kind.setToolTip(KIND_TOOLTIPS.get(icon_kind, "Calque"))
    layout.addWidget(kind)
    name = QPushButton(layer.name)
    name.setObjectName("layerName")
    name.setToolTip(f"{layer.name} · Ctrl+clic pour l'ajouter à la sélection multiple")
    name.setFlat(True)
    name.setMinimumWidth(0)
    name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    name.clicked.connect(lambda _checked=False, layer_id=layer.id: window.layer_name_clicked(layer_id))
    layout.addWidget(name, stretch=1)
    for symbol, tooltip, direction in (("▲", "Monter le calque", 1), ("▼", "Descendre le calque", -1)):
        button = QToolButton()
        button.setObjectName("layerAction")
        button.setText(symbol)
        button.setToolTip(tooltip)
        button.setFixedSize(30, 27)
        button.setEnabled(not layer.locked)
        button.clicked.connect(
            lambda _checked=False, layer_id=layer.id, delta=direction: window.reorder_layer(delta, layer_id)
        )
        layout.addWidget(button)
    lock = QToolButton()
    lock.setObjectName("layerAction")
    lock.setIcon(lock_icon(layer.locked))
    lock.setIconSize(QSize(18, 18))
    lock.setToolTip("Déverrouiller le calque" if layer.locked else "Verrouiller le calque")
    lock.setCheckable(True)
    lock.setChecked(layer.locked)
    lock.setFixedSize(32, 27)
    lock.clicked.connect(lambda _checked=False, layer_id=layer.id: window.toggle_lock(layer_id))
    layout.addWidget(lock)
    set_row_checked(controls, checked)
    return controls


def build_folder_row(window: MainWindow, folder: Folder, check_state: Qt.CheckState) -> QWidget:
    controls, layout = _row()
    drag_handle = LayerDragHandle(folder.id, kind="folder")
    drag_handle.setToolTip("Maintenir et glisser pour déplacer le dossier")
    layout.addWidget(drag_handle)
    check = QCheckBox()
    check.setObjectName("layerCheck")
    check.setTristate(check_state == Qt.CheckState.PartiallyChecked)
    check.setCheckState(check_state)
    check.setToolTip("Sélectionner tous les calques du dossier")
    check.setAccessibleName(f"Sélectionner les calques du dossier {folder.name}")
    # A click always toggles between "all" and "none" members. The state is read
    # at click time: the row is updated in place, not rebuilt, after each click.
    check.clicked.connect(lambda _checked=False, folder_id=folder.id: window.toggle_folder_checked(folder_id))
    layout.addWidget(check)
    layout.addWidget(_visibility_button(
        folder.visible, "Masquer le dossier", "Afficher le dossier",
        lambda state, folder_id=folder.id: window.set_folder_visibility(folder_id, state),
    ))
    toggle = QToolButton()
    toggle.setObjectName("layerAction")
    toggle.setText("▸" if folder.collapsed else "▾")
    toggle.setToolTip("Déplier le dossier" if folder.collapsed else "Replier le dossier")
    toggle.setFixedSize(30, 27)
    toggle.clicked.connect(lambda _checked=False, folder_id=folder.id: window.toggle_folder_collapsed(folder_id))
    layout.addWidget(toggle)
    kind = QLabel()
    kind.setPixmap(layer_kind_icon("folder"))
    kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
    kind.setFixedSize(20, 27)
    kind.setToolTip("Dossier de calques")
    layout.addWidget(kind)
    layout.addWidget(FolderNameButton(window, folder), stretch=1)
    set_row_checked(controls, check_state == Qt.CheckState.Checked)
    return controls
