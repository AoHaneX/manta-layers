"""Selections of the main window and the pixel operations built on them.

A mixin of MainWindow: selecting, copying, cutting or moving selected pixels
(through non-destructive layer masks), background removal and cropping.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha1
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

from PIL import Image, ImageChops
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QDialog, QLineEdit, QPlainTextEdit

from . import selection
from .background_dialog import BackgroundRemovalDialog
from .commands import SelectionCommand
from .graphics import (
    RENDER_ERRORS,
    crop_image_layer,
    document_mask_to_layer,
    layer_mask_to_document,
    layer_selection_outline,
    layer_source_position,
    pil_to_qimage,
    render_layer_image,
    render_layer_with_mask,
    render_layers,
)
from .imaging import alpha_bounds
from .model import ASSET_FORMATS, Document, new_id


def clipboard_fingerprint(image: QImage) -> str:
    """Identity of an image's pixels, whatever the format the clipboard returns it in."""
    pixels = image.convertToFormat(QImage.Format.Format_RGBA8888)
    digest = sha1(f"{pixels.width()}x{pixels.height()}".encode(), usedforsecurity=False)
    digest.update(pixels.constBits())
    return digest.hexdigest()


# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase

    from .window import MainWindow
else:
    _WindowBase = object


class SelectionFlowsMixin(_WindowBase):
    """Selection masks, selected pixels, layer masks and cropping."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.
        _clipboard_origin: tuple[tuple[int, int], str] | None

        def __getattr__(self, name: str) -> Any: ...

    # --- Selections ---------------------------------------------------------------------
    # The selection is a document-sized mask, outside the Document: it is not
    # saved in projects, but every change is an undoable SelectionCommand.
    #
    # The magic wand on one image layer also keeps the exact selection in that
    # layer's source pixels (``selection_layer``): a scaled layer shows pixels
    # finer than the document grid, and parts of it outside the frame, which
    # the document mask cannot hold. Edits of that layer use the exact mask as
    # long as the layer keeps the geometry it was made for.

    def _combine_mode(self, modifiers) -> str:
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if shift and alt:
            return "intersect"
        if shift:
            return "add"
        if alt:
            return "subtract"
        return self.selection_mode_combo.currentData()

    @staticmethod
    def _layer_geometry(layer) -> tuple:
        """What an exact selection depends on: the image and where its pixels are shown."""
        return (layer.asset, layer.x, layer.y, layer.sx, layer.sy, layer.rotation,
                layer.flip_horizontal, layer.flip_vertical)

    def _selection_state(self) -> tuple | None:
        """Undoable form of the selection: PNG document mask and optional exact layer mask."""
        if self.selection_mask is None:
            return None
        exact = None
        if self.selection_layer is not None:
            layer_id, geometry, mask = self.selection_layer
            exact = (layer_id, geometry, selection.encode(mask))
        return selection.encode(self.selection_mask), exact

    def _install_selection(self, state: tuple | None):
        self.selection_mask, self.selection_layer = None, None
        if state is not None:
            data, exact = state
            self.selection_mask = selection.decode(data)
            if exact is not None:
                layer_id, geometry, mask = exact
                self.selection_layer = (layer_id, geometry, selection.decode(mask))
        self._refresh_selection_visual()

    def _exact_selection(self, layer) -> Image.Image | None:
        """Exact selection in the source pixels of ``layer``, if it was made for it as it is now."""
        if self.selection_layer is None or layer is None or layer.kind != "image":
            return None
        layer_id, geometry, mask = self.selection_layer
        if layer_id != layer.id or geometry != self._layer_geometry(layer):
            return None
        return mask

    def _refresh_selection_visual(self):
        outline = None
        if self.selection_layer is not None:
            layer = self.document.layer(self.selection_layer[0])
            exact = self._exact_selection(layer)
            if exact is not None:
                outline = layer_selection_outline(exact, layer)
        self.canvas.update_selection_visual(self.selection_mask, self.show_selection_mask.isChecked(), outline)
        self._update_selection_actions()

    def _update_selection_actions(self):
        has_selection = self.selection_mask is not None
        for action in getattr(self, "selection_actions", ()):
            action.setEnabled(has_selection)
        self.separate_selection_btn.setEnabled(has_selection)

    def set_selection(self, mask, description: str, exact: tuple[Any, Image.Image] | None = None):
        """Replace the selection as an undoable step; ``exact`` is (layer, source-aligned mask)."""
        if exact is not None and selection.is_empty(exact[1]):
            exact = None
        if mask is not None and selection.is_empty(mask) and exact is None:
            mask = None
        if mask is None and exact is not None:
            mask = selection.empty((self.document.width, self.document.height))  # all outside the frame
        before = self._selection_state()
        after = None
        if mask is not None:
            layer_part = None
            if exact is not None:
                layer, layer_mask = exact
                layer_part = (layer.id, self._layer_geometry(layer), selection.encode(layer_mask))
            after = (selection.encode(mask), layer_part)
        if before != after:
            self.undo_stack.push(SelectionCommand(cast("MainWindow", self), before, after, description))

    def _combine_exact(self, shape: Image.Image, mode: str) -> tuple[Any, Image.Image] | None:
        """Keep an exact layer selection through a document-space change (another tool, Maj, Alt)."""
        if mode == "replace" or self.selection_layer is None:
            return None
        layer = self.document.layer(self.selection_layer[0])
        current = self._exact_selection(layer)
        if current is None:
            return None
        shape_on_layer = document_mask_to_layer(shape, layer, current.size,
                                                smooth=not self.selection_pixel_perfect.isChecked())
        return layer, selection.combine(current, shape_on_layer, mode)

    def _finish_shape(self, shape):
        if self.selection_pixel_perfect.isChecked():
            return shape
        return selection.feather(shape, self.selection_feather.value())

    def apply_selection_shape(self, tool: str, rect: QRectF, modifiers):
        mode = self._combine_mode(modifiers)
        if rect.width() < 1 and rect.height() < 1:
            # A simple click with a new selection clears it, as in most editors.
            if mode == "replace":
                self.deselect()
            return
        size = (self.document.width, self.document.height)
        box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        antialias = not self.selection_pixel_perfect.isChecked()
        draw = selection.ellipse if tool == "ellipse" else selection.rectangle
        shape = self._finish_shape(draw(size, box, antialias))
        label = "Sélection elliptique" if tool == "ellipse" else "Sélection rectangulaire"
        self.set_selection(selection.combine(self.selection_mask, shape, mode), label,
                           self._combine_exact(shape, mode))

    def apply_selection_polygon(self, points, modifiers) -> bool:
        """Selection from a closed lasso outline (document coordinates)."""
        mode = self._combine_mode(modifiers)
        size = (self.document.width, self.document.height)
        antialias = not self.selection_pixel_perfect.isChecked()
        shape = selection.polygon(size, points, antialias)
        if selection.is_empty(shape):
            if mode == "replace" and len(points) < 3:
                self.deselect()  # a click without an outline clears, as with the other tools
            self.statusBar().showMessage("Contour trop petit : aucune sélection", 2500)
            return False
        shape = self._finish_shape(shape)
        self.set_selection(selection.combine(self.selection_mask, shape, mode), "Lasso",
                           self._combine_exact(shape, mode))
        return True

    def apply_magic_wand(self, scene_position: QPointF, modifiers):
        mode = self._combine_mode(modifiers)
        tolerance, contiguous = self.wand_tolerance.value(), self.wand_contiguous.isChecked()
        layer = None if self.wand_all_layers.isChecked() else self.document.layer(self.tool_target_id())
        if layer is not None and layer.kind == "image":
            self._magic_wand_on_layer(layer, scene_position, mode)
            return
        x, y = int(scene_position.x() // 1), int(scene_position.y() // 1)
        if not (0 <= x < self.document.width and 0 <= y < self.document.height):
            hint = (" (pour un calque qui dépasse du cadre, décochez « Échantillonner tous les calques »)"
                    if self.wand_all_layers.isChecked() else "")
            self.statusBar().showMessage(f"Cliquez à l'intérieur du document{hint}", 4000)
            return
        if self.wand_all_layers.isChecked():
            # Damaged images (shown hatched) are left out of the analysed picture.
            readable = [layer.id for layer in self.document.layers if not self._is_unreadable(layer)]
            image = self._render_or_report("Baguette magique", lambda: render_layers(
                self.document, readable, with_background=True))
            if len(readable) < len(self.document.layers):
                self.statusBar().showMessage("Les calques à l'image endommagée sont ignorés", 4000)
        else:
            if layer is None:
                self.statusBar().showMessage("Sélectionnez le calque à analyser", 3000)
                return
            layer_id = layer.id
            image = self._render_or_report("Baguette magique", lambda: render_layers(self.document, [layer_id]))
        if image is None:
            return
        wand = self._finish_shape(selection.magic_wand(image, (x, y), tolerance, contiguous))
        self.set_selection(selection.combine(self.selection_mask, wand, mode), "Baguette magique",
                           self._combine_exact(wand, mode))

    def _magic_wand_on_layer(self, layer, scene_position: QPointF, mode: str):
        """Magic wand on the source pixels of one image layer, inside or outside the frame.

        A scaled layer shows its own pixels, finer than the document grid: a
        thin line one source pixel wide can vanish from a document-sized
        render. The wand reads the pixels the canvas shows instead, and the
        selection keeps them exactly for the edits of this layer.
        """
        if self._is_unreadable(layer):
            self.statusBar().showMessage("L'image de ce calque est endommagée", 3000)
            return
        image = self._render_or_report("Baguette magique", lambda: render_layer_with_mask(layer, self.document))
        if image is None:
            return
        seed = layer_source_position(layer, scene_position, image.size)
        if seed is None:
            self.statusBar().showMessage(f"Cliquez sur un pixel du calque « {layer.name} »", 3000)
            return
        exact = selection.magic_wand(image, seed, self.wand_tolerance.value(), self.wand_contiguous.isChecked())
        pixel_perfect = self.selection_pixel_perfect.isChecked()
        if not pixel_perfect:
            # The feather radius is given in document pixels.
            scale = max(1e-6, (abs(layer.sx) * abs(layer.sy)) ** 0.5)
            exact = selection.feather(exact, self.selection_feather.value() / scale)
        size = (self.document.width, self.document.height)
        shown = layer_mask_to_document(exact, layer, size, smooth=not pixel_perfect)
        if mode != "replace" and self.selection_mask is not None:
            current = self._exact_selection(layer)
            if current is None:
                current = document_mask_to_layer(self.selection_mask, layer, image.size, smooth=not pixel_perfect)
            exact = selection.combine(current, exact, mode)
        self.set_selection(selection.combine(self.selection_mask, shown, mode), "Baguette magique",
                           (layer, exact))

    def select_all(self):
        self.set_selection(selection.full((self.document.width, self.document.height)), "Tout sélectionner")

    def deselect(self):
        self.set_selection(None, "Désélectionner")

    def invert_selection(self):
        size = (self.document.width, self.document.height)
        current = self.selection_mask if self.selection_mask is not None else selection.empty(size)
        self.set_selection(selection.invert(current), "Inverser la sélection")

    def _reset_selection(self):
        """New or opened document: start without selection (not an undoable step)."""
        self.selection_mask, self.selection_layer = None, None
        self._refresh_selection_visual()

    def _selection_layer(self, editable: bool):
        """Layer the selection acts on; pixel edits need an unlocked image layer."""
        layer = self.document.layer(self.tool_target_id())
        if self.selection_mask is None:
            self.statusBar().showMessage("Aucune sélection active", 3000)
            return None
        if layer is None:
            self.statusBar().showMessage("Sélectionnez un calque", 3000)
            return None
        if editable and layer.kind != "image":
            self.statusBar().showMessage(
                "Un calque texte reste vectoriel : copiez la sélection vers un nouveau calque", 4000
            )
            return None
        if editable and layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le modifier", 3000)
            return None
        return layer

    def _is_unreadable(self, layer) -> bool:
        """True for a layer whose image was found damaged when the project was opened."""
        known = self._unreadable_assets
        return layer.asset in known or (layer.mask is not None and layer.mask in known)

    def selected_pixels(self, layer) -> tuple[Image.Image, tuple[int, int]] | None:
        """Visible pixels of a layer inside the selection, cropped, with their position."""
        if self.selection_mask is None:
            return None
        rendered = self._render_or_report("Pixels sélectionnés", lambda: render_layers(self.document, [layer.id]))
        if rendered is None:
            return None
        cut = selection.apply_alpha(rendered, self.selection_mask)
        box = cut.getchannel("A").getbbox()
        if box is None:
            self.statusBar().showMessage("Aucun pixel visible dans la sélection", 3000)
            return None
        return cut.crop(box), box[:2]

    def _source_size(self, layer) -> tuple[int, int]:
        with Image.open(BytesIO(self.document.assets[layer.asset]), formats=ASSET_FORMATS) as source:
            return source.size

    def _edit_layer_mask(self, doc: Document, layer_id: str, operation: str, area=None):
        """Change a layer mask inside a mutation: hide, reveal or follow ``area``."""
        layer = doc.layer(layer_id)
        if layer is None:
            raise ValueError("Calque introuvable")
        if area is None:
            if self.selection_mask is None:
                raise ValueError("Aucune sélection active")
            area = self._exact_selection(layer)
            if area is None:
                area = document_mask_to_layer(self.selection_mask, layer, self._source_size(layer),
                                              smooth=not self.selection_pixel_perfect.isChecked())
        current = selection.decode(doc.assets[layer.mask]) if layer.mask else None
        updated = (selection.hide if operation == "hide" else selection.reveal)(current, area)
        if updated.getextrema() == (255, 255):
            layer.mask = None  # fully visible: no mask needed
            return
        layer.mask = new_id()
        doc.assets[layer.mask] = selection.encode(updated)

    def clear_selection_content(self):
        layer = self._selection_layer(editable=True)
        if layer is not None:
            self.mutate("Effacer la sélection",
                        lambda doc: self._edit_layer_mask(doc, layer.id, "hide"), layer.id)

    def reveal_selection_in_mask(self):
        layer = self._selection_layer(editable=True)
        if layer is None:
            return
        if not layer.mask:
            self.statusBar().showMessage("Ce calque n'a pas de masque", 3000)
            return
        self.mutate("Révéler la sélection",
                    lambda doc: self._edit_layer_mask(doc, layer.id, "reveal"), layer.id)

    def remove_layer_mask(self):
        layer = self.document.layer(self.tool_target_id())
        if layer is None or not layer.mask or layer.locked:
            self.statusBar().showMessage("Aucun masque modifiable sur ce calque", 3000)
            return
        self.mutate("Supprimer le masque du calque",
                    lambda doc: setattr(doc.layer(layer.id), "mask", None), layer.id)

    def copy_selection(self) -> bool:
        layer = self._selection_layer(editable=False)
        pixels = self.selected_pixels(layer) if layer is not None else None
        if pixels is None:
            return False
        image, origin = pixels
        copied = pil_to_qimage(image)
        QApplication.clipboard().setImage(copied)
        # Pasting our own copy puts it back where it came from. The clipboard is
        # recognised by its content, not by its change notifications, which Windows
        # sends later, once the copy is over.
        self._clipboard_origin = (origin, clipboard_fingerprint(copied))
        self.statusBar().showMessage("Sélection copiée", 3000)
        return True

    def cut_selection(self) -> bool:
        if self._selection_layer(editable=True) is None or not self.copy_selection():
            return False
        self.clear_selection_content()
        return True

    def _exact_selection_copy(self, layer):
        """The exactly selected pixels of ``layer`` as a new layer at the same place and scale.

        Returns (layer, assets); "empty" when nothing visible is selected; None
        without an exact selection or when the edits cannot be replayed on the
        cropped copy (the document-resolution copy is used instead).
        """
        exact = self._exact_selection(layer)
        if exact is None:
            return None
        area = exact
        if layer.mask:
            current = selection.decode(self.document.assets[layer.mask])
            if current.size != exact.size:
                current = current.resize(exact.size, Image.Resampling.NEAREST)
            area = ImageChops.multiply(current, exact)
        candidate = deepcopy(layer)
        candidate.mask = new_id()
        probe = Document(self.document.width, self.document.height, None, [candidate],
                         {**self.document.assets, candidate.mask: selection.encode(area)})
        try:
            box = render_layer_with_mask(candidate, probe).getchannel("A").getbbox()
            if box is None:
                return "empty"
            copy, assets = crop_image_layer(candidate, probe, box)
        except RENDER_ERRORS:
            return None
        copy.id, copy.name, copy.locked = new_id(), f"{layer.name} (sélection)", False
        return copy, assets

    def selection_to_new_layer(self, cut: bool = False, offset: tuple[int, int] = (0, 0)) -> bool:
        layer = self._selection_layer(editable=cut)
        if layer is None:
            return False
        exact_copy = self._exact_selection_copy(layer)
        if exact_copy == "empty":
            self.statusBar().showMessage("Aucun pixel visible dans la sélection", 3000)
            return False
        data = b""
        if exact_copy is None:
            pixels = self.selected_pixels(layer)
            if pixels is None:
                return False
            image, (left, top) = pixels
            output = BytesIO()
            image.save(output, format="PNG")
            data = output.getvalue()
        holder: dict[str, str] = {}

        def apply(doc):
            if cut:
                self._edit_layer_mask(doc, layer.id, "hide")
            if exact_copy is not None:
                # Same scale, rotation and edits as its source: no pixel is resampled.
                copy, assets = exact_copy
                new = deepcopy(copy)
                doc.assets.update(assets)
                new.x, new.y = new.x + offset[0], new.y + offset[1]
            else:
                new = doc.add_image_bytes(data, f"{layer.name} (sélection)", center=False)
                new.x, new.y = float(left + offset[0]), float(top + offset[1])
                doc.layers.remove(new)
            doc.layers.insert(doc.layers.index(doc.layer(layer.id)) + 1, new)
            new.folder = doc.layer(layer.id).folder  # stays next to its source, in its folder
            holder["id"] = new.id

        label = "Couper vers un nouveau calque" if cut else "Copier vers un nouveau calque"
        if not self.mutate(label, apply, lambda: holder["id"]):
            return False
        self.select_layer(holder["id"])
        return True

    def lift_selection(self, scene_position: QPointF):
        """Start a Ctrl+drag move: the selected pixels follow the mouse."""
        if self.selection_mask is None:
            return None
        x, y = int(scene_position.x() // 1), int(scene_position.y() // 1)
        width, height = self.selection_mask.size
        if not (0 <= x < width and 0 <= y < height) or self.selection_mask.getpixel((x, y)) == 0:
            return None
        layer = self._selection_layer(editable=True)
        pixels = self.selected_pixels(layer) if layer is not None else None
        if pixels is None:
            return None
        image, origin = pixels
        return {"pixmap": QPixmap.fromImage(pil_to_qimage(image)), "origin": QPointF(*origin)}

    def move_selection_content(self, dx: int, dy: int):
        """Move the selected pixels to a new layer, and the selection with them."""
        if dx == 0 and dy == 0 or self.selection_mask is None:
            return
        layer = self._selection_layer(editable=True)
        if layer is None or self.selected_pixels(layer) is None:
            return  # nothing to move: no empty step in the history
        moved = selection.translate(self.selection_mask, dx, dy)
        self.undo_stack.beginMacro("Déplacer la sélection")
        try:
            if self.selection_to_new_layer(cut=True, offset=(dx, dy)):
                self.set_selection(moved, "Déplacer la sélection")
        finally:
            self.undo_stack.endMacro()

    def remove_background(self):
        """Preview then apply a local background removal on the target image layer."""
        layer = self.document.layer(self.tool_target_id())
        if layer is None or layer.kind != "image":
            self.statusBar().showMessage("Sélectionnez un calque image à détourer", 3000)
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le détourer", 3000)
            return
        # Source pixels with their non-destructive edits, but without the current mask.
        image = self._render_or_report("Supprimer l'arrière-plan", lambda: render_layer_image(
            self.document.assets[layer.asset], layer.color_replacements,
            layer.color_fills, layer.eraser_strokes, cache_key=layer.asset))
        if image is None:
            return
        dialog = BackgroundRemovalDialog(image, layer.name, bool(layer.mask), self.models_dir, self)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            mask = dialog.result_mask() if accepted else None
            keep_existing, as_mask = dialog.keep_existing.isChecked(), dialog.as_mask.isChecked()
        finally:
            dialog.dispose()
        if mask is None:
            return
        if keep_existing and layer.mask:
            current = selection.decode(self.document.assets[layer.mask])
            if current.size != mask.size:
                current = current.resize(mask.size, Image.Resampling.NEAREST)
            mask = selection.combine(current, mask, "intersect")
        if as_mask:
            def apply_mask(doc):
                target = doc.layer(layer.id)
                target.mask = new_id()
                doc.assets[target.mask] = selection.encode(mask)

            self.mutate("Supprimer l'arrière-plan", apply_mask, layer.id)
            return
        output = BytesIO()
        selection.apply_alpha(image, mask).save(output, format="PNG")
        data, holder = output.getvalue(), {}

        def add_layer(doc):
            source = doc.layer(layer.id)
            new = doc.add_image_bytes(data, f"{source.name} (détouré)", center=False)
            for key in ("x", "y", "sx", "sy", "rotation", "opacity", "flip_horizontal", "flip_vertical"):
                setattr(new, key, getattr(source, key))
            doc.layers.remove(new)
            doc.layers.insert(doc.layers.index(source) + 1, new)
            new.folder = source.folder
            source.visible = False
            holder["id"] = new.id

        if self.mutate("Supprimer l'arrière-plan (nouveau calque)", add_layer, lambda: holder["id"]):
            self.select_layer(holder["id"])

    def trim_layer_margins(self, layer_id: str | None = None) -> bool:
        """Crop an image layer to its visible pixels without moving them on the canvas."""
        layer = self.document.layer(layer_id or self.tool_target_id())
        if layer is None or layer.kind != "image":
            self.statusBar().showMessage("Sélectionnez un calque image à rogner", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque pour le rogner", 3000)
            return False
        rendered = self._render_or_report("Rogner les marges transparentes",
                                          lambda: render_layer_with_mask(layer, self.document))
        if rendered is None:
            return False
        box = alpha_bounds(rendered)
        if box is None:
            self.statusBar().showMessage("Le calque est entièrement transparent : rien à rogner", 3500)
            return False
        if box == (0, 0, *rendered.size):
            self.statusBar().showMessage("Ce calque n'a pas de marge transparente", 3000)
            return False
        try:
            trimmed, assets = crop_image_layer(layer, self.document, box)
        except RENDER_ERRORS as exc:
            self._report_failure("Rogner les marges transparentes", exc)
            return False

        def apply(doc):
            doc.assets.update(assets)
            doc.layers[doc.layers.index(doc.layer(layer.id))] = deepcopy(trimmed)

        return self.mutate("Rogner les marges transparentes", apply, layer.id)

    def crop_document_to_content(self) -> bool:
        """Shrink the document to the visible pixels of its layers; the layers keep their look."""
        rendered = self._render_or_report("Recadrer le document sur son contenu",
                                          lambda: render_layers(self.document))
        if rendered is None:
            return False
        box = alpha_bounds(rendered)
        if box is None:
            self.statusBar().showMessage("Le document ne contient aucun pixel visible", 3500)
            return False
        left, top, right, bottom = box
        if box == (0, 0, self.document.width, self.document.height):
            self.statusBar().showMessage("Le document n'a pas de marge transparente", 3000)
            return False

        def apply(doc):
            doc.width, doc.height = right - left, bottom - top
            for layer in doc.layers:
                layer.x -= left
                layer.y -= top

        # The selection is tied to the old frame: it is cleared in the same undo step.
        self.undo_stack.beginMacro("Recadrer le document sur son contenu")
        try:
            self.deselect()
            done = self.mutate("Recadrer le document sur son contenu", apply, self.selected_id)
        finally:
            self.undo_stack.endMacro()
        if done:
            self.canvas.fit_document()
        return done

    def delete_selection_or_layer(self) -> bool:
        """Delete key: the selected pixels, else the checked layers, else the current layer.

        A text field or spin box being edited keeps the key for itself.
        """
        if self._focus_edits_text():
            return False
        if self.selection_mask is not None:
            self.clear_selection_content()
            return True
        if self.checked_layer_ids():
            return self.delete_checked_layers()
        self.delete_layer()
        return True

    @staticmethod
    def _focus_edits_text() -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QComboBox):
            return focused.isEditable()
        return isinstance(focused, (QLineEdit, QPlainTextEdit, QAbstractSpinBox))
