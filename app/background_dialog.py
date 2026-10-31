"""Dialog previewing a background removal before it is applied."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from . import background
from .graphics import checker_brush, pil_to_qimage

PREVIEW_SIZE = (420, 280)


class RemovalWorker(QThread):
    """Runs the ONNX model outside the UI thread; the result is read after ``finished``."""

    progressed = Signal(str, int)

    def __init__(self, image: Image.Image, model_path: Path, parent=None):
        super().__init__(parent)
        self.image = image
        self.model_path = model_path
        self.mask: Image.Image | None = None
        self.error: str | None = None

    def run(self):
        try:
            self.mask = background.onnx_mask(self.image, self.model_path, self.progressed.emit)
        except background.BackgroundRemovalError as exc:
            self.error = str(exc)
        except Exception as exc:  # unexpected failures are reported, never fatal
            self.error = f"Erreur inattendue : {exc}"


class DownloadWorker(QThread):
    progressed = Signal(str, int)

    def __init__(self, name: str, destination: Path, parent=None):
        super().__init__(parent)
        self.name = name
        self.destination = destination
        self.cancel_requested = False
        self.error: str | None = None

    def run(self):
        try:
            background.download_model(self.name, self.destination, self.progressed.emit,
                                      lambda: self.cancel_requested)
        except background.BackgroundRemovalError as exc:
            self.error = str(exc)
        except Exception as exc:  # never report an unexpected failure as an installed model
            self.error = f"Erreur inattendue : {exc}"


class BackgroundRemovalDialog(QDialog):
    """Choose a method, preview the mask, then apply it as a mask or a new layer."""

    def __init__(self, image: Image.Image, layer_name: str, has_mask: bool,
                 models_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Supprimer l'arrière-plan — {layer_name}")
        self.setMinimumWidth(520)
        self.image = image
        self.models_dir = Path(models_dir) if models_dir is not None else background.models_directory()
        self.raw_mask: Image.Image | None = None
        self.worker: QThread | None = None
        # Thread still running after the dialog closed; the dialog is deleted after it.
        self._orphan: QThread | None = None
        layout = QVBoxLayout(self)

        explanation = QLabel(
            "Supprime l'arrière-plan entier de l'image, localement, sans rien envoyer sur Internet. "
            "La sélection d'un objet précis au clic n'est pas prise en charge."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        layout.addWidget(explanation)

        form = QFormLayout()
        method_row = QHBoxLayout()
        self.method = QComboBox()
        method_row.addWidget(self.method, stretch=1)
        self.download_button = QPushButton("Télécharger un modèle…")
        self.download_button.clicked.connect(self.download_default_model)
        method_row.addWidget(self.download_button)
        self.folder_button = QPushButton("Dossier des modèles")
        self.folder_button.setToolTip("Placez ici un fichier .onnx de la famille U²-Net ou IS-Net")
        self.folder_button.clicked.connect(self.open_models_folder)
        method_row.addWidget(self.folder_button)
        form.addRow("Méthode", method_row)
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 255)
        self.tolerance.setValue(32)
        self.tolerance.setToolTip("Écart toléré avec la couleur dominante des bords")
        form.addRow("Tolérance", self.tolerance)
        self.hard_edges = QCheckBox("Bords nets (pixel art)")
        form.addRow("Contours", self.hard_edges)
        self.feather = QSpinBox()
        self.feather.setRange(0, 20)
        self.feather.setSuffix(" px")
        form.addRow("Adoucissement", self.feather)
        layout.addLayout(form)

        self.preview_label = QLabel()
        self.preview_label.setFixedSize(*PREVIEW_SIZE)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.as_mask = QRadioButton("Appliquer comme masque du calque (modifiable ensuite)")
        self.as_layer = QRadioButton("Créer un nouveau calque détouré (l'original est masqué)")
        self.as_mask.setChecked(True)
        layout.addWidget(self.as_mask)
        layout.addWidget(self.as_layer)
        self.keep_existing = QCheckBox("Conserver le masque actuel du calque")
        self.keep_existing.setChecked(True)
        self.keep_existing.setVisible(has_mask)
        layout.addWidget(self.keep_existing)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Appliquer")
        self.apply_button.setProperty("variant", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        self.preview_button = self.buttons.addButton("Calculer l'aperçu", QDialogButtonBox.ButtonRole.ActionRole)
        self.preview_button.clicked.connect(self.compute)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Colour previews are quick: refresh them shortly after a setting changes.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._auto_refresh)
        self.tolerance.valueChanged.connect(self._settings_changed)
        self.hard_edges.toggled.connect(self._settings_changed)
        self.feather.valueChanged.connect(self._settings_changed)
        self.method.currentIndexChanged.connect(self._method_changed)
        self.populate_methods()

    # --- Methods -----------------------------------------------------------------------

    def populate_methods(self, select: Path | None = None):
        self.method.blockSignals(True)
        self.method.clear()
        self.method.addItem("Couleur de fond (sans IA)", "colour")
        runtime = background.onnx_runtime_available()
        models = background.installed_models(self.models_dir) if runtime else []
        for path in models:
            self.method.addItem(f"IA locale : {background.spec_for(path).label}", str(path))
        if not runtime:
            self.method.addItem("IA locale — onnxruntime non installé", None)
        elif not models:
            self.method.addItem("IA locale — aucun modèle installé", None)
        for index in range(self.method.count()):
            if self.method.itemData(index) is None:
                self.method.model().item(index).setEnabled(False)
        if select is not None:
            self.method.setCurrentIndex(max(0, self.method.findData(str(select))))
        self.method.blockSignals(False)
        self.download_button.setVisible(runtime)
        self._method_changed()

    def _is_colour(self) -> bool:
        return self.method.currentData() == "colour"

    def _method_changed(self, *_args):
        self.tolerance.setEnabled(self._is_colour())
        self.raw_mask = None
        if not background.onnx_runtime_available():
            self._set_status("Pour la méthode IA : pip install -r requirements-ai.txt, "
                             "puis placez ou téléchargez un modèle.")
        elif self._is_colour():
            self._set_status("Idéale pour un fond uni ou un pixel art.")
        else:
            self._set_status("Cliquez sur « Calculer l'aperçu » pour analyser l'image.")
        self._update_buttons()
        if self._is_colour():
            self.refresh_timer.start()
        else:
            self._show_preview()

    def _settings_changed(self, *_args):
        if self._is_colour():
            self.refresh_timer.start()
        else:
            self._show_preview()

    def _auto_refresh(self):
        if self._is_colour() and self.worker is None:
            self.compute()

    # --- Computation -----------------------------------------------------------------

    def compute(self):
        if self.worker is not None:
            return
        if self._is_colour():
            self.raw_mask = background.border_colour_mask(self.image, self.tolerance.value())
            self._set_status("Aperçu calculé.")
            self._show_preview()
            return
        model = self.method.currentData()
        if not model:
            return
        self.worker = RemovalWorker(self.image, Path(model), self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished.connect(self._removal_finished)
        self.progress.setValue(0)
        self.progress.show()
        self._update_buttons()
        self.worker.start()

    def _on_progress(self, message: str, percent: int):
        self._set_status(message)
        self.progress.setValue(percent)

    def _removal_finished(self):
        worker, self.worker = self.worker, None
        if worker is None:  # the dialog closed meanwhile
            return
        self.progress.hide()
        if worker.error:
            self.raw_mask = None
            self._set_status(worker.error)
        else:
            self.raw_mask = worker.mask
            self._set_status("Aperçu calculé. Vérifiez-le avant d'appliquer.")
        self._show_preview()
        self._update_buttons()

    def result_mask(self) -> Image.Image | None:
        if self.raw_mask is None:
            return None
        return background.refine(self.raw_mask, self.hard_edges.isChecked(), self.feather.value())

    def _show_preview(self):
        width, height = PREVIEW_SIZE
        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.fillRect(canvas.rect(), checker_brush())
        mask = self.result_mask()
        shown = background.preview(self.image, mask) if mask is not None else self.image
        pixmap = QPixmap.fromImage(pil_to_qimage(shown.convert("RGBA"))).scaled(
            width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap((width - pixmap.width()) // 2, (height - pixmap.height()) // 2, pixmap)
        painter.end()
        self.preview_label.setPixmap(canvas)
        self._update_buttons()

    def _update_buttons(self):
        busy = self.worker is not None
        self.apply_button.setEnabled(not busy and self.raw_mask is not None)
        self.preview_button.setEnabled(not busy and bool(self.method.currentData()))
        self.method.setEnabled(not busy)
        self.download_button.setEnabled(not busy)

    def _set_status(self, message: str):
        self.status.setText(message)

    # --- Model management ------------------------------------------------------------

    def open_models_folder(self):
        self.models_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.models_dir)))

    def download_default_model(self):
        spec = background.KNOWN_MODELS[background.DEFAULT_DOWNLOAD]
        url = background.MODEL_RELEASE_URL.format(name=spec.name)
        answer = QMessageBox.question(
            self, "Télécharger un modèle",
            f"Télécharger le modèle « {spec.label} » (environ {spec.download_size_mb:g} Mo) ?\n\n"
            f"Source : {url}\nDestination : {self.models_dir}\n\n"
            "Seul le modèle est téléchargé ; vos images restent sur cet ordinateur.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.worker = DownloadWorker(spec.name, self.models_dir, self)
        self.worker.progressed.connect(self._on_progress)
        self.worker.finished.connect(self._download_finished)
        self.progress.setValue(0)
        self.progress.show()
        self._update_buttons()
        self.worker.start()

    def _download_finished(self):
        worker, self.worker = self.worker, None
        if worker is None:  # the dialog closed meanwhile
            return
        self.progress.hide()
        if worker.error:
            self._set_status(worker.error)
            self._update_buttons()
            return
        self.populate_methods(select=self.models_dir / f"{worker.name}.onnx")
        self._set_status("Modèle installé. Cliquez sur « Calculer l'aperçu ».")

    def done(self, result):
        # Closing never waits for a running thread (a model run cannot be
        # interrupted, a download only stops between two blocks): its result is
        # discarded and dispose() deletes the dialog once the thread has ended.
        if self.worker is not None:
            if isinstance(self.worker, DownloadWorker):
                self.worker.cancel_requested = True
            self._orphan, self.worker = self.worker, None
        super().done(result)

    def dispose(self):
        """Delete the dialog (and its image) once no thread uses it any more."""
        if self._orphan is not None and self._orphan.isRunning():
            self._orphan.finished.connect(self.deleteLater)
        else:
            self.deleteLater()
