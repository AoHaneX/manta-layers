"""Spritesheet slicer: lay a grid over a sheet, choose cells, export PNGs or add them as layers.

Pixels are never resampled: crops are exact and every preview is scaled with
nearest neighbour, so pixel art keeps its look.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .graphics import checker_brush, pil_to_qimage
from .imaging import SpriteGrid, alpha_bounds, grid_cells
from .model import IMPORT_FORMATS, MAX_DIMENSION, MAX_PIXELS
from .theme import COLORS

if TYPE_CHECKING:
    from .window import MainWindow

PREVIEW = 420
MAX_LISTED_CELLS = 1024  # thumbnails beyond this are not listed (the grid is probably wrong)
CELL_ROLE = Qt.ItemDataRole.UserRole


def unique_path(directory: Path, stem: str) -> Path:
    """``stem.png`` in ``directory``, numbered when a file with that name already exists."""
    candidate = directory / f"{stem}.png"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{index}.png"
        index += 1
    return candidate


def export_sprites(sprites, directory: Path, prefix: str) -> list[Path]:
    """Write sprites (row, column, image) as PNGs named prefix_row_column, never overwriting a file."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for row, column, image in sprites:
        path = unique_path(directory, f"{prefix}_{row + 1:02d}_{column + 1:02d}")
        image.save(path, format="PNG")
        written.append(path)
    return written


class SpriteSheetDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Découper une spritesheet")
        self.setMinimumSize(900, 600)
        self.sheet: Image.Image | None = None
        self.sheet_name = "sprite"
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW, PREVIEW)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.preview)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        left.addWidget(self.summary)
        left.addStretch(1)
        layout.addLayout(left)

        right = QVBoxLayout()
        sources = QWidget()
        sources_layout = QHBoxLayout(sources)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("Importer une spritesheet…")
        choose.setProperty("variant", "primary")
        choose.clicked.connect(self.choose_sheet)
        from_layer = QPushButton("Calque sélectionné")
        from_layer.setToolTip("Découper l'image source du calque image sélectionné")
        from_layer.clicked.connect(self.use_selected_layer)
        sources_layout.addWidget(choose)
        sources_layout.addWidget(from_layer)
        right.addWidget(sources)
        form = QFormLayout()
        self.cell_width = self._spin(1, 32, " px")
        self.cell_height = self._spin(1, 32, " px")
        self.columns = self._spin(0, 0, "", "auto")
        self.rows = self._spin(0, 0, "", "auto")
        self.spacing_x = self._spin(0, 0, " px")
        self.spacing_y = self._spin(0, 0, " px")
        self.offset_x = self._spin(0, 0, " px")
        self.offset_y = self._spin(0, 0, " px")
        for label, spin in (("Largeur des cellules", self.cell_width), ("Hauteur des cellules", self.cell_height),
                            ("Colonnes", self.columns), ("Lignes", self.rows),
                            ("Espacement horizontal", self.spacing_x), ("Espacement vertical", self.spacing_y),
                            ("Décalage horizontal", self.offset_x), ("Décalage vertical", self.offset_y)):
            form.addRow(label, spin)
        self.trim = QCheckBox("Rogner les marges transparentes de chaque sprite")
        self.skip_empty = QCheckBox("Ignorer les cellules vides")
        self.skip_empty.setChecked(True)
        form.addRow(self.trim)
        form.addRow(self.skip_empty)
        right.addLayout(form)
        selection_row = QHBoxLayout()
        for text, state in (("Tout cocher", True), ("Tout décocher", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, state=state: self.check_all(state))
            selection_row.addWidget(button)
        selection_row.addStretch(1)
        right.addLayout(selection_row)
        self.cells = QListWidget()
        self.cells.setViewMode(QListView.ViewMode.IconMode)
        self.cells.setIconSize(QSize(48, 48))
        self.cells.setGridSize(QSize(68, 76))
        self.cells.setResizeMode(QListView.ResizeMode.Adjust)
        self.cells.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cells.itemChanged.connect(lambda _item: self._update_summary())
        right.addWidget(self.cells, stretch=1)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("Exporter en PNG…")
        self.export_button.setProperty("variant", "primary")
        self.export_button.clicked.connect(self.export)
        self.layers_button = QPushButton("Ajouter comme calques")
        self.layers_button.setToolTip("Chaque sprite devient un calque, rangé dans un dossier")
        self.layers_button.clicked.connect(self.add_as_layers)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        for button in (self.export_button, self.layers_button, close):
            buttons.addWidget(button)
        right.addLayout(buttons)
        layout.addLayout(right, stretch=1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(150)
        self.refresh_timer.timeout.connect(self.refresh)
        for spin in (self.cell_width, self.cell_height, self.columns, self.rows,
                     self.spacing_x, self.spacing_y, self.offset_x, self.offset_y):
            spin.valueChanged.connect(lambda _value: self.refresh_timer.start())
        self.skip_empty.toggled.connect(lambda _checked: self.refresh_timer.start())
        self.trim.toggled.connect(lambda _checked: self._update_summary())
        self.refresh()

    @staticmethod
    def _spin(minimum: int, value: int, suffix: str, special: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, MAX_DIMENSION)
        spin.setValue(value)
        spin.setSuffix(suffix)
        if special:
            spin.setSpecialValueText(special)
        return spin

    def grid(self) -> SpriteGrid:
        return SpriteGrid(self.cell_width.value(), self.cell_height.value(), self.columns.value(), self.rows.value(),
                          self.spacing_x.value(), self.spacing_y.value(), self.offset_x.value(), self.offset_y.value())

    # --- Sources -------------------------------------------------------------------------------

    def set_sheet(self, image: Image.Image, name: str) -> None:
        self.sheet = image.convert("RGBA")
        self.sheet_name = name or "sprite"
        self.refresh()

    def choose_sheet(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer une spritesheet", self.window_.initial_path("import"),
                                              "Images (*.png *.gif *.bmp *.webp *.jpg *.jpeg)")
        if not path:
            return
        self.window_.remember_directory("import", Path(path).parent)
        try:
            with Image.open(path, formats=IMPORT_FORMATS) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("Image trop grande (maximum 67 mégapixels)")
                image.load()
                self.set_sheet(image, Path(path).stem)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            QMessageBox.warning(self, "Image illisible", str(exc))

    def use_selected_layer(self) -> None:
        document = self.window_.document
        layer = document.layer(self.window_.selected_id)
        if layer is None or layer.kind != "image":
            QMessageBox.information(self, "Découper une spritesheet", "Sélectionnez un calque image.")
            return
        with Image.open(BytesIO(document.assets[layer.asset]), formats=("PNG",)) as source:
            self.set_sheet(source, layer.name)

    # --- Grid and cells ----------------------------------------------------------------------

    def refresh(self) -> None:
        self.cells.blockSignals(True)
        self.cells.clear()
        canvas = QPixmap(PREVIEW, PREVIEW)
        painter = QPainter(canvas)
        painter.fillRect(canvas.rect(), checker_brush())
        self.cell_boxes = []
        if self.sheet is not None:
            try:
                cells = grid_cells(self.sheet.size, self.grid())
            except ValueError as exc:
                cells = []
                self.summary.setText(str(exc))
            scale = min(PREVIEW / self.sheet.width, PREVIEW / self.sheet.height)
            target = QRectF(0, 0, self.sheet.width * scale, self.sheet.height * scale)
            painter.drawImage(target, pil_to_qimage(self.sheet))  # default painter: nearest neighbour
            pen = QPen(QColor(COLORS["copper"]), 1)
            painter.setPen(pen)
            for row, column, box in cells:
                cell = self.sheet.crop(box)
                empty = alpha_bounds(cell) is None
                rect = QRectF(box[0] * scale, box[1] * scale, (box[2] - box[0]) * scale, (box[3] - box[1]) * scale)
                painter.setPen(QPen(QColor(COLORS["disabled"] if empty else COLORS["copper"]), 1))
                painter.drawRect(rect)
                if empty and self.skip_empty.isChecked():
                    continue
                self.cell_boxes.append((row, column, box))
                if len(self.cell_boxes) <= MAX_LISTED_CELLS:
                    self._add_cell(row, column, cell)
        painter.end()
        self.preview.setPixmap(canvas)
        self.cells.blockSignals(False)
        self._update_summary()

    def _add_cell(self, row: int, column: int, cell: Image.Image) -> None:
        pixmap = QPixmap.fromImage(pil_to_qimage(cell)).scaled(
            48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        item = QListWidgetItem(QIcon(pixmap), f"{row + 1}·{column + 1}")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(CELL_ROLE, (row, column))
        self.cells.addItem(item)

    def check_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.cells.blockSignals(True)
        for index in range(self.cells.count()):
            self.cells.item(index).setCheckState(state)
        self.cells.blockSignals(False)
        self._update_summary()

    def _unchecked(self) -> set[tuple[int, int]]:
        return {self.cells.item(index).data(CELL_ROLE) for index in range(self.cells.count())
                if self.cells.item(index).checkState() != Qt.CheckState.Checked}

    def chosen_sprites(self) -> list[tuple[int, int, Image.Image]]:
        """Checked cells (all cells beyond the listed ones), optionally trimmed."""
        unchecked = self._unchecked()
        sprites = []
        for row, column, box in self.cell_boxes:
            if (row, column) in unchecked:
                continue
            cell = self.sheet.crop(box)
            bounds = alpha_bounds(cell)
            if self.trim.isChecked() and bounds is not None:
                cell = cell.crop(bounds)
            sprites.append((row, column, cell))
        return sprites

    def _update_summary(self) -> None:
        if self.sheet is None:
            self.summary.setText("Importez une spritesheet pour définir la grille.")
            ready = False
        else:
            unchecked = self._unchecked()
            count = sum(1 for row, column, _box in self.cell_boxes if (row, column) not in unchecked)
            hidden = max(0, len(self.cell_boxes) - MAX_LISTED_CELLS)
            text = (f"{self.sheet.width} × {self.sheet.height} px · {len(self.cell_boxes)} cellule(s) · "
                    f"{count} sprite(s) à extraire")
            if hidden:
                text += f" · {hidden} cellule(s) non affichée(s), toujours extraites"
            self.summary.setText(text)
            ready = count > 0
        self.export_button.setEnabled(ready)
        self.layers_button.setEnabled(ready)

    # --- Output ------------------------------------------------------------------------------

    def export(self) -> list[Path]:
        directory = QFileDialog.getExistingDirectory(self, "Dossier de destination",
                                                     self.window_.initial_path("sprites"))
        if not directory:
            return []
        try:
            written = export_sprites(self.chosen_sprites(), Path(directory), self.sheet_name)
        except OSError as exc:
            QMessageBox.critical(self, "Export impossible", str(exc))
            return []
        self.window_.remember_directory("sprites", directory)
        QMessageBox.information(self, "Sprites exportés", f"{len(written)} fichier(s) PNG enregistré(s) dans\n{directory}")
        return written

    def add_as_layers(self) -> bool:
        sprites = self.chosen_sprites()
        if not sprites:
            return False
        return self.window_.add_sprite_layers(sprites, self.sheet_name)
