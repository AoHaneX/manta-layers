"""Text layers of the main window: font, path shape, colours and typing on the canvas.

A mixin of MainWindow: every change goes through its undoable ``mutate``.
"""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QColorDialog

from .commands import DocumentCommand
from .graphics import CurvedTextGraphicItem, resolve_font_family
from .model import Document, Layer
from .textpath import DEFAULT_CONTROLS, normalize_controls
from .widgets import InlineTextEditor

# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase

    from .window import MainWindow
else:
    _WindowBase = object


class TextFlowsMixin(_WindowBase):
    """Text properties, text path shapes and the inline text editor."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.
        _inline: dict | None

        def __getattr__(self, name: str) -> Any: ...

    def on_font_changed(self, font: QFont):
        if self.refreshing:
            return
        self.last_font_family = font.family()
        self.settings.setValue("text/last_font", self.last_font_family)
        self.commit_property("font_family")

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
        if not self.curve_intensity.isSliderDown():
            self.curve_commit_timer.start()

    def set_curve_from_value(self, value: int):
        self.curve_intensity.setValue(value)

    def reset_curve_only(self):
        self.curve_intensity.setValue(0)
        self.commit_property("curve_intensity")

    def current_text_alignment(self) -> str:
        for alignment, button in self.text_alignment_buttons.items():
            if button.isChecked():
                return alignment
        return "center"

    @staticmethod
    def _shape_values(shape: str, intensity: float, controls) -> tuple[str, float, list]:
        # U shapes only use the magnitude of the intensity.
        intensity = max(-100.0, min(100.0, float(intensity)))
        if shape in ("u", "u_inverted"):
            intensity = abs(intensity)
        return shape, intensity, normalize_controls(controls)

    def _set_text_shape(self, layer_id: str, shape: str, intensity: float, controls, description: str):
        shape, intensity, controls = self._shape_values(shape, intensity, controls)

        def apply(doc):
            target = doc.layer(layer_id)
            target.text_deformation, target.curve_intensity, target.path_controls = shape, intensity, controls

        self.mutate(description, apply, layer_id)

    def commit_text_shape(self, before: Document, layer_id: str, shape: str, intensity: float, controls):
        """Record a handle drag on the canvas as a single undoable step."""
        source = before.layer(layer_id)
        if not source:
            return
        shape, intensity, controls = self._shape_values(shape, intensity, controls)
        if (shape, controls) == (source.text_deformation, source.path_controls) \
                and abs(source.curve_intensity - intensity) < 0.01:
            return
        after = before.clone()
        target = after.layer(layer_id)
        if target is None:
            return
        target.text_deformation, target.curve_intensity, target.path_controls = shape, intensity, controls
        self._push(DocumentCommand(
            cast("MainWindow", self), before, after, "Déformer le texte", layer_id, layer_id
        ))

    def show_text_shape(self, shape: str, intensity: float):
        """Mirror a live handle drag in the property panel without committing."""
        for widget, value in ((self.curve_intensity, round(intensity)), (self.curve_value, round(intensity))):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        index = self.text_shape_combo.findData(shape)
        if index >= 0 and index != self.text_shape_combo.currentIndex():
            self.text_shape_combo.blockSignals(True)
            self.text_shape_combo.setCurrentIndex(index)
            self.text_shape_combo.blockSignals(False)

    def reset_text_controls(self):
        layer = self.document.layer(self.selected_id)
        if layer and layer.kind == "text" and not layer.locked:
            self._set_text_shape(layer.id, "custom", layer.curve_intensity, DEFAULT_CONTROLS,
                                 "Réinitialiser la courbe du texte")

    # --- Text typed directly on the canvas -------------------------------------------

    def begin_inline_text_edit(self, layer_id: str):
        layer = self.document.layer(layer_id)
        item = self.canvas.graphic_for(layer_id)
        if not layer or layer.kind != "text" or layer.locked or item is None:
            return
        self.select_layer(layer_id)
        self._open_inline_editor(layer.text, item, layer_id, None)

    def begin_inline_text_create(self, scene_position: QPointF):
        """Text tool: preview a new text at the click and create it on validation."""
        if self.canvas.scene() is None:
            return
        layer = Layer(kind="text", name="Texte", text="Texte", font_family=resolve_font_family(self.last_font_family))
        item = CurvedTextGraphicItem(layer)
        # The click marks the start of the first baseline.
        layer.x = scene_position.x()
        layer.y = scene_position.y() - item.baseline
        item.setPos(layer.x, layer.y)
        item.setZValue(len(self.document.layers) + 1)
        self.canvas.scene().addItem(item)
        self._open_inline_editor("", item, None, layer)

    def _open_inline_editor(self, text: str, item, layer_id: str | None, new_layer: Layer | None):
        self._close_inline_editor()
        editor = InlineTextEditor(text, self.canvas.viewport())
        editor.setObjectName("inlineTextEditor")
        anchor = self.canvas.mapFromScene(item.mapToScene(item.boundingRect().bottomLeft()))
        viewport = self.canvas.viewport().rect()
        editor.resize(280, 96)
        editor.move(max(4, min(anchor.x(), viewport.width() - editor.width() - 4)),
                    max(4, min(anchor.y() + 6, viewport.height() - editor.height() - 4)))
        self._inline = {"editor": editor, "item": item, "layer_id": layer_id, "new_layer": new_layer}
        editor.textChanged.connect(lambda: self._preview_inline_text(editor.toPlainText()))
        editor.committed.connect(self._commit_inline_text)
        editor.cancelled.connect(self._cancel_inline_text)
        editor.show()
        editor.setFocus()

    def _preview_inline_text(self, text: str):
        if self._inline is None:
            return
        placeholder = "Texte" if self._inline["new_layer"] is not None else " "
        try:
            self._inline["item"].set_text_preview(text if text.strip() else placeholder)
        except RuntimeError:
            return  # the scene was rebuilt meanwhile
        self.canvas.viewport().update()

    def _close_inline_editor(self) -> dict | None:
        session, self._inline = self._inline, None
        if session is None:
            return None
        session["editor"].hide()
        session["editor"].deleteLater()
        if session["new_layer"] is not None:
            try:
                scene = session["item"].scene()
                if scene is not None:
                    scene.removeItem(session["item"])
            except RuntimeError:
                pass
        self.canvas.setFocus()
        self.canvas.viewport().update()
        return session

    def _commit_inline_text(self, text: str):
        session = self._close_inline_editor()
        if session is None or not text.strip():
            if session is not None and session["layer_id"]:
                self._restore_inline_item(session)
            return
        new_layer = session["new_layer"]
        if new_layer is not None:
            new_layer.text = text
            new_layer.name = f"Texte : {text.split(chr(10), 1)[0][:28]}"

            def add(doc):
                doc.layers.append(deepcopy(new_layer))

            if self.mutate("Ajouter un texte", add, new_layer.id):
                self.select_layer(new_layer.id)
            return
        layer = self.document.layer(session["layer_id"])
        if layer is None or layer.text == text:
            self._restore_inline_item(session)
            return
        self.mutate("Contenu du texte", lambda doc: setattr(doc.layer(layer.id), "text", text), layer.id)

    def _cancel_inline_text(self):
        session = self._close_inline_editor()
        if session is not None and session["layer_id"]:
            self._restore_inline_item(session)

    def _restore_inline_item(self, session: dict):
        layer = self.document.layer(session["layer_id"])
        try:
            if layer is not None:
                session["item"].apply_layer(layer)
        except RuntimeError:
            pass
        self.canvas.viewport().update()

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
