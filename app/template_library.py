"""Library of element templates: bundled ones and those created by the user.

The dialog only chooses; the main window inserts the template, or opens it
for editing, as undoable or saved changes.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .builtin_templates import BUILTIN_TEMPLATES, builtin_template
from .dialogs import _dialog_buttons
from .graphics import qimage_png, render_document
from .model import Document
from .storage import open_project
from .templates import delete_template, duplicate_template, list_templates, rename_template, save_template

ENTRY_ROLE = Qt.ItemDataRole.UserRole


def builtin_thumbnail(document: Document) -> bytes:
    return qimage_png(render_document(document, QSize(320, 180)))


class TemplateLibraryDialog(QDialog):
    """Choose an element template to insert; manage the user's templates."""

    _builtin_icons: dict[str, QIcon] = {}

    def __init__(self, parent=None, directory: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Bibliothèque de modèles")
        self.setMinimumSize(680, 520)
        self.directory = directory
        self.action: str | None = None  # "insert" or "edit" once accepted
        layout = QVBoxLayout(self)
        hint = QLabel("Modèles d'éléments à insérer dans le projet : leurs calques restent séparés et modifiables. "
                      "Créez les vôtres depuis le panneau des calques (clic droit > Créer un modèle…).")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(180, 105))
        self.gallery.setGridSize(QSize(205, 150))
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.gallery.itemDoubleClicked.connect(lambda _item: self._choose("insert"))
        self.gallery.itemSelectionChanged.connect(self.update_actions)
        layout.addWidget(self.gallery, stretch=1)
        management = QHBoxLayout()
        self.rename_btn = QPushButton("Renommer")
        self.edit_btn = QPushButton("Modifier")
        self.edit_btn.setToolTip("Ouvrir le modèle pour le modifier ; Sauvegarder le projet l'enregistre")
        self.duplicate_btn = QPushButton("Dupliquer")
        self.duplicate_btn.setToolTip("Copier le modèle dans votre bibliothèque (y compris un modèle fourni)")
        self.delete_btn = QPushButton("Supprimer")
        self.delete_btn.setProperty("variant", "danger")
        for button, slot in ((self.rename_btn, self.rename_selected), (self.edit_btn, lambda: self._choose("edit")),
                             (self.duplicate_btn, self.duplicate_selected), (self.delete_btn, self.delete_selected)):
            button.clicked.connect(slot)
            management.addWidget(button)
        management.addStretch(1)
        layout.addLayout(management)
        self.buttons = _dialog_buttons(self, "Insérer")
        self.insert_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.buttons.accepted.disconnect()
        self.buttons.accepted.connect(lambda: self._choose("insert"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Fermer")
        layout.addWidget(self.buttons)
        self.refresh()

    # --- Gallery ---------------------------------------------------------------------------

    def refresh(self, select: object = None) -> None:
        self.gallery.clear()
        for key, (name, _build) in BUILTIN_TEMPLATES.items():
            icon = self._builtin_icons.get(key)
            if icon is None:
                pixmap = QPixmap()
                pixmap.loadFromData(builtin_thumbnail(builtin_template(key)))
                icon = self._builtin_icons[key] = QIcon(pixmap)
            self._add(icon, f"{name}\nfourni avec Manta Layers", ("builtin", key), select)
        for info in list_templates(self.directory, kind="elements"):
            pixmap = QPixmap()
            if info.thumbnail:
                pixmap.loadFromData(info.thumbnail)
            self._add(QIcon(pixmap), f"{info.name}\n{info.width} × {info.height} px", ("user", info.path), select)
        if self.gallery.currentItem() is None and self.gallery.count():
            self.gallery.setCurrentRow(0)
        self.update_actions()

    def _add(self, icon: QIcon, text: str, entry, select) -> None:
        item = QListWidgetItem(icon, text)
        item.setData(ENTRY_ROLE, entry)
        item.setToolTip(text.splitlines()[0])
        self.gallery.addItem(item)
        if select is not None and entry == select:
            self.gallery.setCurrentItem(item)

    def selected_entry(self):
        item = self.gallery.currentItem()
        return item.data(ENTRY_ROLE) if item else None

    def update_actions(self, *_args) -> None:
        entry = self.selected_entry()
        user = entry is not None and entry[0] == "user"
        for button in (self.rename_btn, self.edit_btn, self.delete_btn):
            button.setEnabled(user)
        self.duplicate_btn.setEnabled(entry is not None)
        self.insert_button.setEnabled(entry is not None)

    def selected_name(self) -> str:
        item = self.gallery.currentItem()
        return item.text().splitlines()[0] if item else ""

    def load_selected(self) -> Document:
        """Document of the selected template; raises ValueError for a damaged or missing file."""
        kind, value = self.selected_entry()
        if kind == "builtin":
            return builtin_template(value)
        return open_project(value)

    def _choose(self, action: str) -> None:
        if self.selected_entry() is None:
            return
        self.action = action
        self.accept()

    # --- Management (errors are reported, never silent) --------------------------------------

    def _warn(self, exc: Exception) -> None:
        QMessageBox.warning(self, "Action impossible", str(exc))

    def rename_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None or entry[0] != "user":
            return
        name, accepted = QInputDialog.getText(self, "Renommer le modèle", "Nom :", text=self.selected_name())
        if not accepted or not name.strip():
            return
        try:
            rename_template(entry[1], name)
        except (OSError, ValueError) as exc:
            self._warn(exc)
        self.refresh(entry)

    def duplicate_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        try:
            if entry[0] == "builtin":
                document = builtin_template(entry[1])
                path = save_template(document, self.selected_name(), builtin_thumbnail(document),
                                     self.directory, kind="elements")
            else:
                path = duplicate_template(entry[1], self.directory)
        except (OSError, ValueError) as exc:
            self._warn(exc)
            self.refresh()
            return
        self.refresh(("user", path))

    def delete_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None or entry[0] != "user":
            return
        answer = QMessageBox.question(
            self, "Supprimer le modèle", f"Supprimer définitivement le modèle « {self.selected_name()} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_template(entry[1])
        except OSError as exc:
            self._warn(exc)
        self.refresh()
