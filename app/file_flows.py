"""Document sessions of the main window: new, open, save, export, recovery.

A mixin of MainWindow: these methods use its document, undo stack and
canvas. Keeping them here leaves window.py to the interface and the tools.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from . import export, selection
from .dialogs import NewProjectDialog, ResizeDocumentDialog
from .graphics import UNREADABLE_ROLE, font_is_installed, make_scene, qimage_to_pil, render_document
from .model import MAX_DOCUMENT_PIXELS, Document, Layer
from .paths import safe_file_stem
from .recovery import SessionRecovery, recovery_text
from .storage import open_project, save_project
from .templates import save_template
from .theme import dialog_button_style

# While the document has unsaved changes, a recovery copy is written this often.
RECOVERY_INTERVAL_MS = 60_000


# A mixin of MainWindow: type checkers see the window it is mixed into.
if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow as _WindowBase
else:
    _WindowBase = object


class DocumentFlowsMixin(_WindowBase):
    """Creating, opening, saving and exporting documents, and crash recovery."""

    if TYPE_CHECKING:
        # Attributes set by MainWindow; everything else comes from it too.
        _collapsed_folders: dict[str, bool]

        def __getattr__(self, name: str) -> Any: ...

    # --- New, open, save -------------------------------------------------------------

    def new_document(self):
        if not self.maybe_save():
            return
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        try:
            document = dialog.document()
            template = dialog.selected_template() if dialog.tabs.currentIndex() == 1 else None
            self._start_session(document, None)
        except Exception as exc:
            QMessageBox.critical(self, "Création impossible", str(exc))
            return
        finally:
            dialog.deleteLater()
        self.editing_template = None
        self.template_origin = template.stem if template is not None else None
        self.update_title()
        self._warn_missing_fonts(document)

    def _make_scene(self, document: Document, tolerate_all: bool = False):
        """Canvas scene; images already damaged when the project was opened are shown hatched.

        A change that makes another image unreadable is still refused.
        """
        known = self._unreadable_assets

        def tolerated(layer: Layer) -> bool:
            return tolerate_all or layer.asset in known or (layer.mask is not None and layer.mask in known)

        return make_scene(document, interactive=True, tolerate_unreadable=tolerated)

    def _start_session(self, document: Document, project_path: Path | None, unsaved: bool = False) -> None:
        """Show another document from scratch: history, selection, view and recovery copy.

        Raises if the document cannot be shown; the current one then stays as it was.
        """
        scene = self._make_scene(document, tolerate_all=True)
        unreadable = {item.data(0) for item in scene.items() if item.data(UNREADABLE_ROLE)}
        self._unreadable_assets = {asset for layer in document.layers if layer.id in unreadable
                                   for asset in (layer.asset, layer.mask) if asset}
        self._collapsed_folders = {}
        self.install_document(document, None, scene=scene)
        self.project_path = project_path
        self.undo_stack.clear()
        if unsaved:
            self.undo_stack.resetClean()  # restored work is unsaved
        else:
            self.undo_stack.setClean()
        self._reset_selection()
        self.canvas.fit_document()
        self.update_title()
        # The copy of the document left behind must not be offered after a crash.
        self.recovery.discard(self.recovery.session_id)
        self._warn_unreadable_layers()

    def _warn_unreadable_layers(self) -> None:
        """Name the image layers shown hatched because their pixels cannot be decoded."""
        unreadable = {item.data(0) for item in self.canvas_scene.items() if item.data(UNREADABLE_ROLE)}
        names = [layer.name for layer in self.document.layers if layer.id in unreadable]
        if names:
            QMessageBox.warning(
                self, "Images illisibles",
                "Ces calques ont une image endommagée, affichée hachurée :\n\n" + "\n".join(names)
                + "\n\nLe reste du projet est modifiable. Supprimez ou remplacez ces calques "
                "avant d'exporter l'image.")

    def resize_document(self):
        dialog = ResizeDocumentDialog(self.document.width, self.document.height, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            width, height = dialog.dimensions()
        finally:
            dialog.deleteLater()
        self.set_document_size(width, height)

    def set_document_size(self, width: int, height: int) -> bool:
        """Change the working area; the selection is cut to it in the same undo step."""
        if (width, height) == (self.document.width, self.document.height):
            return False

        def resize(doc):
            doc.width = width
            doc.height = height

        label = f"Redimensionner le document en {width} × {height} px"
        resized = (selection.resize_canvas(self.selection_mask, (width, height))
                   if self.selection_mask is not None else None)
        self.undo_stack.beginMacro(label)
        try:
            # Undoing restores the whole selection, not the part left by the smaller frame.
            self.set_selection(resized, label)
            done = self.mutate(label, resize, self.selected_id)
        finally:
            self.undo_stack.endMacro()
        if done:
            self.canvas.fit_document()
        return done

    def maybe_save(self) -> bool:
        self._commit_pending_edits()
        if not self.is_modified():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText("Enregistrer les modifications du document ?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        box.button(QMessageBox.StandardButton.Save).setStyleSheet(dialog_button_style("primary"))
        box.button(QMessageBox.StandardButton.Discard).setStyleSheet(dialog_button_style("danger"))
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        result = box.standardButton(box.clickedButton())
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save_document()
        return True

    def open_document(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un projet", self.initial_path("project"),
            "Projet Manta Layers (*.manta);;Ancien projet Manta Layers (*.mcrab)"
        )
        if not path:
            return
        opened_path = Path(path)
        try:
            doc = open_project(path)
            self._start_session(doc, opened_path if opened_path.suffix.lower() == ".manta" else None)
        except Exception as exc:
            QMessageBox.critical(self, "Projet illisible", str(exc))
            return
        self.editing_template = self.template_origin = None
        self.remember_directory("project", opened_path.parent)
        self.update_title()
        self.statusBar().showMessage(f"Projet chargé : {opened_path.name}", 5000)
        self._warn_missing_fonts(doc)

    def _warn_missing_fonts(self, doc: Document):
        missing = sorted({layer.font_family for layer in doc.layers
                          if layer.kind == "text" and not font_is_installed(layer.font_family)})
        if not missing:
            return
        QMessageBox.information(
            self, "Polices absentes",
            "Ces polices ne sont pas disponibles sur cet ordinateur :\n\n"
            + "\n".join(f"• {name}" for name in missing)
            + "\n\nLe texte s'affiche avec une police de remplacement. Le nom d'origine reste "
            "enregistré dans le projet tant que vous ne choisissez pas une autre police. "
            "Pour retrouver le rendu exact, utilisez Fichier > Importer une police…",
        )

    def save_document(self) -> bool:
        if self.editing_template is not None:
            return self._write_template_back()
        if self.project_path is None:
            return self.save_as_document()
        return self._write_project(self.project_path)

    def save_as_document(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder le projet", self.initial_path("project", f"{self._file_stem()}.manta"),
            "Projet Manta Layers (*.manta)"
        )
        if not path:
            return False
        chosen = Path(path)
        destination = chosen
        if destination.suffix.lower() != ".manta":
            destination = destination.with_name(destination.name + ".manta")
        if not self._confirm_completed_path(chosen, destination, "Sauvegarder le projet"):
            return False
        # Le chemin du projet ne change qu'après un enregistrement réussi.
        if not self._write_project(destination):
            return False
        self.remember_directory("project", destination.parent)
        self.project_path = destination
        self.editing_template = None  # "save as" turns an edited template into a project
        self.update_title()
        return True

    def _write_template_back(self) -> bool:
        """Save the element template being edited, with a fresh thumbnail."""
        self._commit_pending_edits()
        template = self.editing_template
        if template is None:
            return False
        try:
            save_template(self.document, template["name"], self._template_thumbnail(self.document),
                          destination=template["path"], kind="elements")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Enregistrement du modèle impossible", str(exc))
            return False
        self.undo_stack.setClean()
        self.recovery.discard(self.recovery.session_id)
        self.statusBar().showMessage(f"Modèle enregistré : {template['name']}", 5000)
        return True

    # --- Remembered folders ----------------------------------------------------------------
    # The last folder of each kind of operation (project, export, import, token,
    # sprites) is kept in QSettings. A document created from a template also
    # keeps its own folders, so that templates never overwrite each other's.

    def _setting_keys(self, kind: str) -> list[str]:
        keys = [f"paths/templates/{self.template_origin}/{kind}"] if self.template_origin else []
        return keys + [f"paths/{kind}"]

    def initial_path(self, kind: str, filename: str = "") -> str:
        """Folder (optionally with a file name) where a file dialog of this kind should open."""
        directory = None
        for key in self._setting_keys(kind):
            value = str(self.settings.value(key, "") or "")
            if value and Path(value).is_dir():
                directory = value
                break
        if directory is None:
            location = (QStandardPaths.StandardLocation.DocumentsLocation if kind == "project"
                        else QStandardPaths.StandardLocation.PicturesLocation)
            directory = QStandardPaths.writableLocation(location) or str(Path.home())
        return str(Path(directory) / filename) if filename else directory

    def remember_directory(self, kind: str, directory) -> None:
        for key in self._setting_keys(kind):
            self.settings.setValue(key, str(directory))

    def _file_stem(self) -> str:
        if self.editing_template is not None:
            return self.editing_template["name"]
        return self.project_path.stem if self.project_path else "MantaLayers"

    def _write_project(self, destination: Path) -> bool:
        self._commit_pending_edits()
        try:
            save_project(self.document, destination)
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement impossible", str(exc))
            return False
        self.undo_stack.setClean()
        self.recovery.discard(self.recovery.session_id)  # the project file is now up to date
        self.statusBar().showMessage(f"Enregistré : {destination.name}", 5000)
        return True

    def save_as_template(self):
        self._commit_pending_edits()
        default_name = self.project_path.stem if self.project_path else "Nouveau modèle"
        name, accepted = QInputDialog.getText(
            self, "Enregistrer comme modèle", "Nom du modèle :", text=default_name
        )
        if not accepted or not name.strip():
            return
        try:
            destination = self._confirm_template_replacement(name, "preset")
            if destination is False:
                return
            path = save_template(self.document, name, self._template_thumbnail(self.document),
                                 destination=destination)
            self.statusBar().showMessage(
                f"Modèle enregistré : {name.strip()} · {path.parent}", 6000
            )
        except Exception as exc:
            QMessageBox.critical(self, "Enregistrement du modèle impossible", str(exc))

    def export_image(self):
        if self.document.width * self.document.height > MAX_DOCUMENT_PIXELS:
            QMessageBox.critical(self, "Export impossible",
                                 f"Document trop grand pour l'export (> {MAX_DOCUMENT_PIXELS // 1_000_000} "
                                 "millions de pixels). Réduisez ses dimensions.")
            return
        self._export(f"{self._file_stem()}.png", "Exporter l'image",
                     lambda: qimage_to_pil(render_document(self.document)), "Export terminé", "Export impossible")

    def export_selected_layer(self):
        layer = self.document.layer(self.selected_id)
        item = self.selected_image_item()
        if not layer or layer.kind != "image" or item is None:
            self.statusBar().showMessage("Sélectionnez un calque image à enregistrer", 3000)
            return
        self._export(f"{safe_file_stem(layer.name, 'Calque')}.png", "Enregistrer le calque sous",
                     lambda: qimage_to_pil(item.pixmap().toImage()), "Calque enregistré",
                     "Enregistrement du calque impossible")

    def _confirm_completed_path(self, chosen: Path, destination: Path, title: str) -> bool:
        """Ask before replacing ``destination`` when an extension was added to the name chosen.

        The file dialog only confirmed overwriting the name typed, not the completed one.
        """
        if destination == chosen or not destination.exists():
            return True
        answer = QMessageBox.question(
            self, title, f"{destination.name} existe déjà. Le remplacer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _export(self, filename: str, title: str, render, done: str, failed: str) -> Path | None:
        """Ask where to save, then write the rendered image; the folder is remembered."""
        self._commit_pending_edits()
        path, chosen_filter = QFileDialog.getSaveFileName(
            self, title, self.initial_path("export", filename), export.FILE_FILTERS)
        if not path:
            return None
        chosen = Path(path)
        self.remember_directory("export", chosen.parent)
        destination = export.with_image_suffix(chosen, chosen_filter)
        if not self._confirm_completed_path(chosen, destination, title):
            return None
        try:
            export.save_image(render(), destination)
        except Exception as exc:
            QMessageBox.critical(self, failed, str(exc))
            return None
        self.statusBar().showMessage(f"{done} : {destination}", 6000)
        return destination

    # --- Session recovery ------------------------------------------------------------
    # While the document has unsaved changes, a copy is written every minute (see
    # app/recovery.py); at start-up, the copies of crashed sessions are offered.

    def _setup_recovery(self):
        self.recovery = SessionRecovery(self.recovery_dir, self)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(RECOVERY_INTERVAL_MS)
        self.autosave_timer.timeout.connect(lambda: self.autosave_now(background=True))
        self.autosave_timer.start()
        QTimer.singleShot(0, self.offer_session_recovery)

    def autosave_now(self, background: bool = False) -> bool:
        """Write the recovery copy if the document has unsaved changes; True when written (or started)."""
        if not self.is_modified():
            # Saved, or undone back to the saved state: a copy written before is stale.
            if self.recovery.autosaved_revision is not None:
                self.recovery.discard(self.recovery.session_id)
            return False
        return self.recovery.write(self.document, self._revision, self.project_path, background)

    def offer_session_recovery(self) -> bool:
        """Offer the copies left by crashed sessions, newest first; True when one was restored.

        Each copy is restored, deleted or kept for the next start, as the user
        chooses: a copy is never deleted without having been shown. Only one
        copy can be restored (the window holds one document); the others stay.
        """
        candidates = self.recovery.candidates()
        restored = False
        try:
            for index, candidate in enumerate(candidates):
                choice = self._ask_recovery(candidate, index, len(candidates))
                if choice == "later":
                    break
                if choice == "discard":
                    self.recovery.discard(candidate["id"])
                    continue
                restored = self._restore_recovery(candidate)
                break
        finally:
            for candidate in candidates:
                candidate["lock"].unlock()
        return restored

    def _ask_recovery(self, candidate: dict, index: int, count: int) -> str:
        """Ask what to do with one recovery copy: "restore", "discard" or "later"."""
        text, details = recovery_text(candidate, index, count)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restaurer la session")
        box.setText(text)
        box.setInformativeText(details)
        restore = box.addButton("Restaurer", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Supprimer", QMessageBox.ButtonRole.DestructiveRole)
        later = box.addButton("Plus tard", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore)
        box.setEscapeButton(later)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is restore:
            return "restore"
        return "discard" if clicked is discard else "later"

    def _restore_recovery(self, candidate: dict) -> bool:
        original = candidate["meta"].get("project_path")
        original_path = Path(original) if isinstance(original, str) and original else None
        try:
            document = open_project(candidate["project"])
            self._start_session(document, original_path if original_path is not None
                                and original_path.suffix.lower() == ".manta" else None, unsaved=True)
        except Exception as exc:
            QMessageBox.warning(self, "Restauration impossible",
                                f"{exc}\n\nLa copie reste disponible : {candidate['project']}")
            return False
        # The restored work now belongs to this session: its own copies take over.
        self.recovery.discard(candidate["id"])
        return True
