"""Rows of the property panel shown for shape layers.

The widgets reuse the controls of the text properties (spin boxes, colour
swatch with its button and its "×" clear button); every edit is committed by
the main window as one undoable step.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QToolButton,
    QWidget,
)

from .model import MAX_DIMENSION, MAX_STROKE_WIDTH, Layer
from .shape_item import OPEN_SHAPES, SHAPE_TYPE_LABELS
from .theme import COLORS

if TYPE_CHECKING:
    from .window import MainWindow


def _spin(minimum: float, maximum: float, decimals: int, suffix: str = " px") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    return spin


class ColorField(QWidget):
    """Swatch, hexadecimal value and clear button, like the text background control."""

    def __init__(self, window: MainWindow, key: str, title: str, empty_label: str):
        super().__init__()
        self.empty_label = empty_label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(30, 28)
        self.swatch.setToolTip(f"Choisir la couleur : {title.lower()}")
        self.button = QPushButton(empty_label)
        # The hexadecimal value must always show in full: a narrower padding than the theme's.
        self.button.setStyleSheet("padding-left: 6px; padding-right: 6px;")
        self.clear = QToolButton()
        self.clear.setObjectName("colorTool")
        self.clear.setText("×")
        self.clear.setToolTip(f"Retirer : {title.lower()}")
        for widget in (self.swatch, self.button):
            widget.clicked.connect(lambda _checked=False: window.choose_shape_color(key, title))
        self.clear.clicked.connect(lambda _checked=False: window.set_shape_property(key, None))
        layout.addWidget(self.swatch)
        layout.addWidget(self.button, stretch=1)
        layout.addWidget(self.clear)

    def fit_value(self) -> None:
        """Minimum width of the value button: the widest value in the font actually used.

        Measured once the field is in the window, whose style sheet sets the font.
        """
        self.button.ensurePolished()
        metrics = self.button.fontMetrics()
        widest = max(metrics.horizontalAdvance(text) for text in ("#000000", "#DDDDDD", "#BBBBBB", self.empty_label))
        self.button.setMinimumWidth(widest + 18)  # side paddings, border and a little air

    def show_color(self, color: str | None, editable: bool) -> None:
        self.fit_value()
        muted = COLORS["muted"]
        self.button.setText(color.upper() if color else self.empty_label)
        self.swatch.setStyleSheet(
            f"background-color: {color}; border: 1px solid {muted}; border-radius: 5px;" if color else
            f"background-color: transparent; border: 1px dashed {muted}; border-radius: 5px;"
        )
        self.clear.setEnabled(bool(color) and editable)


class ShapePropertyRows:
    """Shape rows added to the property form; hidden for other layers."""

    def __init__(self, window: MainWindow, form: QFormLayout):
        self.form = form
        self.type_combo = QComboBox()
        for kind, label in SHAPE_TYPE_LABELS.items():
            self.type_combo.addItem(label, kind)
        self.type_combo.currentIndexChanged.connect(lambda _index: window.commit_shape_property("shape_type"))
        self.width = _spin(1, MAX_DIMENSION * 2, 1)
        self.height = _spin(1, MAX_DIMENSION * 2, 1)
        self.fill = ColorField(window, "fill_color", "Remplissage", "Aucun")
        self.stroke = ColorField(window, "stroke_color", "Contour", "Aucun")
        self.stroke_width = _spin(0, MAX_STROKE_WIDTH, 1)
        self.radius = _spin(0, MAX_DIMENSION, 1)
        self.sides = QSpinBox()
        self.sides.setRange(3, 24)
        self.sides.setKeyboardTracking(False)
        for key, spin in (("shape_width", self.width), ("shape_height", self.height),
                          ("stroke_width", self.stroke_width), ("corner_radius", self.radius),
                          ("polygon_sides", self.sides)):
            spin.editingFinished.connect(lambda key=key: window.commit_shape_property(key))
        self.rows = (
            ("Type de forme", self.type_combo), ("Largeur", self.width), ("Hauteur", self.height),
            ("Remplissage", self.fill), ("Contour", self.stroke), ("Épaisseur du contour", self.stroke_width),
            ("Arrondi des angles", self.radius), ("Nombre de côtés", self.sides),
        )
        for label, widget in self.rows:
            form.addRow(label, widget)

    def value(self, key: str):
        return {
            "shape_type": self.type_combo.currentData(),
            "shape_width": self.width.value(),
            "shape_height": self.height.value(),
            "stroke_width": self.stroke_width.value(),
            "corner_radius": self.radius.value(),
            "polygon_sides": self.sides.value(),
        }[key]

    def refresh(self, layer: Layer | None) -> None:
        is_shape = layer is not None and layer.kind == "shape"
        for _label, widget in self.rows:
            self.form.setRowVisible(widget, is_shape)
        if layer is None or not is_shape:
            return
        editable = not layer.locked
        widgets = (self.type_combo, self.width, self.height, self.stroke_width, self.radius, self.sides)
        for widget in widgets:
            widget.blockSignals(True)
            widget.setEnabled(editable)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(layer.shape_type)))
        self.width.setValue(layer.shape_width)
        self.height.setValue(layer.shape_height)
        self.stroke_width.setValue(layer.stroke_width)
        self.radius.setValue(layer.corner_radius)
        self.sides.setValue(layer.polygon_sides)
        for widget in widgets:
            widget.blockSignals(False)
        self.fill.setEnabled(editable and layer.shape_type not in OPEN_SHAPES)
        self.stroke.setEnabled(editable)
        self.fill.show_color(layer.fill_color, editable)
        self.stroke.show_color(layer.stroke_color, editable)
        self.form.setRowVisible(self.fill, layer.shape_type not in OPEN_SHAPES)
        self.form.setRowVisible(self.radius, layer.shape_type == "rectangle")
        self.form.setRowVisible(self.sides, layer.shape_type == "polygon")
