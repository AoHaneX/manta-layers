"""Token creator: frame an illustration, preview it, export a PNG or add it as a layer."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .graphics import checker_brush, pil_to_qimage, render_layers_region
from .model import IMPORT_FORMATS, MAX_PIXELS
from .theme import COLORS
from .tokens import FRAMES, MAX_SIZE, MIN_SIZE, TokenSettings, max_border, render_token

if TYPE_CHECKING:
    from .window import MainWindow

PREVIEW = 320


class TokenPreview(QLabel):
    """Preview on a checkerboard; dragging moves the portrait, the wheel zooms."""

    def __init__(self, dialog: TokenDialog):
        super().__init__()
        self.dialog = dialog
        self.setFixedSize(PREVIEW, PREVIEW)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._last: QPointF | None = None
        # Zoom kept as a float between wheel events: fine wheels (touchpads, high resolution
        # mice) move by less than 1 % per event, which rounding alone would always cancel.
        self._zoom: float | None = None

    def mousePressEvent(self, event):
        self._last = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        delta = event.position() - self._last
        self._last = event.position()
        self.dialog.shift_portrait(delta.x(), delta.y())

    def mouseReleaseEvent(self, event):
        self._last = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            slider = self.dialog.zoom
            # Start again from the slider when it was moved by something else since the last event.
            zoom = self._zoom if self._zoom is not None and round(self._zoom) == slider.value() else slider.value()
            self._zoom = max(slider.minimum(), min(slider.maximum(), zoom * 1.1 ** steps))
            slider.setValue(round(self._zoom))
        event.accept()


class TokenDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle("Créateur de tokens")
        self.source: Image.Image | None = None
        self.source_name = "token"
        layout = QHBoxLayout(self)
        preview_column = QVBoxLayout()
        self.preview = TokenPreview(self)
        preview_column.addWidget(self.preview)
        hint = QLabel("Glissez l'aperçu pour cadrer · molette pour zoomer")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_column.addWidget(hint)
        preview_column.addStretch(1)
        layout.addLayout(preview_column)

        form_column = QVBoxLayout()
        form = QFormLayout()
        sources = QWidget()
        sources_layout = QHBoxLayout(sources)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("Choisir une image…")
        choose.clicked.connect(self.choose_image)
        from_layer = QPushButton("Calque sélectionné")
        from_layer.setToolTip("Utiliser le rendu du calque sélectionné")
        from_layer.clicked.connect(self.use_selected_layer)
        sources_layout.addWidget(choose)
        sources_layout.addWidget(from_layer)
        form.addRow("Illustration", sources)
        self.frame = QComboBox()
        for key, label in FRAMES.items():
            self.frame.addItem(label, key)
        form.addRow("Cadre", self.frame)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(MIN_SIZE, MAX_SIZE)
        self.size_spin.setSingleStep(64)
        self.size_spin.setValue(512)
        self.size_spin.setSuffix(" px")
        form.addRow("Taille du token", self.size_spin)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(20, 400)
        self.zoom.setValue(100)
        self.zoom.setToolTip("Zoom de l'illustration (%)")
        form.addRow("Zoom", self.zoom)
        self.offset_x = QDoubleSpinBox()
        self.offset_y = QDoubleSpinBox()
        for spin in (self.offset_x, self.offset_y):
            spin.setRange(-MAX_SIZE, MAX_SIZE)
            spin.setDecimals(0)
            spin.setSuffix(" px")
        form.addRow("Décalage X", self.offset_x)
        form.addRow("Décalage Y", self.offset_y)
        self.border_color = COLORS["copper"]
        self.color_button = QPushButton()
        self.color_button.setFixedSize(QSize(60, 30))
        self.color_button.setToolTip("Couleur de la bordure")
        self.color_button.clicked.connect(self.choose_color)
        form.addRow("Couleur de bordure", self.color_button)
        self.border_width = QSpinBox()
        self.border_width.setRange(0, 256)
        self.border_width.setValue(16)
        self.border_width.setSuffix(" px")
        form.addRow("Épaisseur de bordure", self.border_width)
        # The thickest border depends on the frame and the size (the thick frame doubles it).
        self.frame.currentIndexChanged.connect(self._update_border_limit)
        self.size_spin.valueChanged.connect(self._update_border_limit)
        self._update_border_limit()
        self.pixel_art = QCheckBox("Illustration en pixel art (sans lissage)")
        form.addRow("Mise à l'échelle", self.pixel_art)
        form_column.addLayout(form)
        form_column.addStretch(1)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("Exporter en PNG…")
        self.export_button.setProperty("variant", "primary")
        self.export_button.clicked.connect(self.export_png)
        self.add_button = QPushButton("Ajouter au projet")
        self.add_button.clicked.connect(self.add_to_project)
        close = QPushButton("Fermer")
        close.clicked.connect(self.reject)
        for button in (self.export_button, self.add_button, close):
            buttons.addWidget(button)
        form_column.addLayout(buttons)
        layout.addLayout(form_column, stretch=1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(60)
        self.refresh_timer.timeout.connect(self.update_preview)
        for signal in (self.frame.currentIndexChanged, self.size_spin.valueChanged, self.zoom.valueChanged,
                       self.offset_x.valueChanged, self.offset_y.valueChanged, self.border_width.valueChanged,
                       self.pixel_art.toggled):
            signal.connect(lambda *_args: self.refresh_timer.start())
        self._show_color()
        self.update_preview()

    # --- Sources ---------------------------------------------------------------------------

    def set_source(self, image: Image.Image, name: str) -> None:
        self.source = image.convert("RGBA")
        self.source_name = name or "token"
        self.offset_x.setValue(0)
        self.offset_y.setValue(0)
        self.zoom.setValue(100)
        self.update_preview()

    def choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une illustration", self.window_.initial_path("import"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if not path:
            return
        self.window_.remember_directory("import", Path(path).parent)
        try:
            with Image.open(path, formats=IMPORT_FORMATS) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError("Image trop grande (maximum 67 mégapixels)")
                image.load()
                self.set_source(image, Path(path).stem)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            QMessageBox.warning(self, "Image illisible", str(exc))

    def use_selected_layer(self) -> None:
        layer = self.window_.document.layer(self.window_.selected_id)
        rendered = render_layers_region(self.window_.document, [layer.id]) if layer else None
        if layer is None or rendered is None:
            QMessageBox.information(self, "Créateur de tokens", "Sélectionnez un calque visible.")
            return
        self.set_source(rendered[0], layer.name)

    # --- Settings ----------------------------------------------------------------------------

    def settings(self, size: int | None = None) -> TokenSettings:
        """Current settings; for a preview of ``size`` px, offsets and border scale with it."""
        full = self.size_spin.value()
        ratio = (size or full) / full
        return TokenSettings(
            size=size or full, frame=self.frame.currentData(), zoom=self.zoom.value() / 100,
            offset_x=self.offset_x.value() * ratio, offset_y=self.offset_y.value() * ratio,
            border_color=self.border_color,
            border_width=min(round(self.border_width.value() * ratio),
                             max_border(size or full, self.frame.currentData())),
            pixel_art=self.pixel_art.isChecked(),
        )

    def _update_border_limit(self) -> None:
        # Lowering the maximum also lowers a value above it, which refreshes the preview.
        self.border_width.setMaximum(max_border(self.size_spin.value(), self.frame.currentData()))

    def shift_portrait(self, dx: float, dy: float) -> None:
        ratio = self.size_spin.value() / PREVIEW
        self.offset_x.setValue(self.offset_x.value() + dx * ratio)
        self.offset_y.setValue(self.offset_y.value() + dy * ratio)

    def choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.border_color), self, "Couleur de bordure")
        if color.isValid():
            self.border_color = color.name().upper()
            self._show_color()
            self.update_preview()

    def _show_color(self) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {self.border_color}; border: 1px solid {COLORS['muted']}; border-radius: 5px;")

    # --- Output ------------------------------------------------------------------------------

    def update_preview(self) -> None:
        # Drawn at the screen density (sharp at 150 %); the painter works in logical pixels.
        ratio = self.preview.devicePixelRatioF()
        pixels = round(PREVIEW * ratio)
        canvas = QPixmap(pixels, pixels)
        canvas.setDevicePixelRatio(ratio)
        area = QRect(0, 0, PREVIEW, PREVIEW)
        painter = QPainter(canvas)
        painter.fillRect(area, checker_brush())
        if self.source is not None:
            try:
                token = render_token(self.source, self.settings(pixels))
                painter.drawImage(QRectF(area), pil_to_qimage(token))
            except ValueError as exc:
                painter.setPen(QColor(COLORS["danger"]))
                painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, str(exc))
        else:
            painter.setPen(QColor(COLORS["background"]))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "Choisissez une illustration")
        painter.end()
        self.preview.setPixmap(canvas)
        has_source = self.source is not None
        self.export_button.setEnabled(has_source)
        self.add_button.setEnabled(has_source)

    def render_full(self) -> Image.Image:
        if self.source is None:
            raise ValueError("Choisissez d'abord une image")
        return render_token(self.source, self.settings())

    def export_png(self) -> Path | None:
        if self.source is None:
            return None
        suggested = self.window_.initial_path("token", f"{self.source_name}_token.png")
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le token", suggested, "PNG (*.png)")
        if not path:
            return None
        destination = Path(path)
        if destination.suffix.lower() != ".png":
            destination = destination.with_name(destination.name + ".png")
        try:
            self.render_full().save(destination, format="PNG", optimize=True)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Export impossible", str(exc))
            return None
        self.window_.remember_directory("token", destination.parent)
        self.window_.statusBar().showMessage(f"Token exporté : {destination}", 5000)
        return destination

    def add_to_project(self) -> bool:
        if self.source is None:
            return False
        try:
            token = self.render_full()
        except ValueError as exc:
            QMessageBox.warning(self, "Créateur de tokens", str(exc))
            return False
        output = BytesIO()
        token.save(output, format="PNG")
        return self.window_.add_image_layer(output.getvalue(), f"Token : {self.source_name}")
