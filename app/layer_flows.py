"""Layer panel of the main window: multiple selection, folders, merging, drag and drop.

A mixin of MainWindow: every change of the stack goes through its undoable ``mutate``.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QInputDialog, QListWidgetItem, QMenu, QMessageBox

from .graphics import (
    RENDER_ERRORS,
    layers_bounds,
    merge_changes_appearance,
    qimage_png,
    render_document,
    render_layers_region,
)
from .layer_panel import FOLDER_ROLE, set_row_checked
from .model import Document, Layer
from .templates import extract_elements, list_templates, save_template

# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase
else:
    _WindowBase = object


class LayerFlowsMixin(_WindowBase):
    """Checked layers, folders, layer context menu and reordering by drag and drop."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.

        def __getattr__(self, name: str) -> Any: ...

    # --- Multiple selection and folders ----------------------------------------------------
    # Checked layers form the multiple selection: a view state, outside the
    # document and the history, used by the folder, merge, delete and template actions.

    def checked_layers(self) -> list[Layer]:
        """Checked layers that still exist, bottom to top."""
        return [layer for layer in self.document.layers if layer.id in self.checked_ids]

    def checked_layer_ids(self) -> list[str]:
        """Checked layers that still exist, bottom to top."""
        return [layer.id for layer in self.document.layers if layer.id in self.checked_ids]

    def set_layer_checked(self, layer_id: str, checked: bool):
        if self.refreshing or self.document.layer(layer_id) is None:
            return
        if checked:
            self.checked_ids.add(layer_id)
        else:
            self.checked_ids.discard(layer_id)
        self._refresh_checks()

    def set_checked_layers(self, layer_ids) -> None:
        self.checked_ids = {layer_id for layer_id in layer_ids if self.document.layer(layer_id)}
        self._refresh_checks()

    def set_folder_checked(self, folder_id: str, checked: bool):
        members = {layer.id for layer in self.document.folder_members(folder_id)}
        if checked:
            self.checked_ids |= members
        else:
            self.checked_ids -= members
        self._refresh_checks()

    def toggle_folder_checked(self, folder_id: str):
        """Check every layer of the folder, or none when they all are already."""
        state = self._folder_check_state(self.document, folder_id)
        self.set_folder_checked(folder_id, state != Qt.CheckState.Checked)

    def _refresh_checks(self):
        """Update check boxes and highlights in place (the list keeps its scroll position)."""
        self.refreshing = True
        try:
            for index in range(self.layer_list.count()):
                row = self.layer_list.item(index)
                controls = self.layer_list.itemWidget(row)
                item_id = row.data(Qt.ItemDataRole.UserRole)
                box = controls.findChild(QCheckBox, "layerCheck") if controls else None
                if box is None:
                    continue
                if row.data(FOLDER_ROLE):
                    state = self._folder_check_state(self.document, item_id)
                    box.setTristate(state == Qt.CheckState.PartiallyChecked)
                    box.setCheckState(state)
                    set_row_checked(controls, state == Qt.CheckState.Checked)
                else:
                    box.setChecked(item_id in self.checked_ids)
                    set_row_checked(controls, item_id in self.checked_ids)
        finally:
            self.refreshing = False
        self.statusBar().showMessage(f"{len(self.checked_ids)} calque(s) dans la sélection multiple", 2500)

    def layer_name_clicked(self, layer_id: str):
        """Click selects the layer; Ctrl+click adds it to (or removes it from) the multiple selection."""
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_layer_checked(layer_id, layer_id not in self.checked_ids)
            return
        self.select_layer(layer_id)

    def set_folder_visibility(self, folder_id: str, visible: bool):
        folder = self.document.folder(folder_id)
        if self.refreshing or folder is None or folder.visible == visible:
            return
        self.mutate("Afficher / masquer le dossier",
                    lambda doc: setattr(doc.folder(folder_id), "visible", visible))

    def toggle_folder_collapsed(self, folder_id: str):
        """Folding only changes the list: a view state saved with the project, outside the history."""
        folder = self.document.folder(folder_id)
        if folder is None:
            return
        folder.collapsed = not folder.collapsed
        # Outside the history, but kept by undo and redo (their snapshots predate
        # the fold) and saved with the project.
        self._collapsed_folders[folder_id] = folder.collapsed
        self._rebuild_layer_list(self.document)

    def _unique_folder_name(self) -> str:
        names = {folder.name for folder in self.document.folders}
        return next(f"Dossier {index}" for index in range(1, len(names) + 2) if f"Dossier {index}" not in names)

    def create_folder_from_checked(self) -> bool:
        layer_ids = self.checked_layer_ids()
        if not layer_ids:
            self.statusBar().showMessage("Cochez les calques à regrouper", 3000)
            return False
        name, accepted = QInputDialog.getText(self, "Créer un dossier de calques", "Nom du dossier :",
                                              text=self._unique_folder_name())
        if not accepted:
            return False
        return self.mutate("Créer un dossier de calques",
                           lambda doc: doc.create_folder(layer_ids, name.strip() or "Dossier"))

    def rename_folder(self, folder_id: str) -> bool:
        folder = self.document.folder(folder_id)
        if folder is None:
            return False
        name, accepted = QInputDialog.getText(self, "Renommer le dossier", "Nom du dossier :", text=folder.name)
        clean = " ".join(name.split())
        if not accepted or not clean or clean == folder.name:
            return False
        return self.mutate("Renommer le dossier", lambda doc: setattr(doc.folder(folder_id), "name", clean))

    def dissolve_folder(self, folder_id: str) -> bool:
        if self.document.folder(folder_id) is None:
            return False
        return self.mutate("Dissocier le dossier", lambda doc: doc.dissolve_folder(folder_id))

    def delete_checked_layers(self) -> bool:
        layers = self.checked_layers()
        removable = [layer.id for layer in layers if not layer.locked]
        if not removable:
            self.statusBar().showMessage(
                "Déverrouillez les calques avant de les supprimer" if layers else "Aucun calque coché", 3000)
            return False
        if not self.mutate(f"Supprimer {len(removable)} calque(s)", lambda doc: doc.remove_layers(removable)):
            return False
        self.checked_ids -= set(removable)
        if self.selected_id in removable:
            self.select_layer(None)
        self._refresh_checks()
        if len(removable) < len(layers):
            self.statusBar().showMessage("Les calques verrouillés ont été conservés", 4000)
        return True

    def merge_checked_layers(self) -> bool:
        """Merge the checked visible layers into one image layer, at the place of the topmost."""
        layers = self.checked_layers()
        sources = [layer for layer in layers if self.document.is_visible(layer)]
        if len(sources) < 2:
            self.statusBar().showMessage("Cochez au moins deux calques visibles à fusionner", 3500)
            return False
        if any(layer.locked for layer in sources):
            self.statusBar().showMessage("Déverrouillez les calques avant de les fusionner", 3500)
            return False
        animated = next((layer for layer in sources if layer.is_animated), None)
        if animated is not None and self.refuse_animated(animated, "la fusion"):
            return False
        changes = self._render_or_report(
            "Fusionner les calques", lambda: merge_changes_appearance(self.document, [layer.id for layer in sources]))
        if changes is None:
            return False
        if changes:
            answer = QMessageBox.question(
                self, "Fusionner les calques",
                "Des calques non cochés se trouvent entre les calques à fusionner et les recouvrent. "
                "Le calque fusionné sera placé au-dessus d'eux : l'image changera d'aspect.\n\n"
                "Fusionner quand même ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            merged = render_layers_region(self.document, [layer.id for layer in sources])
        except RENDER_ERRORS as exc:
            self._report_failure("Fusionner les calques", exc)
            return False
        if merged is None:
            self.statusBar().showMessage("Les calques à fusionner n'ont aucun pixel visible", 3500)
            return False
        image, (left, top) = merged
        output = BytesIO()
        image.save(output, format="PNG")
        data, source_ids, holder = output.getvalue(), [layer.id for layer in sources], {}

        def apply(doc):
            top_layer = max((doc.layer(layer_id) for layer_id in source_ids), key=doc.layers.index)
            position = sum(1 for layer in doc.layers[:doc.layers.index(top_layer)] if layer.id not in source_ids)
            new = doc.add_image_bytes(data, f"Fusion de {len(source_ids)} calques", center=False)
            doc.layers.remove(new)
            new.x, new.y, new.folder = float(left), float(top), top_layer.folder
            doc.layers = [layer for layer in doc.layers if layer.id not in source_ids]
            doc.layers.insert(position, new)
            doc.normalize_folders()
            holder["id"] = new.id

        if not self.mutate("Fusionner les calques", apply, lambda: holder["id"]):
            return False
        self.checked_ids = {holder["id"]}
        self.select_layer(holder["id"])
        self._refresh_checks()
        if len(sources) < len(layers):
            self.statusBar().showMessage("Les calques masqués n'ont pas été fusionnés", 4000)
        return True

    def create_template_from_checked(self) -> Path | None:
        """Save the checked layers, their folders and images as a reusable element template."""
        layer_ids = self.checked_layer_ids()
        bounds = layers_bounds(self.document, layer_ids) if layer_ids else None
        if bounds is None:
            self.statusBar().showMessage("Cochez les calques qui composeront le modèle", 3000)
            return None
        default = self.checked_layers()[-1].name if len(layer_ids) == 1 else "Nouveau modèle"
        name, accepted = QInputDialog.getText(self, "Créer un modèle", "Nom du modèle :", text=default)
        if not accepted or not name.strip():
            return None
        try:
            elements = extract_elements(self.document, layer_ids, bounds)
            destination = self._confirm_template_replacement(name, "elements")
            if destination is False:
                return None
            path = save_template(elements, name, self._template_thumbnail(elements),
                                 destination=destination, kind="elements")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Création du modèle impossible", str(exc))
            return None
        self.statusBar().showMessage(f"Modèle créé : {name.strip()} · Insertion > Bibliothèque de modèles", 6000)
        return path

    def _confirm_template_replacement(self, name: str, kind: str):
        """Path of a same-named template to replace, None for a new one, False if cancelled."""
        existing = next((info for info in list_templates(kind=kind)
                         if info.name.casefold() == name.strip().casefold()), None)
        if existing is None:
            return None
        answer = QMessageBox.question(
            self, "Remplacer le modèle",
            f"Un modèle nommé « {existing.name} » existe déjà. Le remplacer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return existing.path if answer == QMessageBox.StandardButton.Yes else False

    @staticmethod
    def _template_thumbnail(document: Document) -> bytes:
        return qimage_png(render_document(document, QSize(320, 180)))

    def show_layer_context_menu(self, row: QListWidgetItem | None, global_position):
        self.layer_context_menu(row).exec(global_position)

    def layer_context_menu(self, row: QListWidgetItem | None) -> QMenu:
        """Menu of a panel row; right-clicking a layer applies the multiple selection rule first."""
        menu = QMenu(self)
        menu.setObjectName("canvasContextMenu")
        if row is not None and row.data(FOLDER_ROLE):
            folder_id = row.data(Qt.ItemDataRole.UserRole)
            menu.addAction("Renommer le dossier…").triggered.connect(lambda: self.rename_folder(folder_id))
            menu.addAction("Cocher les calques du dossier").triggered.connect(
                lambda: self.set_folder_checked(folder_id, True))
            menu.addAction("Dissocier le dossier").triggered.connect(lambda: self.dissolve_folder(folder_id))
            return menu
        if row is not None:
            layer_id = row.data(Qt.ItemDataRole.UserRole)
            # As in a file explorer: right-clicking outside the selection selects only that layer.
            if layer_id not in self.checked_ids:
                self.set_checked_layers([layer_id])
            self.select_layer(layer_id)
        count = len(self.checked_layer_ids())
        folder_action = menu.addAction("Créer un dossier de calques…")
        merge_action = menu.addAction("Fusionner les calques")
        delete_action = menu.addAction("Supprimer")
        template_action = menu.addAction("Créer un modèle…")
        folder_action.setEnabled(count >= 1)
        merge_action.setEnabled(count >= 2)
        delete_action.setEnabled(count >= 1)
        template_action.setEnabled(count >= 1)
        folder_action.triggered.connect(self.create_folder_from_checked)
        merge_action.triggered.connect(self.merge_checked_layers)
        delete_action.triggered.connect(self.delete_checked_layers)
        template_action.triggered.connect(self.create_template_from_checked)
        if self.checked_ids:
            menu.addSeparator()
            menu.addAction("Tout décocher").triggered.connect(lambda: self.set_checked_layers([]))
        return menu

    def drop_in_layer_list(self, kind: str, item_id: str, target: QListWidgetItem | None, upper: bool) -> bool:
        """Drop a dragged layer or folder on a row of the panel.

        On a layer row: above or below it, in its folder. On a folder row: its
        upper half places the item above the folder, its lower half inside it.
        Below the last row: at the bottom of the stack.
        """
        doc = self.document
        if target is None:
            anchor, above, folder = (doc.layers[0].id if doc.layers else None), False, None
        elif target.data(FOLDER_ROLE):
            members = doc.folder_members(target.data(Qt.ItemDataRole.UserRole))
            if not members:
                return False
            anchor, above = members[-1].id, True
            folder = None if upper else target.data(Qt.ItemDataRole.UserRole)
        else:
            anchor_layer = doc.layer(target.data(Qt.ItemDataRole.UserRole))
            if anchor_layer is None:
                return False
            anchor, above, folder = anchor_layer.id, upper, anchor_layer.folder
        if kind == "folder":
            if doc.folder(item_id) is None:
                return False
            return self._mutate_structure("Déplacer le dossier", lambda d: d.move_folder(item_id, anchor, above))
        layer = doc.layer(item_id)
        if layer is None:
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le déplacer", 3000)
            return False
        return self._mutate_structure("Déplacer le calque",
                                      lambda d: d.move_layer(item_id, anchor, above, folder), item_id)

    def _mutate_structure(self, description: str, fn, select_after: str | None = None) -> bool:
        """Run a stacking change only if it really changes the order or the folders (no empty history step)."""
        def structure(doc):
            return [(layer.id, layer.folder) for layer in doc.layers]

        probe = self.document.clone()
        if not fn(probe) or structure(probe) == structure(self.document):
            return False
        return self.mutate(description, fn, select_after)
