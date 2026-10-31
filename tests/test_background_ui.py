"""Background removal dialog and its application to layers (no real model)."""
import io
import time

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from app import background as B  # noqa: E402
from app import selection as S  # noqa: E402
from app.background_dialog import BackgroundRemovalDialog  # noqa: E402
from app.graphics import render_layers  # noqa: E402
from app.model import Document  # noqa: E402


def subject_png():
    image = Image.new("RGBA", (40, 30), (250, 250, 250, 255))
    ImageDraw.Draw(image).rectangle((10, 8, 29, 21), fill=(20, 90, 200, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def layer_window(window, tmp_path):
    document = Document(100, 80)
    layer = document.add_image_bytes(subject_png(), "Sujet", center=False)
    layer.x, layer.y = 30.0, 20.0
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    window.models_dir = tmp_path / "models"
    return window, layer.id


def accept_with(monkeypatch, configure=lambda dialog: None):
    def fake_exec(dialog):
        configure(dialog)
        dialog.compute()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BackgroundRemovalDialog, "exec", fake_exec)


def test_applied_as_a_non_destructive_mask(layer_window, monkeypatch):
    window, layer_id = layer_window
    source = window.document.assets[window.document.layer(layer_id).asset]
    accept_with(monkeypatch)
    window.remove_background()
    layer = window.document.layer(layer_id)
    assert layer.mask is not None and window.document.assets[layer.asset] == source
    rendered = render_layers(window.document, [layer_id])
    assert rendered.getpixel((31, 21))[3] == 0          # former background
    assert rendered.getpixel((45, 35)) == (20, 90, 200, 255)  # subject
    window.undo_stack.undo()
    assert window.document.layer(layer_id).mask is None


def test_applied_as_a_new_layer_hiding_the_original(layer_window, monkeypatch):
    window, layer_id = layer_window
    accept_with(monkeypatch, lambda dialog: dialog.as_layer.setChecked(True))
    window.remove_background()
    assert len(window.document.layers) == 2
    original, cut = window.document.layers
    assert original.id == layer_id and not original.visible
    assert (cut.x, cut.y) == (30.0, 20.0) and cut.mask is None
    assert render_layers(window.document, [cut.id]).getpixel((31, 21))[3] == 0


def test_existing_mask_is_kept_by_intersection(layer_window, monkeypatch):
    window, layer_id = layer_window
    window.set_selection(S.rectangle((100, 80), (40, 28, 50, 42)), "test")
    window.clear_selection_content()  # manual correction hides part of the subject
    accept_with(monkeypatch)
    window.remove_background()
    rendered = render_layers(window.document, [layer_id])
    assert rendered.getpixel((45, 35))[3] == 0 and rendered.getpixel((58, 35))[3] == 255


def test_cancelled_dialog_changes_nothing(layer_window, monkeypatch):
    window, layer_id = layer_window
    monkeypatch.setattr(BackgroundRemovalDialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
    window.remove_background()
    assert window.document.layer(layer_id).mask is None and window.undo_stack.count() == 0


def test_text_and_locked_layers_are_refused(window):
    document = Document(50, 50)
    text = document.add_text("Pas une image")
    window.install_document(document, text.id)
    window.remove_background()
    assert window.undo_stack.count() == 0


def make_dialog(tmp_path, qapp):
    image = Image.open(io.BytesIO(subject_png())).convert("RGBA")
    return BackgroundRemovalDialog(image, "Sujet", has_mask=False, models_dir=tmp_path)


def wait_for_worker(dialog, qapp, timeout=5):
    deadline = time.monotonic() + timeout
    while dialog.worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert dialog.worker is None


def test_dialog_without_runtime_explains_how_to_enable_ai(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: False)
    dialog = make_dialog(tmp_path, qapp)
    labels = [dialog.method.itemText(i) for i in range(dialog.method.count())]
    assert labels[0].startswith("Couleur de fond")
    assert "onnxruntime non installé" in labels[1]
    assert not dialog.method.model().item(1).isEnabled()
    assert dialog.download_button.isHidden()


def test_dialog_runs_a_model_in_a_thread_with_preview(tmp_path, qapp, monkeypatch):
    (tmp_path / "u2netp.onnx").write_bytes(b"fake")
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: True)

    def fake_onnx(image, path, progress):
        progress("Analyse de l'image (processeur)…", 50)
        return S.rectangle(image.size, (10, 8, 30, 22))

    monkeypatch.setattr(B, "onnx_mask", fake_onnx)
    dialog = make_dialog(tmp_path, qapp)
    dialog.method.setCurrentIndex(1)
    assert not dialog.apply_button.isEnabled()  # nothing to apply before the preview
    dialog.compute()
    wait_for_worker(dialog, qapp)
    assert dialog.result_mask().getbbox() == (10, 8, 30, 22)
    assert dialog.apply_button.isEnabled()
    assert dialog.preview_label.pixmap() is not None


def test_dialog_reports_model_errors(tmp_path, qapp, monkeypatch):
    (tmp_path / "u2netp.onnx").write_bytes(b"fake")
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: True)

    def broken(*_args):
        raise B.BackgroundRemovalError("Modèle illisible (u2netp.onnx) : test")

    monkeypatch.setattr(B, "onnx_mask", broken)
    dialog = make_dialog(tmp_path, qapp)
    dialog.method.setCurrentIndex(1)
    dialog.compute()
    wait_for_worker(dialog, qapp)
    assert "illisible" in dialog.status.text() and not dialog.apply_button.isEnabled()


