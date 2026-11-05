"""Fenêtre principale de Manta Layers, éditeur simple à calques pour Windows."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from functools import partial
from io import BytesIO
from pathlib import Path
from shutil import copy2

from PIL import Image
from PySide6.QtCore import QPointF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QUndoStack
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGraphicsPixmapItem,
    QInputDialog,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QToolButton,
    QWidget,
)

from . import __version__, background, background_dialog, selection
from .color_tools import ColorToolsMixin
from .commands import DocumentCommand, SelectionCommand
from .file_flows import DocumentFlowsMixin
from .graphics import (
    RENDER_ERRORS,
    forget_font_families,
    pil_to_qimage,
    qimage_png,
    render_layer_with_mask,
    resolve_font_family,
)
from .icons import sidebar_arrow_icon
from .layer_flows import LayerFlowsMixin
from .layer_panel import FOLDER_ROLE, build_folder_row, build_layer_row
from .model import MAX_LAYERS, Document, Layer
from .paths import user_data_directory
from .screen_picker import ScreenColorPicker
from .selection_flows import SelectionFlowsMixin, clipboard_fingerprint
from .shape_item import OPEN_SHAPES, shape_from_drag
from .sprite_dialog import SpriteSheetDialog
from .storage import open_project
from .template_library import TemplateLibraryDialog
from .templates import insert_elements
from .text_flows import TextFlowsMixin
from .textpath import TEXT_SHAPES
from .theme import COLORS, STYLE
from .token_dialog import TokenDialog
from .window_panels import WindowPanelsMixin

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}
# Polices livrées avec l'application (lecture seule) puis polices importées
# par l'utilisateur, rangées dans son dossier de données.
BUNDLED_FONTS_DIR = ROOT / "fonts"
USER_FONTS_DIR = user_data_directory() / "fonts"
PROPERTY_LABELS = {
    "name": "Renommer le calque",
    "x": "Position X", "y": "Position Y",
    "sx": "Échelle X", "sy": "Échelle Y",
    "rotation": "Rotation",
    "opacity": "Opacité",
    "text": "Contenu du texte",
    "font_family": "Police du texte",
    "font_size": "Taille du texte",
    "curve_intensity": "Courbure du texte",
    "character_spacing": "Espacement des caractères",
    "path_alignment": "Alignement du texte",
    "text_deformation": "Forme du texte",
    "path_orientation": "Orientation des lettres",
}


class MainWindow(DocumentFlowsMixin, LayerFlowsMixin, TextFlowsMixin, SelectionFlowsMixin, ColorToolsMixin,
                 WindowPanelsMixin, QMainWindow):
    def __init__(self, settings: QSettings | None = None, recovery_dir: Path | None = None):
        super().__init__()
        # Crash-recovery copies; tests pass a temporary folder.
        self.recovery_dir = Path(recovery_dir) if recovery_dir is not None else user_data_directory() / "recovery"
        self.document = Document()
        self.project_path: Path | None = None
        # Element template opened for editing ({"path", "name"}): saving writes it back.
        self.editing_template: dict | None = None
        # Template the document comes from (its key), for the remembered folders.
        self.template_origin: str | None = None
        self.selected_id: str | None = None
        # Dernier calque choisi : les outils continuent de le viser même si la
        # sélection est vidée, par exemple après un clic dans le vide.
        self.last_selected_id: str | None = None
        self.refreshing = False
        self.picker_active = False
        self.picker_target = "tools"
        self.picker_text_layer_id: str | None = None
        self.paint_mode: str | None = None
        self.eraser_active = False
        self.text_tool_active = False
        self.selection_tool: str | None = None
        # Shape being drawn on the canvas: rectangle, ellipse, polygon, line or arrow.
        self.shape_tool: str | None = None
        self.shape_tool_buttons: dict[str, QToolButton] = {}
        self._screen_picker: ScreenColorPicker | None = None
        self.selection_tool_buttons: dict[str, QToolButton] = {}
        # Floating editor used to type a text directly on the canvas.
        self._inline: dict | None = None
        self._resyncing_history = False
        # Assets found damaged when the document was opened (see _make_scene).
        self._unreadable_assets: set[str] = set()
        self.selection_mask: Image.Image | None = None
        # Exact magic wand selection in one layer's source pixels: (layer id, geometry, mask).
        self.selection_layer: tuple[str, tuple, Image.Image] | None = None
        # Multiple selection of the layer panel (layer ids), see set_layer_checked.
        self.checked_ids: set[str] = set()
        # Folded folders of the current document, kept across undo and redo.
        self._collapsed_folders: dict[str, bool] = {}
        self._layer_rows: dict[str, QWidget] = {}
        self.models_dir = background.models_directory()
        # Position of the pixels this window copied, with the fingerprint of the
        # clipboard image they became: only that image is pasted back in place.
        self._clipboard_origin: tuple[tuple[int, int], str] | None = None
        self.last_eraser_point: tuple[float, float] | None = None
        self.last_eraser_layer_id: str | None = None
        self.replacement_color = COLORS["primary"]
        self._updating_color_fields = False
        self._pushing_command: DocumentCommand | None = None
        self._push_error: Exception | None = None
        self.variation_colors: list[str] = []
        self.left_sidebar_expanded = True
        self.left_sidebar_width = 245
        self.settings = settings if settings is not None else QSettings("Blue Shrimp", "Manta Layers")
        self.last_font_family = str(self.settings.value("text/last_font", "Arial"))
        self.snap_enabled = self.settings.value("canvas/snap", True, type=bool)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self.custom_font_ids: list[int] = []
        self.load_custom_fonts()
        self.setWindowIcon(QIcon(str(ASSETS / "manta.png")))
        self.setAcceptDrops(True)
        self.setMinimumSize(960, 600)
        self.resize(1440, 870)
        self.setStyleSheet(STYLE)
        self._build_layout()
        self._build_actions()
        self._name_icon_buttons(self)
        self.undo_stack.indexChanged.connect(self.update_title)
        self.undo_stack.cleanChanged.connect(self.update_title)
        self._revision = 0
        self._load_demo()
        self._setup_recovery()

    def load_custom_fonts(self):
        """Charge les polices livrées avec l'application puis celles importées."""
        for directory in (BUNDLED_FONTS_DIR, USER_FONTS_DIR):
            try:
                paths = sorted(directory.iterdir()) if directory.is_dir() else []
            except OSError:
                continue
            for path in paths:
                if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                    font_id = QFontDatabase.addApplicationFont(str(path))
                    if font_id >= 0:
                        self.custom_font_ids.append(font_id)
        forget_font_families()

    def import_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Importer des polices", "", "Polices (*.ttf *.otf *.ttc);;Tous les fichiers (*)"
        )
        if not paths:
            return
        imported = []
        for raw_path in paths:
            source = Path(raw_path)
            if source.suffix.lower() not in FONT_SUFFIXES:
                continue
            destination = USER_FONTS_DIR / source.name
            if destination.exists():
                answer = QMessageBox.question(
                    self, "Police déjà présente",
                    f"Remplacer la police {source.name} ?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    continue
            try:
                # La police est validée avant la copie : un fichier invalide
                # n'est jamais laissé dans le dossier des polices.
                font_id = QFontDatabase.addApplicationFontFromData(source.read_bytes())
                if font_id < 0:
                    raise ValueError("format de police non pris en charge")
                USER_FONTS_DIR.mkdir(parents=True, exist_ok=True)
                copy2(source, destination)
                self.custom_font_ids.append(font_id)
                imported.extend(QFontDatabase.applicationFontFamilies(font_id))
            except Exception as exc:
                QMessageBox.warning(self, "Import de police impossible", f"{source.name}\n{exc}")
        if imported:
            forget_font_families()
            self.statusBar().showMessage(
                "Police(s) ajoutée(s) : " + ", ".join(dict.fromkeys(imported)), 6000
            )

    def toggle_left_sidebar(self):
        self.left_sidebar_expanded = not self.left_sidebar_expanded
        if self.left_sidebar_expanded:
            sizes = self.main_splitter.sizes()
            self.left_panel.show()
            self.main_splitter.setSizes([
                self.left_sidebar_width,
                max(1, sizes[1] - self.left_sidebar_width), sizes[2],
            ])
            self.left_toggle.setIcon(sidebar_arrow_icon(False))
            self.left_toggle.setToolTip("Replier le panneau d'utilitaires")
        else:
            self.left_sidebar_width = max(220, self.main_splitter.sizes()[0])
            self.left_panel.hide()
            self.left_toggle.setIcon(sidebar_arrow_icon(True))
            self.left_toggle.setToolTip("Ouvrir le panneau d'utilitaires")

    def _load_demo(self):
        demo = ROOT / "exemples" / "Manta_Demo.manta"
        document = Document()
        if demo.exists():
            try:
                document = open_project(demo)
            except Exception:
                document = Document()
        try:
            self.install_document(document, document.layers[-1].id if document.layers else None)
        except Exception:
            self.install_document(Document(), None)
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.canvas.fit_document()
        self.update_title()

    def install_document(self, doc: Document, selected: str | None, scene=None):
        """Affiche un document. Si son rendu échoue, l'état courant reste intact.

        ``scene`` is the scene of ``doc`` when it was already built (see _push).
        """
        if scene is None:
            scene = self._make_scene(doc)
        self._revision += 1
        # The scene is replaced: an editor typing into the old one is dropped,
        # and a drag in progress forgets the items about to be deleted.
        self._close_inline_editor()
        self.canvas.reset_interaction()
        for folder in doc.folders:
            folder.collapsed = self._collapsed_folders.get(folder.id, folder.collapsed)
        self.refreshing = True
        try:
            self.document = doc
            self.checked_ids &= {layer.id for layer in doc.layers}
            self.selected_id = selected if doc.layer(selected) else None
            if self.selected_id:
                self.last_selected_id = self.selected_id
            previous = getattr(self, "canvas_scene", None)
            self.canvas_scene = scene
            self.canvas.setScene(self.canvas_scene)
            if previous is not None:
                # The previous scene may be the one handling the click that led here
                # (a pending curve committed by a selection change): it is handed to
                # the window and deleted once the event is over, never during it.
                previous.setParent(self)
                previous.deleteLater()
            self.canvas_scene.selectionChanged.connect(self.on_scene_select)
            self._rebuild_layer_list(doc)
            for item in self.canvas_scene.items():
                if item.data(0) == self.selected_id:
                    item.setSelected(True)
                    break
            self.doc_info.setText(f"{doc.width} × {doc.height} px · {len(doc.layers)} calque(s)")
            if self.selection_mask is not None and self.selection_mask.size != (doc.width, doc.height):
                # Size changes record the selection in their own undo step (resize_document):
                # this only keeps the mask the size of the document in between.
                resized = selection.resize_canvas(self.selection_mask, (doc.width, doc.height))
                self.selection_mask = None if selection.is_empty(resized) else resized
                self._refresh_selection_visual()
            self._refresh_properties()
            self.update_utility_buttons()
        finally:
            self.refreshing = False
        self.canvas.viewport().update()
        self.update_title()

    def _rebuild_layer_list(self, doc: Document):
        """Rows from top to bottom; a folder row precedes its (unless collapsed) layers."""
        scroll = self.layer_list.verticalScrollBar().value()
        # Clearing the list makes it report "no current row": that is not the
        # user deselecting the layer, so selection signals are ignored meanwhile.
        refreshing, self.refreshing = self.refreshing, True
        self.layer_list.setUpdatesEnabled(False)
        try:
            self.layer_list.clear()
            self._layer_rows = {}
            entries: list[tuple[str, bool, QWidget]] = []
            shown_folders = set()
            for layer in reversed(doc.layers):
                folder = doc.folder(layer.folder)
                if folder is not None and folder.id not in shown_folders:
                    shown_folders.add(folder.id)
                    entries.append((folder.id, True, build_folder_row(
                        self, folder, self._folder_check_state(doc, folder.id))))
                if folder is not None and folder.collapsed:
                    continue
                controls = build_layer_row(self, layer, layer.id in self.checked_ids)
                self._layer_rows[layer.id] = controls
                entries.append((layer.id, False, controls))
            # All items first, then their widgets: interleaving addItem and
            # setItemWidget relayouts the list each time, quadratic in the rows
            # (about 4 s for 1,000 layers, after every action).
            rows = [self._add_layer_list_item(item_id, is_folder) for item_id, is_folder, _ in entries]
            for row, (item_id, _is_folder, controls) in zip(rows, entries):
                self._name_icon_buttons(controls)
                self.layer_list.setItemWidget(row, controls)
                if item_id == self.selected_id:
                    self.layer_list.setCurrentItem(row)
        finally:
            self.layer_list.setUpdatesEnabled(True)
            self.refreshing = refreshing
        self.layer_list.verticalScrollBar().setValue(scroll)

    def _add_layer_list_item(self, item_id: str, is_folder: bool) -> QListWidgetItem:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, item_id)
        row.setData(FOLDER_ROLE, is_folder)
        row.setSizeHint(QSize(row.sizeHint().width(), 34))
        self.layer_list.addItem(row)
        return row

    def _folder_check_state(self, doc: Document, folder_id: str) -> Qt.CheckState:
        members = {layer.id for layer in doc.folder_members(folder_id)}
        checked = len(members & self.checked_ids)
        if checked == 0:
            return Qt.CheckState.Unchecked
        return Qt.CheckState.Checked if checked == len(members) else Qt.CheckState.PartiallyChecked

    @staticmethod
    def _name_icon_buttons(root: QWidget) -> None:
        """Give screen readers a name for buttons that only show an icon or a symbol."""
        for button in root.findChildren(QAbstractButton):
            if (not button.accessibleName() and button.toolTip()
                    and not any(character.isalpha() for character in button.text())):
                button.setAccessibleName(button.toolTip())

    def update_utility_buttons(self):
        """N'affiche dans la colonne gauche que les actions actuellement possibles."""
        if not hasattr(self, "utility_buttons"):
            return
        layer = self.document.layer(self.selected_id)
        editable = bool(layer and not layer.locked)
        for key in ("duplicate", "flip_horizontal", "flip_vertical", "delete"):
            self.utility_buttons[key].setVisible(editable)
        self.utility_buttons["lock"].setVisible(layer is not None)
        if layer is not None:
            self.utility_buttons["lock"].setText(
                "▣ Déverrouiller le calque" if layer.locked
                else "▣ Verrouiller le calque"
            )

    def select_layer(self, layer_id: str | None):
        if self.refreshing:
            return
        self._flush_pending_curve()
        self.refreshing = True
        try:
            self.selected_id = layer_id if self.document.layer(layer_id) else None
            if self.selected_id:
                self.last_selected_id = self.selected_id
            for i in range(self.layer_list.count()):
                row = self.layer_list.item(i)
                if row.data(Qt.ItemDataRole.UserRole) == self.selected_id:
                    self.layer_list.setCurrentItem(row)
                    break
            else:
                self.layer_list.setCurrentRow(-1)
            scene = self.canvas.scene()
            if scene is not None:
                for item in scene.items():
                    if self.document.layer(item.data(0)):
                        item.setSelected(item.data(0) == self.selected_id)
            self._refresh_properties()
            self.update_utility_buttons()
        finally:
            self.refreshing = False
        self.canvas.viewport().update()

    def tool_target_id(self) -> str | None:
        """Calque visé par la gomme et les pots : la sélection, sinon le dernier calque choisi."""
        for candidate in (self.selected_id, self.last_selected_id):
            if candidate and self.document.layer(candidate):
                return candidate
        return None

    def _show_tool_target(self):
        """Resélectionne le dernier calque choisi quand un outil s'active sans sélection."""
        if self.selected_id is None and self.tool_target_id():
            self.select_layer(self.tool_target_id())

    def on_scene_select(self):
        if self.refreshing:
            return
        scene = self.canvas.scene()
        if scene is None:
            return
        selected = scene.selectedItems()
        if selected:
            self.select_layer(selected[0].data(0))
        else:
            self.select_layer(None)

    def on_layer_list_select(self, current, previous):
        if self.refreshing or (current is not None and current.data(FOLDER_ROLE)):
            return  # a folder row is not a layer: the current layer stays selected
        self.select_layer(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def set_layer_visibility(self, layer_id: str, visible: bool):
        if self.refreshing:
            return
        layer = self.document.layer(layer_id)
        if layer and layer.visible != visible:
            self.mutate("Afficher / masquer le calque",
                        lambda doc: setattr(doc.layer(layer_id), "visible", visible), layer_id)

    def _refresh_properties(self):
        layer = self.document.layer(self.selected_id)
        is_text = bool(layer and layer.kind == "text")
        for widget in self.text_property_widgets:
            self.property_form.setRowVisible(widget, is_text)
        editable_widgets = [self.name_input, self.text_input, self.font_combo, self.font_size,
                            self.text_color_control, self.text_background_control,
                            self.text_alignment_control, self.curve_control,
                            self.character_spacing, *self.inputs.values()]
        widgets = [*editable_widgets, self.lock_btn]
        for w in widgets:
            w.setEnabled(layer is not None)
        if not layer:
            self.shape_rows.refresh(None)
            self.name_input.setText("")
            self.text_input.setPlainText("")
            self.paint_bucket_btn.setEnabled(False)
            self.paint_global_btn.setEnabled(False)
            self._schedule_right_panel_layout()
            return
        self.name_input.setText(layer.name)
        for w in editable_widgets:
            w.setEnabled(not layer.locked)
        for key, spin in self.inputs.items():
            spin.setValue(layer.opacity * 100 if key == "opacity" else getattr(layer, key))
        self.text_input.setPlainText(layer.text)
        for w in (self.text_input, self.font_combo, self.font_size,
                  self.text_color_control, self.text_background_control):
            w.setEnabled(is_text and not layer.locked)
        self.font_combo.setCurrentFont(QFont(layer.font_family))
        self.font_size.setValue(layer.font_size)
        shape = layer.text_deformation if layer.text_deformation in TEXT_SHAPES else "straight"
        self.text_shape_combo.setCurrentIndex(self.text_shape_combo.findData(shape))
        # U shapes use a magnitude only; the custom curve is driven by its handles.
        minimum = 0 if shape in ("u", "u_inverted") else -100
        self.curve_intensity.setRange(minimum, 100)
        self.curve_value.setRange(minimum, 100)
        editable_text = is_text and not layer.locked
        self.text_shape_control.setEnabled(editable_text)
        self.curve_control.setEnabled(editable_text and shape != "custom")
        self.text_controls_reset_btn.setEnabled(editable_text and shape == "custom")
        self.upright_letters.setEnabled(editable_text)
        self.upright_letters.setChecked(layer.path_orientation == "horizontal")
        self.curve_intensity.setValue(round(layer.curve_intensity))
        self.curve_value.setValue(round(layer.curve_intensity))
        self.character_spacing.setValue(layer.character_spacing)
        self.text_alignment_buttons.get(
            layer.path_alignment, self.text_alignment_buttons["center"]
        ).setChecked(True)
        muted = COLORS["muted"]
        self.color_btn.setText(layer.color.upper())
        self.text_color_swatch.setStyleSheet(
            f"background-color: {layer.color}; border: 1px solid {muted}; border-radius: 5px;"
        )
        background = layer.text_background if is_text else None
        self.text_background_btn.setText(background.upper() if background else "Transparent")
        self.text_background_swatch.setStyleSheet(
            f"background-color: {background}; border: 1px solid {muted}; border-radius: 5px;"
            if background else
            f"background-color: transparent; border: 1px dashed {muted}; border-radius: 5px;"
        )
        self.text_background_clear.setEnabled(bool(background) and not layer.locked)
        self.lock_btn.setText("Déverrouiller" if layer.locked else "Verrouiller")
        self.shape_rows.refresh(layer)
        can_paint = layer.kind == "image" and not layer.locked
        self.paint_bucket_btn.setEnabled(can_paint)
        self.paint_global_btn.setEnabled(can_paint)
        self._schedule_right_panel_layout()

    def mutate(self, description: str, fn, select_after=None) -> bool:
        """Apply ``fn`` to a copy of the document as one undoable step.

        ``select_after`` is the layer selected once the step is done (and redone),
        or a function returning it, called after ``fn`` for layers ``fn`` creates.
        """
        before = self._current_snapshot()
        after = self.document.clone()
        try:
            fn(after)
            if callable(select_after):
                select_after = select_after()
            if len(after.layers) > MAX_LAYERS and len(after.layers) > len(before.layers):
                # Beyond it the project could no longer be saved nor copied for recovery.
                raise ValueError(f"le projet compterait {len(after.layers)} calques, "
                                 f"pour un maximum de {MAX_LAYERS}")
            # Safety net: whatever the change, folders stay contiguous and never empty,
            # and images or masks no layer uses any more are not carried along.
            after.normalize_folders()
            after.prune_assets()
        except Exception as exc:
            self._report_failure(description, exc)
            return False
        return self._push(DocumentCommand(self, before, after, description,
                                          self.selected_id,
                                          select_after if select_after is not None else self.selected_id))

    # --- History storage ------------------------------------------------------------
    # Each step keeps the document before and after it. Snapshots are never
    # modified once stored (the canvas shows a copy), so the layers a step does
    # not change are shared with the previous snapshot instead of being copied:
    # the history grows with the changes, not with the size of the document.

    def _last_applied_document(self) -> Document | None:
        """Snapshot of the document left by the last applied step, if it can be found."""
        for index in range(self.undo_stack.index() - 1, -1, -1):
            command = self.undo_stack.command(index)
            if isinstance(command, DocumentCommand):
                return command.after
            children = [command.child(child) for child in range(command.childCount())]
            documents = [child for child in children if isinstance(child, DocumentCommand)]
            if documents:
                return documents[-1].after
            if not isinstance(command, SelectionCommand) and children == []:
                return None  # an unknown kind of step: no shortcut
        return None

    def _current_snapshot(self) -> Document:
        """The document shown, as a snapshot: the stored one when it is identical, else a copy."""
        previous = self._last_applied_document()
        if previous is not None and previous == self.document:
            return previous
        return self.document.clone()

    @staticmethod
    def _share_layers(snapshot: Document, reference: Document) -> None:
        """Replace the layers of ``snapshot`` identical to those of ``reference`` by the same objects."""
        known = {layer.id: layer for layer in reference.layers}
        shared = []
        for layer in snapshot.layers:
            previous = known.get(layer.id)
            if previous is None:
                shared.append(layer)
            elif previous == layer:
                shared.append(previous)
            else:
                # A changed layer still shares its earlier strokes and fills: a new
                # eraser stroke must not copy all the previous ones into the step.
                for name in ("eraser_strokes", "color_fills"):
                    old, new = getattr(previous, name), getattr(layer, name)
                    setattr(layer, name, [old[index] if index < len(old) and old[index] == item else item
                                          for index, item in enumerate(new)])
                shared.append(layer)
        snapshot.layers = shared

    def _push(self, command: DocumentCommand) -> bool:
        """Empile une commande ; si son application échoue, elle n'entre pas dans l'historique."""
        description = command.text()
        previous = self._last_applied_document()
        if previous is not None and command.before is not previous:
            self._share_layers(command.before, previous)
        self._share_layers(command.after, command.before)
        # Build the new scene first: pushing clears the redo steps and may move
        # the saved state, which a change that cannot be shown must not do.
        try:
            document = command.after.clone()
            command.prepared = (document, self._make_scene(document))
        except Exception as exc:
            self._report_failure(description, exc)
            return False
        self._pushing_command = command
        self._push_error = None
        try:
            self.undo_stack.push(command)
        finally:
            self._pushing_command = None
        if self._push_error is not None:
            self._report_failure(description, self._push_error)
            return False
        self.statusBar().showMessage(description, 3000)
        return True

    def command_failed(self, command: DocumentCommand, exc: Exception, undoing: bool = False):
        if command is self._pushing_command:
            self._push_error = exc
            # QUndoStack.push supprime une commande devenue obsolète au lieu de l'empiler.
            command.setObsolete(True)
            return
        self._report_failure("Annuler / rétablir", exc)
        if not self._resyncing_history:
            # The stack moved but the document did not: step back once the stack is idle,
            # so that the history position matches the document shown again.
            QTimer.singleShot(0, lambda: self._resync_history(undoing))

    def _resync_history(self, undoing: bool) -> None:
        self._resyncing_history = True
        try:
            if undoing:
                self.undo_stack.redo()
            else:
                self.undo_stack.undo()
        finally:
            self._resyncing_history = False

    def _report_failure(self, description: str, exc: Exception):
        QMessageBox.warning(self, "Action impossible", f"{description} : {exc}")

    def commit_canvas_moves(self, before: Document, positions: dict[str, tuple[float, float]]) -> bool:
        """Record layers dragged together as one undoable step."""
        after = before.clone()
        for layer_id, (x, y) in positions.items():
            layer = after.layer(layer_id)
            if layer is not None:
                layer.x, layer.y = x, y
        return self._push(DocumentCommand(self, before, after, f"Déplacer {len(positions)} calques",
                                          self.selected_id, self.selected_id))

    def toggle_snap(self, enabled: bool):
        self.snap_enabled = bool(enabled)
        self.settings.setValue("canvas/snap", self.snap_enabled)
        self.statusBar().showMessage(
            "Magnétisme activé · maintenez Alt pour l'ignorer" if enabled else "Magnétisme désactivé", 3000)

    def commit_canvas_transform(self, before, layer_id, state, description):
        after = before.clone()
        layer = after.layer(layer_id)
        layer.x, layer.y, layer.sx, layer.sy, layer.rotation = state
        self._push(DocumentCommand(self, before, after, description, layer_id, layer_id))

    def commit_property(self, key: str):
        """Valide uniquement le champ modifié.

        Les autres champs affichent des valeurs arrondies : les réécrire
        déplacerait ou redimensionnerait le calque sans que l'utilisateur le veuille.
        """
        if key == "curve_intensity":
            self.curve_commit_timer.stop()
        if self.refreshing:
            return
        layer = self.document.layer(self.selected_id)
        if not layer or layer.locked:
            return
        if key in self.inputs:
            spin = self.inputs[key]
            current = layer.opacity * 100 if key == "opacity" else getattr(layer, key)
            if abs(spin.value() - current) <= 0.5 * 10 ** -spin.decimals() + 1e-9:
                return
            low, high = spin.minimum(), spin.maximum()
            if not low <= current <= high and spin.value() == min(high, max(low, current)):
                return  # the field only shows the clamped value: leaving it changes nothing
            value = spin.value() / 100 if key == "opacity" else spin.value()
        elif key == "name":
            value = self.name_input.text().strip()
            if not value:
                self.name_input.setText(layer.name)
                return
        elif layer.kind != "text":
            return
        elif key == "text":
            value = self.text_input.toPlainText()
        elif key == "font_family":
            value = self.font_combo.currentFont().family()
        elif key == "font_size":
            value = self.font_size.value()
        elif key == "curve_intensity":
            if self.curve_intensity.value() == round(layer.curve_intensity):
                return
            value = float(self.curve_intensity.value())
            # Bending a straight text turns it into an arc.
            shape = "arc" if layer.text_deformation == "straight" and value else layer.text_deformation
            self._set_text_shape(layer.id, shape, value, layer.path_controls, PROPERTY_LABELS[key])
            return
        elif key == "text_deformation":
            shape = self.text_shape_combo.currentData()
            if shape == layer.text_deformation:
                return
            self._set_text_shape(layer.id, shape, layer.curve_intensity, layer.path_controls,
                                 PROPERTY_LABELS[key])
            return
        elif key == "path_orientation":
            value = "horizontal" if self.upright_letters.isChecked() else "tangent"
        elif key == "character_spacing":
            if abs(self.character_spacing.value() - layer.character_spacing) <= 0.05 + 1e-9:
                return
            value = self.character_spacing.value()
        elif key == "path_alignment":
            value = self.current_text_alignment()
        else:
            return
        if getattr(layer, key) == value:
            return
        self.mutate(PROPERTY_LABELS[key], lambda doc: setattr(doc.layer(layer.id), key, value), layer.id)

    def _flush_pending_curve(self):
        if self.curve_commit_timer.isActive():
            self.commit_property("curve_intensity")

    def _pending_edit_commits(self) -> dict[QWidget, Callable[[], object]]:
        """Fields validated on focus loss, with the call that validates each one."""
        commits: dict[QWidget, Callable[[], object]] = {
            self.name_input: lambda: self.commit_property("name"),
            self.text_input: lambda: self.commit_property("text"),
            self.font_size: lambda: self.commit_property("font_size"),
            self.curve_value: lambda: self.commit_property("curve_intensity"),
            self.character_spacing: lambda: self.commit_property("character_spacing"),
        }
        for key, spin in self.inputs.items():
            commits[spin] = partial(self.commit_property, key)
        for key, spin in (("shape_width", self.shape_rows.width), ("shape_height", self.shape_rows.height),
                          ("stroke_width", self.shape_rows.stroke_width),
                          ("corner_radius", self.shape_rows.radius), ("polygon_sides", self.shape_rows.sides)):
            commits[spin] = partial(self.commit_shape_property, key)
        return commits

    def _commit_pending_edits(self) -> None:
        """Validate what is still being typed: closing or saving must not lose it.

        Text fields only commit when they lose the focus, which neither the
        window's close button nor a keyboard shortcut moves.
        """
        if self._inline is not None:
            self._inline["editor"].finish(True)
        commits = self._pending_edit_commits()
        # The focus may sit in a child of the field (the line edit of a spin box).
        widget: QWidget | None = self.focusWidget()
        while widget is not None and widget not in commits:
            widget = widget.parentWidget()
        if widget is not None:
            if isinstance(widget, QAbstractSpinBox):
                widget.interpretText()  # keyboard tracking is off: the typed text is not the value yet
            commits[widget]()
        self._flush_pending_curve()

    # --- Canvas tools ----------------------------------------------------------------
    # Only one tool is active at a time; every activation goes through _clear_tools.

    def any_tool_active(self) -> bool:
        return bool(self.eraser_active or self.picker_active or self.paint_mode
                    or self.text_tool_active or self.selection_tool or self.shape_tool)

    def _clear_tools(self, keep: str | None = None):
        if keep != "eraser" and self.eraser_active:
            self.canvas.cancel_eraser_preview()
            self.eraser_active = False
            self.canvas.eraser_cursor_local = None
        if keep != "picker":
            self.picker_active = False
            self.picker_text_layer_id = None
        if keep != "paint":
            self.paint_mode = None
        if keep != "text":
            self.text_tool_active = False
        if keep != "select":
            self._leave_selection_tools()
        if keep != "shape":
            self.shape_tool = None
            self.canvas.shape_drag = None

    def _sync_tool_buttons(self):
        """Reflect the tool flags on every button, then refresh options and cursor."""
        pairs = [
            (self.eraser_btn, self.eraser_active),
            (self.picker_btn, self.picker_active and self.picker_target == "tools"),
            (self.text_picker_btn, self.picker_active and self.picker_target == "text"),
            (self.text_background_picker_btn,
             self.picker_active and self.picker_target == "text_background"),
            (self.paint_bucket_btn, self.paint_mode == "contiguous"),
            (self.paint_global_btn, self.paint_mode == "global"),
            (self.text_tool_btn, self.text_tool_active),
        ]
        pairs += [(button, self.selection_tool == tool)
                  for tool, button in self.selection_tool_buttons.items()]
        pairs += [(button, self.shape_tool == kind) for kind, button in self.shape_tool_buttons.items()]
        for button, checked in pairs:
            button.blockSignals(True)
            button.setChecked(bool(checked))
            button.blockSignals(False)
        for action, checked in ((self.eraser_action, self.eraser_active),
                                (self.text_tool_action, self.text_tool_active)):
            action.blockSignals(True)
            action.setChecked(checked)
            action.blockSignals(False)
        self.update_tool_options_visibility()
        self._refresh_color_tool_cursor()
        self.canvas.viewport().update()

    def deactivate_active_tools(self):
        """Leaving the Tools tab always returns the canvas to its neutral state."""
        if not self.any_tool_active():
            return
        self._clear_tools()
        self._sync_tool_buttons()

    def activate_picker(self, target: str, active: bool):
        if not active:
            self.deactivate_picker()
            return
        if target in ("text", "text_background"):
            layer = self.document.layer(self.selected_id)
            if not layer or layer.kind != "text" or layer.locked:
                self._sync_tool_buttons()
                self.statusBar().showMessage(
                    "Sélectionnez un calque texte déverrouillé", 3000
                )
                return
        self._clear_tools("picker")
        self.picker_text_layer_id = self.selected_id if target != "tools" else None
        self.picker_target = target
        self.picker_active = True
        self._sync_tool_buttons()
        self.statusBar().showMessage("Cliquez sur un pixel d'un calque image", 3000)

    def deactivate_picker(self):
        self.picker_active = False
        self._sync_tool_buttons()

    def _refresh_color_tool_cursor(self):
        if self.eraser_active:
            cursor = Qt.CursorShape.BlankCursor
        elif self.text_tool_active:
            cursor = Qt.CursorShape.IBeamCursor
        else:
            active = self.picker_active or self.paint_mode is not None or self.selection_tool or self.shape_tool
            cursor = Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        self.canvas.setCursor(cursor)

    def toggle_paint_mode(self, mode: str, active: bool):
        if active:
            self._clear_tools("paint")
            self.paint_mode = mode
            self._show_tool_target()
            self.statusBar().showMessage(
                "Cliquez dans une zone à remplir" if mode == "contiguous"
                else "Cliquez sur la couleur à remplacer dans tout le calque", 4000
            )
        elif self.paint_mode == mode:
            self.paint_mode = None
        self._sync_tool_buttons()

    def set_eraser_active(self, active: bool):
        self.canvas.cancel_eraser_preview()
        if active:
            self._clear_tools("eraser")
            self._show_tool_target()
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Gomme active · glisser pour effacer · [ et ] changent la taille", 4500
            )
        self.eraser_active = bool(active)
        self.canvas.eraser_cursor_local = None
        self._sync_tool_buttons()

    def set_text_tool_active(self, active: bool):
        if active:
            self._clear_tools("text")
            self.statusBar().showMessage(
                "Outil texte · cliquez sur le canvas pour écrire · double-clic sur un texte pour le modifier",
                5000,
            )
        self.text_tool_active = bool(active)
        self._sync_tool_buttons()

    def _leave_selection_tools(self):
        """Leaving the selection tools drops the selection and its outline (Ctrl+Z brings it back).

        A selection made from the menus with no selection tool active is kept.
        """
        was_active = bool(self.selection_tool)
        self.selection_tool = None
        self.canvas.cancel_selection_drag()
        if was_active and self.selection_mask is not None:
            self.deselect()

    def set_selection_tool(self, tool: str | None):
        if not tool:
            self._leave_selection_tools()
        elif tool != self.selection_tool:
            self.canvas.cancel_selection_drag()  # an outline being drawn belongs to the previous tool
        if tool:
            self._clear_tools("select")
            self._show_tool_target()
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Maj : ajouter · Alt : soustraire · Maj+Alt : intersection", 4500
            )
        self.selection_tool = tool or None
        self._sync_tool_buttons()

    def set_shape_tool(self, kind: str | None):
        if kind:
            self._clear_tools("shape")
            self.tabs.setCurrentWidget(self.tools_tab)
            self.statusBar().showMessage(
                "Glissez sur le canvas pour tracer la forme · un clic crée une forme de taille standard · "
                "la couleur choisie ci-dessus sert de remplissage", 5000)
        self.shape_tool = kind or None
        self._sync_tool_buttons()

    def commit_shape_property(self, key: str) -> bool:
        if self.refreshing:
            return False
        return self.set_shape_property(key, self.shape_rows.value(key))

    def set_shape_property(self, key: str, value) -> bool:
        """Change one property of the selected shape as an undoable step (values are clamped)."""
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.kind != "shape" or layer.locked:
            return False
        probe = deepcopy(layer)
        setattr(probe, key, value)
        if key == "stroke_color" and value and probe.stroke_width == 0:
            probe.stroke_width = 4.0  # a chosen outline colour must be visible
        if key == "shape_type" and value in OPEN_SHAPES and (probe.stroke_width == 0 or not probe.stroke_color):
            # A line or an arrow is only its outline (its fill is not drawn): give it one,
            # in the shape's colour, as a line drawn with the tool has.
            probe.stroke_width = probe.stroke_width or 6.0
            probe.stroke_color = probe.stroke_color or probe.fill_color or "#000000"
        probe.normalize_shape_fields()
        if probe == layer:
            return False

        def apply(doc):
            index = doc.layers.index(doc.layer(layer.id))
            doc.layers[index] = deepcopy(probe)

        return self.mutate("Modifier la forme", apply, layer.id)

    def choose_shape_color(self, key: str, title: str) -> bool:
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.kind != "shape" or layer.locked:
            return False
        color = QColorDialog.getColor(QColor(getattr(layer, key) or "#FFFFFF"), self, title)
        return color.isValid() and self.set_shape_property(key, color.name().upper())

    def create_shape(self, start: QPointF, end: QPointF, modifiers) -> bool:
        """Add the shape drawn with the active shape tool, as an editable layer."""
        if not self.shape_tool:
            return False
        layer = shape_from_drag(self.shape_tool, (start.x(), start.y()), (end.x(), end.y()),
                                bool(modifiers & Qt.KeyboardModifier.ShiftModifier), self.replacement_color)

        def add(doc):
            doc.layers.append(deepcopy(layer))

        if not self.mutate(f"Ajouter : {layer.name}", add, layer.id):
            return False
        self.select_layer(layer.id)
        return True

    def update_tool_options_visibility(self):
        """Only show the settings of the active tool."""
        eraser = self.eraser_active
        bucket = self.paint_mode is not None and not eraser
        self.eraser_settings.setVisible(eraser)
        self.paint_settings.setVisible(bucket)
        self.selection_settings.setVisible(bool(self.selection_tool))
        self.wand_settings.setVisible(self.selection_tool == "wand")
        for widget in (
            self.color_tools_label, self.color_editor,
            self.alternative_label, self.variations_widget,
        ):
            widget.setVisible(not eraser and not self.selection_tool)
        self._schedule_right_panel_layout()

    def toggle_lock(self, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            description = "Déverrouiller le calque" if layer.locked else "Verrouiller le calque"
            self.mutate(description, lambda doc: setattr(doc.layer(layer.id), "locked", not layer.locked), layer.id)

    def selected_image_item(self):
        scene = self.canvas.scene()
        if scene is None:
            return None
        return next((item for item in scene.items()
                     if item.data(0) == self.selected_id and isinstance(item, QGraphicsPixmapItem)), None)

    def copy_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText():
            focused.copy()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection():
            focused.copy()
            return True
        if self.selection_mask is not None:
            return self.copy_selection()
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à copier", 3000)
            return False
        try:
            pixels = self.layer_pixels(layer)
        except ValueError as exc:
            self.statusBar().showMessage(f"Copie impossible : {exc}", 5000)
            return False
        QApplication.clipboard().setImage(pil_to_qimage(pixels))
        self.statusBar().showMessage(f"Calque copié : {layer.name}", 3000)
        return True

    def _render_or_report(self, action: str, render):
        """Result of a render a tool needs, or None after telling why it failed (damaged image)."""
        try:
            return render()
        except RENDER_ERRORS as exc:
            self._report_failure(action, exc)
            return None

    def layer_pixels(self, layer: Layer) -> Image.Image:
        """Exact pixels of an image layer as shown (edits, mask and flips), for copies and exports.

        The displayed pixmap is not used: it is premultiplied, and a damaged image
        is shown as a hatched stand-in that must never be copied or exported.
        """
        try:
            image = render_layer_with_mask(layer, self.document)
        except RENDER_ERRORS as exc:
            raise ValueError(f"image illisible pour le calque « {layer.name} » ({exc})") from exc
        if layer.flip_horizontal:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if layer.flip_vertical:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        return image

    def cut_layer(self) -> bool:
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.hasSelectedText() and not focused.isReadOnly():
            focused.cut()
            return True
        if isinstance(focused, QPlainTextEdit) and focused.textCursor().hasSelection() and not focused.isReadOnly():
            focused.cut()
            return True
        if self.selection_mask is not None:
            return self.cut_selection()
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque image à couper", 3000)
            return False
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le couper", 3000)
            return False
        if self.copy_layer():
            self.delete_layer()
            return True
        return False

    def paste_image(self) -> bool:
        clipboard = QApplication.clipboard()
        image: QImage = clipboard.image()
        if image.isNull():
            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            if isinstance(focused, QPlainTextEdit) and clipboard.mimeData().hasText() and not focused.isReadOnly():
                focused.paste()
                return True
            self.statusBar().showMessage("Le presse-papiers ne contient pas d'image", 3000)
            return False
        data = qimage_png(image)
        holder = {}
        origin = None
        if self._clipboard_origin and self._clipboard_origin[1] == clipboard_fingerprint(image):
            origin = self._clipboard_origin[0]

        def add(doc):
            layer = doc.add_image_bytes(data, "Image collée", center=origin is None)
            if origin is not None:
                layer.x, layer.y = float(origin[0]), float(origin[1])
            holder["id"] = layer.id

        if not self.mutate("Coller une image", add, lambda: holder["id"]):
            return False
        self.select_layer(holder["id"])
        self.tabs.setCurrentIndex(0)
        return True

    def flip_layer_horizontal(self):
        self._flip_selected_layer("flip_horizontal", "Retourner horizontalement")

    def flip_layer_vertical(self):
        self._flip_selected_layer("flip_vertical", "Retourner verticalement")

    def _flip_selected_layer(self, attribute: str, description: str):
        layer = self.document.layer(self.selected_id)
        if not layer:
            self.statusBar().showMessage("Sélectionnez un calque", 3000)
            return
        if layer.locked:
            self.statusBar().showMessage("Déverrouillez le calque avant de le retourner", 3000)
            return
        self.mutate(description,
                    lambda doc: setattr(doc.layer(layer.id), attribute,
                                        not getattr(doc.layer(layer.id), attribute)), layer.id)

    def show_canvas_context_menu(self, global_position):
        layer = self.document.layer(self.selected_id)
        is_image = bool(layer and layer.kind == "image")
        editable_image = bool(is_image and not layer.locked)
        editable_layer = bool(layer and not layer.locked)
        menu = QMenu(self)
        menu.setObjectName("canvasContextMenu")
        copy_action = menu.addAction("Copier\tCtrl+C")
        cut_action = menu.addAction("Couper\tCtrl+X")
        paste_action = menu.addAction("Coller\tCtrl+V")
        copy_action.setEnabled(is_image or self.selection_mask is not None)
        cut_action.setEnabled(editable_image)
        paste_action.setEnabled(not QApplication.clipboard().image().isNull())
        copy_action.triggered.connect(self.copy_layer)
        cut_action.triggered.connect(self.cut_layer)
        paste_action.triggered.connect(self.paste_image)
        duplicate_action = menu.addAction("Dupliquer\tCtrl+D")
        duplicate_action.setEnabled(bool(layer and not layer.locked))
        duplicate_action.triggered.connect(self.duplicate_layer)
        menu.addSeparator()
        lock_action = menu.addAction("Déverrouiller" if layer and layer.locked else "Verrouiller")
        lock_action.setEnabled(layer is not None)
        lock_action.triggered.connect(self.toggle_lock)
        horizontal = menu.addAction("Retourner horizontalement")
        vertical = menu.addAction("Retourner verticalement")
        horizontal.setEnabled(editable_layer)
        vertical.setEnabled(editable_layer)
        horizontal.triggered.connect(self.flip_layer_horizontal)
        vertical.triggered.connect(self.flip_layer_vertical)
        if self.selection_mask is not None:
            menu.addSeparator()
            menu.addAction("Copier vers un nouveau calque	Ctrl+J").triggered.connect(
                lambda: self.selection_to_new_layer(False))
            menu.addAction("Couper vers un nouveau calque	Ctrl+Maj+J").triggered.connect(
                lambda: self.selection_to_new_layer(True))
            menu.addAction("Effacer le contenu sélectionné	Suppr").triggered.connect(
                self.clear_selection_content)
            menu.addAction("Désélectionner	Ctrl+Maj+A").triggered.connect(self.deselect)
        menu.addSeparator()
        background_action = menu.addAction("Supprimer l'arrière-plan…")
        background_action.setEnabled(editable_image)
        background_action.triggered.connect(self.remove_background)
        trim_action = menu.addAction("Rogner les marges transparentes")
        trim_action.setEnabled(editable_image)
        trim_action.triggered.connect(lambda: self.trim_layer_margins())
        save_layer_action = menu.addAction("Enregistrer le calque sous…")
        save_layer_action.setEnabled(is_image)
        save_layer_action.triggered.connect(self.export_selected_layer)
        menu.addSeparator()
        delete_action = menu.addAction("Supprimer")
        delete_action.setEnabled(bool(layer and not layer.locked))
        delete_action.triggered.connect(self.delete_layer)
        menu.exec(global_position)

    def add_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des images", self.initial_path("import"),
                     "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;Tous les fichiers (*)")
        if paths:
            self.remember_directory("import", Path(paths[0]).parent)
        self._import_paths(paths)

    def _import_paths(self, paths):
        for raw_path in paths or []:
            path = Path(raw_path)
            try:
                data = path.read_bytes()
            except OSError as exc:
                QMessageBox.warning(self, "Import impossible", f"{raw_path}\n{exc}")
                continue
            holder = {}

            def add(doc, data=data, name=path.stem, holder=holder):
                holder["id"] = doc.add_image_bytes(data, name).id

            # Un fichier illisible ou trop grand est signalé par mutate et
            # n'ajoute aucune étape à l'historique.
            if self.mutate(f"Importer {path.stem}", add, lambda holder=holder: holder["id"]):
                self.select_layer(holder["id"])

    def add_text(self):
        content, ok = QInputDialog.getText(self, "Nouveau calque texte", "Votre texte :")
        if not ok or not content.strip():
            return
        holder = {}
        def add(doc):
            layer = doc.add_text(content)
            layer.font_family = resolve_font_family(self.last_font_family)
            holder['id'] = layer.id
        if self.mutate("Ajouter un texte", add, lambda: holder["id"]):
            self.select_layer(holder['id'])
            self.tabs.setCurrentIndex(0)

    def delete_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            if self.mutate("Supprimer le calque", lambda doc: doc.layers.remove(doc.layer(layer.id))):
                self.select_layer(None)
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le supprimer", 3000)

    def duplicate_layer(self):
        layer = self.document.layer(self.selected_id)
        if layer and not layer.locked:
            result = {}
            if self.mutate("Dupliquer le calque", lambda doc: result.update(id=doc.duplicate_layer(layer.id).id),
                           lambda: result["id"]):
                self.select_layer(result['id'])
        elif layer:
            self.statusBar().showMessage("Déverrouillez le calque avant de le dupliquer", 3000)

    def reorder_layer(self, direction: int, layer_id: str | None = None):
        layer = self.document.layer(layer_id or self.selected_id)
        if layer:
            idx = self.document.layers.index(layer)
            if 0 <= idx + direction < len(self.document.layers):
                self.mutate("Changer l'ordre des calques", lambda doc: doc.reorder_layer(layer.id, direction), layer.id)

    # --- Element template library ----------------------------------------------------------

    def add_image_layer(self, data: bytes, name: str) -> bool:
        """Add PNG bytes as a centred image layer (tokens, imports from tools)."""
        holder = {}

        def add(doc):
            holder["id"] = doc.add_image_bytes(data, name).id

        if not self.mutate(f"Ajouter : {name}", add, lambda: holder["id"]):
            return False
        self.select_layer(holder["id"])
        return True

    def add_sprite_layers(self, sprites, sheet_name: str) -> bool:
        """Add extracted sprites as image layers grouped in a folder, laid out in their grid order."""
        room = MAX_LAYERS - len(self.document.layers)
        if len(sprites) > room:
            QMessageBox.warning(
                self, "Trop de sprites",
                f"{len(sprites)} sprites ne tiennent pas dans le projet : il peut encore recevoir "
                f"{max(0, room)} calque(s), pour un maximum de {MAX_LAYERS}.\n\n"
                + "Agrandissez les cellules, décochez des sprites ou exportez-les en PNG.")
            return False
        images = []
        for row, column, image in sprites:
            output = BytesIO()
            image.save(output, format="PNG")
            images.append((row, column, image.size, output.getvalue()))

        def add(doc):
            ids, x, y, line = [], 0.0, 0.0, 0
            for row, column, (width, height), data in images:
                layer = doc.add_image_bytes(data, f"{sheet_name} {row + 1}·{column + 1}", center=False)
                if x and x + width > doc.width:
                    x, y, line = 0.0, y + line, 0
                layer.x, layer.y = x, y
                x += width
                line = max(line, height)
                ids.append(layer.id)
            doc.create_folder(ids, sheet_name)

        if not self.mutate(f"Ajouter {len(images)} sprite(s)", add):
            return False
        self.statusBar().showMessage(f"{len(images)} sprite(s) ajouté(s) dans le dossier « {sheet_name} »", 5000)
        return True

    # Tool dialogs are deleted after use: each one keeps its source images in memory.

    def open_token_creator(self) -> None:
        dialog = TokenDialog(self)
        try:
            layer = self.document.layer(self.selected_id)
            if layer is not None and layer.kind == "image":
                dialog.use_selected_layer()
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_sprite_slicer(self) -> None:
        dialog = SpriteSheetDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def open_template_library(self) -> bool:
        dialog = TemplateLibraryDialog(self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_entry() is None:
                return False
            name, (kind, value), action = dialog.selected_name(), dialog.selected_entry(), dialog.action
            elements = dialog.load_selected()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Modèle illisible", f"{dialog.selected_name()}\n{exc}")
            return False
        finally:
            dialog.deleteLater()
        if action == "edit" and kind == "user":
            return self.edit_element_template(Path(value), name, elements)
        return self.insert_template_elements(elements, name)

    def insert_template_elements(self, elements: Document, name: str) -> bool:
        """Insert a template's layers, centred and on top, as separate editable layers."""
        offset = ((self.document.width - elements.width) / 2, (self.document.height - elements.height) / 2)
        holder = {}

        def apply(doc):
            holder["ids"] = insert_elements(doc, elements, offset)

        if not self.mutate(f"Insérer le modèle « {name} »", apply,
                           lambda: holder["ids"][-1] if holder["ids"] else None):
            return False
        self.set_checked_layers(holder["ids"])
        if holder["ids"]:
            self.select_layer(holder["ids"][-1])
        self.statusBar().showMessage("Modèle inséré · ses calques sont cochés : glissez-en un pour tout déplacer", 5000)
        return True

    def edit_element_template(self, path: Path, name: str, elements: Document) -> bool:
        """Open an element template as the document; Save writes it back to the library."""
        if not self.maybe_save():
            return False
        try:
            self._start_session(elements, None)
        except Exception as exc:
            QMessageBox.critical(self, "Modèle illisible", str(exc))
            return False
        self.editing_template = {"path": path, "name": name}
        self.template_origin = path.stem
        self.update_title()
        self.statusBar().showMessage("Modification du modèle · Sauvegarder le projet l'enregistre", 6000)
        return True

    @staticmethod
    def _changes_document(command) -> bool:
        """True for a document edit, or a macro containing one; False for selections."""
        if isinstance(command, DocumentCommand):
            return True
        return any(MainWindow._changes_document(command.child(index))
                   for index in range(command.childCount()))

    def is_modified(self) -> bool:
        """Unsaved document edits; selection changes alone never count.

        The undo stack's clean index marks the saved state; the document is
        modified when a document edit lies between that state and the current one.
        """
        clean, current = self.undo_stack.cleanIndex(), self.undo_stack.index()
        if clean < 0:
            return True  # the saved state left the history, or restored unsaved work
        return any(self._changes_document(self.undo_stack.command(index))
                   for index in range(min(clean, current), max(clean, current)))

    def update_title(self, *_):
        if self.editing_template is not None:
            name = f"Modèle : {self.editing_template['name']}"
        else:
            name = self.project_path.name if self.project_path else "Sans titre"
        modified = " *" if self.is_modified() else ""
        self.setWindowTitle(f"{name}{modified} — Manta Layers {__version__} | ReefKit")

    def update_zoom(self):
        self.zoom_label.setText(f"{self.canvas.transform().m11() * 100:.0f} %")

    def change_zoom(self, factor):
        self.canvas.zoom_by(factor)

    def about(self):
        QMessageBox.about(self, "À propos de Manta Layers", f"""<h3>Manta Layers {__version__}</h3>
        <p>Éditeur d'images local à calques · Univers Blue Shrimp / ReefKit.</p>
        <p>Images, textes multilignes courbés sur trajectoire, calques, transformations,
        gomme et remplissages non destructifs, sélections et masques de calque, suppression
        locale de l'arrière-plan, modèles, historique, projets natifs et exports.</p>
        <p>Code source sous licence MIT ; illustrations et mascottes : tous droits réservés.</p>
        <p>La déformation Warp des lettres et le recadrage libre sont prévus pour les prochaines versions.</p>""")

    def dragEnterEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self.image_paths_from_mime(event.mimeData())
        if paths:
            self._import_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def image_paths_from_mime(mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_SUFFIXES]

    # --- Keyboard nudging ---------------------------------------------------------------

    def nudge_layer(self, dx: float, dy: float) -> bool:
        """Move the selected layer with the arrow keys; a burst of presses is one undo step."""
        layer = self.document.layer(self.selected_id)
        if layer is None or layer.locked:
            return False
        before = self._current_snapshot()
        after = self.document.clone()
        target = after.layer(layer.id)
        if target is None:
            return False
        target.x += dx
        target.y += dy
        self._push(DocumentCommand(self, before, after, "Déplacer au clavier", layer.id, layer.id,
                                   merge_key=("nudge", layer.id)))
        return True

    def _wait_for_background_work(self):
        """A background removal or download closed mid-way must end before the window is destroyed."""
        if not background_dialog.orphan_workers_running():
            return
        self.statusBar().showMessage("Fin du détourage en cours avant la fermeture…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            QApplication.processEvents()
            background_dialog.wait_for_orphan_workers()
        finally:
            QApplication.restoreOverrideCursor()

    def closeEvent(self, event):
        if self.maybe_save():
            self.refreshing = True
            self._wait_for_background_work()
            self.autosave_timer.stop()
            self.recovery.close()
            event.accept()
        else:
            event.ignore()
