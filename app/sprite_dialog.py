"""Spritesheet slicer: lay a grid over a sheet, choose cells, export PNGs or add them as layers.

Pixels are never resampled: crops are exact and every preview is scaled with
nearest neighbour, so pixel art keeps its look.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtCore import QLineF, QRectF, QSize, Qt, QTimer
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

from .graphics import RENDER_ERRORS, checker_brush, pil_to_qimage
from .imaging import SpriteGrid, extract_sprites, grid_shape, iter_cells
from .model import IMPORT_FORMATS, MAX_DIMENSION, MAX_LAYERS, MAX_PIXELS
from .paths import safe_file_stem
from .theme import COLORS

if TYPE_CHECKING:
    from .window import MainWindow

PREVIEW = 420
MAX_LISTED_CELLS = 1024  # thumbnails beyond this are not listed (the grid is probably wrong)
# Beyond this many cells the preview only draws the grid (no per-cell inspection, no
# thumbnails) and exporting or adding the sprites asks for a confirmation first.
MAX_DETAILED_CELLS = 10_000
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
    # The prefix is a layer name, such as "Token : …": it must become a valid file name.
    prefix = safe_file_stem(prefix, "sprite")
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
        # Grid and options of the last refresh: the listed cells and the extraction both follow them.
        self._grid: SpriteGrid | None = None
        self._grid_error = ""
        self._skip_empty = True
        self.cell_count = 0  # cells offered for extraction (non-empty ones when empty cells are skipped)
        self.detailed = True  # False when the preview only shows the grid
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
        # Typing "16" must not refresh for the intermediate "1" (a huge grid on a big sheet).
        spin.setKeyboardTracking(False)
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
        except RENDER_ERRORS as exc:
            QMessageBox.warning(self, "Image illisible", str(exc))

    def use_selected_layer(self) -> None:
        document = self.window_.document
        layer = document.layer(self.window_.selected_id)
        if layer is None or layer.kind != "image":
            QMessageBox.information(self, "Découper une spritesheet", "Sélectionnez un calque image.")
            return
        try:
            with Image.open(BytesIO(document.assets[layer.image_asset()]), formats=("PNG",)) as source:
                self.set_sheet(source, layer.name)
        except RENDER_ERRORS as exc:
            QMessageBox.warning(self, "Image illisible", f"L'image du calque « {layer.name} » est illisible : {exc}")

    # --- Grid and cells ----------------------------------------------------------------------

    def refresh(self) -> None:
        self.cells.blockSignals(True)
        self.cells.clear()
        ratio = self.preview.devicePixelRatioF()
        canvas = QPixmap(round(PREVIEW * ratio), round(PREVIEW * ratio))  # stored at the screen density
        canvas.setDevicePixelRatio(ratio)
        painter = QPainter(canvas)
        painter.fillRect(QRectF(0, 0, PREVIEW, PREVIEW), checker_brush())
        self._grid, self._grid_error, self._skip_empty = None, "", self.skip_empty.isChecked()
        self.cell_count, self.detailed = 0, True
        if self.sheet is not None:
            scale = min(PREVIEW / self.sheet.width, PREVIEW / self.sheet.height)
            target = QRectF(0, 0, self.sheet.width * scale, self.sheet.height * scale)
            painter.drawImage(target, pil_to_qimage(self.sheet))  # default painter: nearest neighbour
            grid = self.grid()
            try:
                columns, rows = grid_shape(self.sheet.size, grid)
                self._grid = grid
            except ValueError as exc:
                columns = rows = 0
                self._grid_error = str(exc)
            if columns * rows > MAX_DETAILED_CELLS:
                # Too many cells to inspect while editing: lines only, emptiness unknown.
                self.detailed = False
                self.cell_count = columns * rows
                self._draw_grid_lines(painter, grid, columns, rows, scale)
            elif self._grid is not None:
                for row, column, box, cell, bounds in iter_cells(self.sheet, grid):
                    empty = bounds is None
                    rect = QRectF(box[0] * scale, box[1] * scale,
                                  (box[2] - box[0]) * scale, (box[3] - box[1]) * scale)
                    painter.setPen(QPen(QColor(COLORS["disabled"] if empty else COLORS["copper"]), 1))
                    painter.drawRect(rect)
                    if empty and self._skip_empty:
                        continue
                    self.cell_count += 1
                    if self.cell_count <= MAX_LISTED_CELLS:
                        self._add_cell(row, column, cell)
        painter.end()
        self.preview.setPixmap(canvas)
        self.cells.blockSignals(False)
        self._update_summary()

    @staticmethod
    def _draw_grid_lines(painter: QPainter, grid: SpriteGrid, columns: int, rows: int, scale: float) -> None:
        """Outline of every cell drawn with one line per cell edge, not one rectangle per cell."""
        painter.setPen(QPen(QColor(COLORS["copper"]), 1))
        step_x, step_y = grid.cell_width + grid.spacing_x, grid.cell_height + grid.spacing_y
        top, bottom = grid.offset_y, grid.offset_y + rows * step_y - grid.spacing_y
        left, right = grid.offset_x, grid.offset_x + columns * step_x - grid.spacing_x
        # Sets: without spacing, the right edge of a cell is the left edge of the next one.
        xs = {left + column * step_x + edge for column in range(columns) for edge in (0, grid.cell_width)}
        ys = {top + row * step_y + edge for row in range(rows) for edge in (0, grid.cell_height)}
        painter.drawLines([QLineF(x * scale, top * scale, x * scale, bottom * scale) for x in sorted(xs)]
                          + [QLineF(left * scale, y * scale, right * scale, y * scale) for y in sorted(ys)])

    def _add_cell(self, row: int, column: int, cell: Image.Image) -> None:
        ratio = self.cells.devicePixelRatioF()
        side = round(48 * ratio)  # 48 logical pixels, stored at the screen density
        pixmap = QPixmap.fromImage(pil_to_qimage(cell)).scaled(
            side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        pixmap.setDevicePixelRatio(ratio)
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

    def chosen_count(self) -> int:
        """Sprites the output would produce (an upper bound when the preview only shows the grid)."""
        return max(0, self.cell_count - len(self._unchecked()))

    def chosen_sprites(self) -> list[tuple[int, int, Image.Image]]:
        """Checked cells (all cells beyond the listed ones), optionally trimmed."""
        if self.sheet is None or self._grid is None:
            return []
        unchecked = self._unchecked()
        return [(row, column, image) for row, column, image
                in extract_sprites(self.sheet, self._grid, self.trim.isChecked(), self._skip_empty)
                if (row, column) not in unchecked]

    def _update_summary(self) -> None:
        if self.sheet is None:
            self.summary.setText("Importez une spritesheet pour définir la grille.")
            ready = False
        elif self._grid_error:
            self.summary.setText(self._grid_error)
            ready = False
        else:
            count = self.chosen_count()
            text = f"{self.sheet.width} × {self.sheet.height} px · {self.cell_count} cellule(s) · "
            if self.detailed:
                text += f"{count} sprite(s) à extraire"
                hidden = max(0, self.cell_count - MAX_LISTED_CELLS)
                if hidden:
                    text += f" · {hidden} cellule(s) non affichée(s), toujours extraites"
            else:
                text += (f"jusqu'à {count} sprite(s) à extraire · plus de {MAX_DETAILED_CELLS} cellules : "
                         "aperçu limité à la grille, sans vignettes")
            self.summary.setText(text)
            ready = count > 0
        self.export_button.setEnabled(ready)
        self.layers_button.setEnabled(ready)

    def confirm_large_output(self) -> bool:
        """Ask before producing a very large number of files or layers."""
        count = self.chosen_count()
        if count <= MAX_DETAILED_CELLS:
            return True
        answer = QMessageBox.question(
            self, "Découper une spritesheet",
            f"La grille donne jusqu'à {count} sprites. L'opération peut être longue et créer autant "
            "de fichiers ou de calques.\n\nContinuer ?")
        return answer == QMessageBox.StandardButton.Yes

    # --- Output ------------------------------------------------------------------------------

    def export(self) -> list[Path]:
        if not self.confirm_large_output():
            return []
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
        room = MAX_LAYERS - len(self.window_.document.layers)
        if self.chosen_count() > room:
            QMessageBox.warning(
                self, "Trop de sprites",
                f"Jusqu'à {self.chosen_count()} sprites pour {max(0, room)} calque(s) encore possibles "
                f"(maximum {MAX_LAYERS} par projet).\n\n"
                "Agrandissez les cellules, décochez des sprites ou exportez-les en PNG.")
            return False
        if not self.confirm_large_output():
            return False
        sprites = self.chosen_sprites()
        if not sprites:
            return False
        return self.window_.add_sprite_layers(sprites, self.sheet_name)