def test_download_requires_confirmation(tmp_path, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    monkeypatch.setattr(B, "download_model", lambda *a, **k: pytest.fail("downloaded without consent"))
    dialog = make_dialog(tmp_path, qapp)
    dialog.download_default_model()
    assert dialog.worker is None
    QApplication.processEvents()


def test_closing_during_a_model_run_does_not_wait_for_it(tmp_path, qapp, monkeypatch):
    import threading
    (tmp_path / "u2netp.onnx").write_bytes(b"fake")
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: True)
    release = threading.Event()

    def slow_onnx(image, path, progress):
        release.wait(5)
        return S.full(image.size)

    monkeypatch.setattr(B, "onnx_mask", slow_onnx)
    dialog = make_dialog(tmp_path, qapp)
    dialog.method.setCurrentIndex(1)
    dialog.compute()
    worker = dialog.worker
    started = time.monotonic()
    dialog.reject()
    assert time.monotonic() - started < 1  # the model run is not awaited
    assert dialog.result() == QDialog.DialogCode.Rejected and dialog.worker is None
    dialog.dispose()
    release.set()
    assert worker.wait(5000)
    qapp.processEvents()
    assert dialog.raw_mask is None  # the late result is discarded


def test_colour_preview_uses_a_reduced_copy_but_applies_full_size(tmp_path, qapp):
    image = Image.new("RGBA", (3000, 1500), (250, 250, 250, 255))
    ImageDraw.Draw(image).rectangle((1000, 500, 1999, 999), fill=(20, 90, 200, 255))
    dialog = BackgroundRemovalDialog(image, "Grand", has_mask=False, models_dir=tmp_path)
    dialog.compute()
    assert max(dialog.preview_mask.size) <= 1024 and dialog.raw_mask is None
    assert dialog.apply_button.isEnabled()
    mask = dialog.result_mask()
    assert mask.size == image.size and mask.getbbox() == (1000, 500, 2000, 1000)
    dialog.dispose()


def test_unexpected_download_failure_is_not_reported_as_installed(tmp_path, monkeypatch):
    from app.background_dialog import DownloadWorker

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(B, "download_model", broken)
    worker = DownloadWorker("u2netp", tmp_path)
    worker.run()  # synchronously: only the error handling is tested
    assert worker.error and "boom" in worker.error
