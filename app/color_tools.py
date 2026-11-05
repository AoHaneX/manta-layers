"""Eraser, colour picker, paint bucket and colour fields of the main window.

A mixin of MainWindow: every edit goes through its undoable ``mutate``.
"""
from __future__ import annotations

from math import floor
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QGraphicsPixmapItem, QMessageBox

from .graphics import eraser_source_position, layer_source_pixel
from .model import Layer
from .screen_picker import ScreenColorPicker
from .theme import COLORS

# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase
else:
    _WindowBase = object


class ColorToolsMixin(_WindowBase):
    """Eraser strokes, colour picking and filling, and the current colour."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.
        _screen_picker: ScreenColorPicker | None

        def __getattr__(self, name: str) -> Any: ...

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
        tool = "du crayon" if self.pencil_active else "de la gomme"
        self.statusBar().showMessage(f"Taille {tool} : {value} px", 1800)
        self.canvas.viewport().update()

    def eraser_stroke_settings(self) -> dict:
        """Settings of a new eraser or pencil stroke, without its points (shared by the preview and the commit)."""
        settings = {
            "size": self.eraser_size.value(),
            "shape": self.eraser_shape.currentData(),
            "pixel_art": self.eraser_pixel_art.isChecked(),
            "hardness": self.eraser_hardness.value(),
            "opacity": self.eraser_opacity.value(),
            "pixel_centered": True,
        }
        if self.pencil_active:
            settings.update(tool="pencil", color=self.replacement_color)
        return settings

    def commit_eraser_stroke(self, layer_id: str, points: list[QPointF]):
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "image" or layer.locked or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("Trait ignoré : calque non modifiable", 3000)
            return
        width, height = item.pixmap().width(), item.pixmap().height()
        stroke = self.eraser_stroke_settings()
        size = stroke["size"]
        # On a flipped layer the covered pixels are mirrored, as in the live preview.
        stroke["points"] = [[eraser_source_position(point.x(), width, size, layer.flip_horizontal),
                             eraser_source_position(point.y(), height, size, layer.flip_vertical)]
                            for point in points]
        self.mutate(
            "Trait de crayon" if stroke.get("tool") == "pencil" else "Trait de gomme",
            lambda doc: doc.layer(layer_id).eraser_strokes.append(stroke),
            layer_id,
        )

    def sample_canvas_color(self, item, scene_position) -> bool:
        layer = self.document.layer(item.data(0)) if item is not None else None
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("La pipette fonctionne sur les calques image", 3000)
            return False
        found = self._layer_pixel(layer, item, scene_position)
        if found is None:
            return False
        _x, _y, (red, green, blue, alpha) = found
        if alpha == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return False
        sampled = f"#{red:02X}{green:02X}{blue:02X}"
        return self.apply_picked_color(sampled, self.picker_target, self.picker_text_layer_id)

    def _layer_pixel(self, layer: Layer, item: QGraphicsPixmapItem, scene_position):
        """Source position and exact colour of the layer pixel under a scene position, or None."""
        local = item.mapFromScene(scene_position)
        # floor, not int(): a click just left of or above the layer is outside it.
        x, y = floor(local.x()), floor(local.y())
        pixmap = item.pixmap()
        try:
            return layer_source_pixel(layer, self.document, x, y, (pixmap.width(), pixmap.height()))
        except Exception as exc:
            self.statusBar().showMessage(f"Calque illisible : {exc}", 4000)
            return None

    def apply_picked_color(self, sampled: str, target: str, text_layer_id: str | None) -> bool:
        """Give a picked colour to its tool: the tools colour, or a text colour (undoable)."""
        if target in ("text", "text_background"):
            text_layer = self.document.layer(text_layer_id)
            if not text_layer or text_layer.kind != "text" or text_layer.locked:
                self.deactivate_picker()
                self.statusBar().showMessage("Le calque texte n'est plus modifiable", 3000)
                return False
            attribute = "text_background" if target == "text_background" else "color"
            description = "Couleur de fond du texte" if attribute == "text_background" else "Couleur du texte"
            self.mutate(
                description,
                lambda doc: setattr(doc.layer(text_layer.id), attribute, sampled),
                text_layer.id,
            )
        else:
            # La couleur prélevée devient la couleur de remplissage ; la sélection
            # reste sur le calque que les outils doivent continuer de viser.
            self.set_current_color(sampled)
        self.deactivate_picker()
        self.statusBar().showMessage(f"Couleur prélevée : {sampled}", 4000)
        return True

    def start_screen_picker(self) -> bool:
        """Pick a colour anywhere on the desktop, for the active picker target (tools colour by default)."""
        if self._screen_picker is not None and self._screen_picker.active:
            return False
        target = self.picker_target if self.picker_active else "tools"
        text_layer_id = self.picker_text_layer_id if self.picker_active else None
        picker = ScreenColorPicker(self)
        picker.picked.connect(lambda color: self._screen_pick_done(color, target, text_layer_id))
        picker.cancelled.connect(lambda: self._screen_pick_done(None, target, text_layer_id))
        picker.failed.connect(lambda message: QMessageBox.warning(self, "Pipette écran", message))
        self._screen_picker = picker
        if not picker.start():
            self._screen_picker = None
            return False
        self.statusBar().showMessage(
            "Pipette écran : survolez n'importe quelle application et cliquez · Échap ou clic droit pour annuler")
        return True

    def _screen_pick_done(self, color: str | None, target: str, text_layer_id: str | None):
        if self._screen_picker is not None:
            self._screen_picker.deleteLater()  # one picker per use, never kept by the window
        self._screen_picker = None
        if color is None:
            self.statusBar().showMessage("Pipette écran annulée", 2500)
            return
        self.apply_picked_color(color, target, text_layer_id)

    def paint_canvas_color(self, scene_position) -> bool:
        layer_id = self.tool_target_id()
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "image" or not isinstance(item, QGraphicsPixmapItem):
            self.statusBar().showMessage("Le pot nécessite un calque image sélectionné", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le modifier", 3000)
            return False
        found = self._layer_pixel(layer, item, scene_position)
        if found is None:
            self.statusBar().showMessage("Cliquez sur le calque sélectionné", 3000)
            return False
        seed_x, seed_y, (red, green, blue, alpha) = found
        if alpha == 0:
            self.statusBar().showMessage("Ce pixel est transparent", 3000)
            return False
        # La zone à remplacer est toujours celle de la couleur cliquée ; la couleur
        # courante de l'onglet Outils (pipette, HEX, palette) est la couleur cible.
        source = f"#{red:02X}{green:02X}{blue:02X}"
        target = self.replacement_color.upper()
        if source == target:
            self.statusBar().showMessage("La couleur choisie est déjà appliquée", 3000)
            return False
        fill = {
            "mode": self.paint_mode,
            "source": source,
            "target": target,
            "x": seed_x,
            "y": seed_y,
            "tolerance": self.paint_tolerance.value(),
            "preserve_shading": self.preserve_shading.isChecked(),
            "after_strokes": len(layer.eraser_strokes),
        }
        description = (
            "Recoloriser une zone" if self.preserve_shading.isChecked()
            else "Remplir une zone"
        ) if self.paint_mode == "contiguous" else (
            "Recoloriser le calque" if self.preserve_shading.isChecked()
            else "Remplacer une couleur sur le calque"
        )
        return self.mutate(
            description,
            lambda doc: doc.layer(layer.id).color_fills.append(fill),
            layer.id,
        )

    def set_current_color(self, color: str, skip_field: str | None = None):
        selected = QColor(color)
        if not selected.isValid():
            return
        self.replacement_color = selected.name().upper()
        self.color_preview.setStyleSheet(
            f"background-color: {self.replacement_color}; border: 1px solid {COLORS['muted']}; border-radius: 6px;"
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
                f"background: {value}; border: 1px solid {COLORS['muted']}; border-radius: 5px; padding: 0;"
            )

    def choose_variation(self, index: int):
        if 0 <= index < len(self.variation_colors):
            self.set_current_color(self.variation_colors[index])

    def choose_replacement_color(self):
        color = QColorDialog.getColor(QColor(self.replacement_color), self, "Couleur de remplacement")
        if color.isValid():
            self.set_current_color(color.name())
