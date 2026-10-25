"""Boîtes de dialogue de création et de dimensionnement des documents."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QInputDialog, QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .model import MAX_DIMENSION, Document
from .templates import (
    delete_template, duplicate_template, instantiate_template, list_templates, rename_template,
)


def _dimension_input(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(1, MAX_DIMENSION)
    spin.setValue(value)
    spin.setSuffix(" px")
    return spin


def _dialog_buttons(dialog: QDialog, accept_label: str) -> QDialogButtonBox:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    accept = buttons.button(QDialogButtonBox.StandardButton.Ok)
    accept.setText(accept_label)
    accept.setProperty("variant", "primary")
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


class NewProjectDialog(QDialog):
    """Création d'un document vierge ou sélection d'un modèle local."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau projet")
        self.setMinimumSize(650, 500)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        blank = QWidget()
        blank_layout = QVBoxLayout(blank)
        blank_form = QFormLayout()
        self.width_input = _dimension_input(1280)
        self.height_input = _dimension_input(720)
        self.background_input = QComboBox()
        self.background_input.addItems(["Transparent", "Blanc", "Noir"])
        blank_form.addRow("Largeur", self.width_input)
        blank_form.addRow("Hauteur", self.height_input)
        blank_form.addRow("Fond", self.background_input)
        blank_layout.addLayout(blank_form)
        blank_layout.addStretch(1)
        self.tabs.addTab(blank, "Projet vierge")

        library = QWidget()
        library_layout = QVBoxLayout(library)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.ViewMode.IconMode)
        self.gallery.setIconSize(QSize(180, 105))
        self.gallery.setGridSize(QSize(205, 150))
        self.gallery.setResizeMode(QListView.ResizeMode.Adjust)
        self.gallery.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.gallery.itemDoubleClicked.connect(lambda _item: self.accept())
        library_layout.addWidget(self.gallery, stretch=1)
        management = QHBoxLayout()
        self.rename_btn = QPushButton("Renommer")
        self.duplicate_btn = QPushButton("Dupliquer")
        self.delete_btn = QPushButton("Supprimer")
        self.delete_btn.setProperty("variant", "danger")
        self.rename_btn.clicked.connect(self.rename_selected)
        self.duplicate_btn.clicked.connect(self.duplicate_selected)
        self.delete_btn.clicked.connect(self.delete_selected)
        management.addWidget(self.rename_btn)
        management.addWidget(self.duplicate_btn)
        management.addWidget(self.delete_btn)
        management.addStretch(1)
        library_layout.addLayout(management)
        self.tabs.addTab(library, "Depuis un modèle")

        self.buttons = _dialog_buttons(self, "Créer")
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        layout.addWidget(self.buttons)
        self.tabs.currentChanged.connect(self.update_actions)
        self.gallery.itemSelectionChanged.connect(self.update_actions)
        self.refresh_gallery()

    def refresh_gallery(self, selected_path: Path | None = None):
        self.gallery.clear()
        for info in list_templates():
            pixmap = QPixmap()
            if info.thumbnail:
                pixmap.loadFromData(info.thumbnail)
            item = QListWidgetItem(QIcon(pixmap), f"{info.name}\n{info.width} × {info.height} px")
            item.setData(Qt.ItemDataRole.UserRole, str(info.path))
            item.setToolTip(info.name)
            self.gallery.addItem(item)
            if selected_path is not None and info.path == selected_path:
                self.gallery.setCurrentItem(item)
        self.update_actions()

    def selected_template(self) -> Path | None:
        item = self.gallery.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def update_actions(self, *_args):
        selected = self.selected_template() is not None
        for button in (self.rename_btn, self.duplicate_btn, self.delete_btn):
            button.setEnabled(selected)
        self.create_button.setEnabled(self.tabs.currentIndex() == 0 or selected)

    def rename_selected(self):
        path = self.selected_template()
        item = self.gallery.currentItem()
        if path is None or item is None:
            return
        current_name = item.text().splitlines()[0]
        name, accepted = QInputDialog.getText(self, "Renommer le modèle", "Nom :", text=current_name)
        if accepted and name.strip():
            rename_template(path, name)
            self.refresh_gallery(path)

    def duplicate_selected(self):
        path = self.selected_template()
        if path is not None:
            self.refresh_gallery(duplicate_template(path))

    def delete_selected(self):
        path = self.selected_template()
        item = self.gallery.currentItem()
        if path is None or item is None:
            return
        name = item.text().splitlines()[0]
        answer = QMessageBox.question(
            self, "Supprimer le modèle",
            f"Supprimer définitivement le modèle « {name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            delete_template(path)
            self.refresh_gallery()

    def document(self) -> Document:
        if self.tabs.currentIndex() == 1:
            return instantiate_template(self.selected_template())
        background = {
            "Transparent": None, "Blanc": "#FFFFFF", "Noir": "#000000"
        }[self.background_input.currentText()]
        return Document(self.width_input.value(), self.height_input.value(), background)


class ResizeDocumentDialog(QDialog):
    """Largeur et hauteur finales du document, saisies dans une seule fenêtre."""

    def __init__(self, width: int, height: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dimensions du document")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.width_input = _dimension_input(width)
        self.height_input = _dimension_input(height)
        form.addRow("Largeur finale", self.width_input)
        form.addRow("Hauteur finale", self.height_input)
        layout.addLayout(form)
        layout.addWidget(_dialog_buttons(self, "Appliquer"))

    def dimensions(self) -> tuple[int, int]:
        return self.width_input.value(), self.height_input.value()
