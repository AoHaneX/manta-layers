"""Background removal dialog and its application to layers (no real model)."""
import io
import time

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from app import background as B  # noqa: E402
from app import background_dialog  # noqa: E402
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


def test_the_packaged_application_does_not_suggest_pip(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: False)
    monkeypatch.setattr(B.sys, "frozen", True, raising=False)
    dialog = make_dialog(tmp_path, qapp)
    assert dialog.method.itemText(1) == "IA locale — non incluse"
    dialog.method.setCurrentIndex(0)
    dialog._method_changed()
    assert "pip" not in dialog.status.text() and "pas incluse" in dialog.status.text()
    assert "pip" not in B.runtime_missing_message()


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


class SlowWorker(QThread):
    def run(self):
        time.sleep(0.4)


def test_closing_waits_for_a_background_removal_left_running(window, tmp_path):
    dialog = BackgroundRemovalDialog(Image.new("RGBA", (8, 8)), "image", False, tmp_path / "models", window)
    dialog.worker = SlowWorker(dialog)
    dialog.worker.start()
    dialog.reject()  # closing never waits for the thread...
    assert background_dialog.orphan_workers_running()
    dialog.dispose()
    window._wait_for_background_work()  # ...but quitting does, or Qt aborts the process
    assert not background_dialog.orphan_workers_running()


def test_only_the_tolerance_invalidates_the_full_size_colour_mask(tmp_path, qapp):
    dialog = make_dialog(tmp_path, qapp)
    dialog.compute()
    full_size = dialog.result_mask()
    raw = dialog.raw_mask
    assert full_size is not None and raw is not None
    dialog.feather.setValue(3)
    dialog.hard_edges.setChecked(True)
    assert dialog.raw_mask is raw  # edges and feathering only change refine()
    dialog.compute()
    assert dialog.raw_mask is raw
    dialog.tolerance.setValue(dialog.tolerance.value() + 1)
    assert dialog.raw_mask is None
    dialog.dispose()


def test_apply_computes_the_full_size_colour_mask_in_a_thread(tmp_path, qapp, monkeypatch):
    import threading
    image = Image.new("RGBA", (300, 200), (250, 250, 250, 255))
    ImageDraw.Draw(image).rectangle((100, 50, 199, 149), fill=(20, 90, 200, 255))
    dialog = BackgroundRemovalDialog(image, "Sujet", has_mask=False, models_dir=tmp_path)
    dialog.compute()
    threads = []
    original = B.border_colour_mask

    def recording(source, tolerance=32, feather=0):
        threads.append(threading.current_thread())
        return original(source, tolerance, feather)

    monkeypatch.setattr(B, "border_colour_mask", recording)
    dialog.accept()
    assert dialog.worker is not None and not dialog.apply_button.isEnabled()
    assert not dialog.tolerance.isEnabled()  # the running computation keeps its tolerance
    assert dialog.result() != QDialog.DialogCode.Accepted
    wait_for_worker(dialog, qapp)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert threads and threads[0] is not threading.main_thread()
    assert dialog.raw_mask.size == image.size
    mask = dialog.result_mask()
    assert mask.getbbox() == (100, 50, 200, 150) and len(threads) == 1  # not computed twice
    dialog.dispose()


def test_failed_full_size_colour_mask_keeps_the_dialog_open(tmp_path, qapp, monkeypatch):
    dialog = make_dialog(tmp_path, qapp)
    dialog.compute()

    def broken(*_args, **_kwargs):
        raise MemoryError("trop grand")

    monkeypatch.setattr(B, "border_colour_mask", broken)
    dialog.accept()
    wait_for_worker(dialog, qapp)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "trop grand" in dialog.status.text() and dialog.apply_button.isEnabled()
    assert dialog.progress.maximum() == 100 and dialog.progress.isHidden()
    dialog.dispose()


def test_ai_preview_is_applied_without_recomputation(tmp_path, qapp, monkeypatch):
    (tmp_path / "u2netp.onnx").write_bytes(b"fake")
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: True)
    monkeypatch.setattr(B, "onnx_mask", lambda image, path, progress: S.full(image.size))
    dialog = make_dialog(tmp_path, qapp)
    dialog.method.setCurrentIndex(1)
    dialog.compute()
    wait_for_worker(dialog, qapp)
    dialog.accept()
    assert dialog.worker is None and dialog.result() == QDialog.DialogCode.Accepted
    dialog.dispose()


@pytest.mark.parametrize("ratio", [1.0, 1.5, 2.0])
def test_preview_is_drawn_at_the_screen_density(tmp_path, qapp, monkeypatch, ratio):
    from PySide6.QtWidgets import QLabel
    shown = []
    original = QLabel.setPixmap
    monkeypatch.setattr(QLabel, "devicePixelRatioF", lambda _label: ratio)  # emulates 100/150/200 %
    # QLabel.pixmap() is converted to the label's real density: record what is given.
    monkeypatch.setattr(QLabel, "setPixmap", lambda label, pixmap: (shown.append(pixmap), original(label, pixmap)))
    dialog = make_dialog(tmp_path, qapp)
    dialog.compute()
    pixmap = shown[-1]
    width, height = background_dialog.PREVIEW_SIZE
    assert pixmap.devicePixelRatio() == ratio
    assert (pixmap.width(), pixmap.height()) == (round(width * ratio), round(height * ratio))
    assert pixmap.deviceIndependentSize().toSize().width() == width
    # The image is drawn at full resolution: its centre is the subject, not the checkerboard.
    centre = pixmap.toImage().pixelColor(pixmap.width() // 2, pixmap.height() // 2)
    assert (centre.red(), centre.green(), centre.blue()) == (20, 90, 200)
    dialog.dispose()
