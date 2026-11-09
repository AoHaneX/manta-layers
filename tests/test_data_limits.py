"""Data robustness: layer and manifest limits, damaged layers, recovery copies."""
import json
import threading
from unittest import mock
from zipfile import ZipFile

import pytest
from conftest import png_bytes
from PIL import Image
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app import diagnostics, recovery, storage
from app.model import MAX_LAYERS, Document, Layer
from app.storage import open_project, save_project


def _text_document(count):
    document = Document(64, 64)
    document.layers = [Layer(id=f"t{index}", kind="text", text="a") for index in range(count)]
    return document


# --- Layer limit: whatever can be edited can be saved and reopened ---------------------------

def test_more_than_a_thousand_layers_save_and_reopen(tmp_path):
    path = tmp_path / "planche.manta"
    save_project(_text_document(1024), path)  # a 512 × 512 sheet cut in 16 px cells
    assert len(open_project(path).layers) == 1024


def test_too_many_layers_are_refused_before_writing(tmp_path):
    path = tmp_path / "projet.manta"
    path.write_bytes(b"ancien")
    with pytest.raises(ValueError, match="calques"):
        save_project(_text_document(MAX_LAYERS + 1), path)
    assert path.read_bytes() == b"ancien"
    assert not (tmp_path / "projet.manta.tmp").exists()


def test_an_edit_beyond_the_limit_is_refused(window, monkeypatch):
    window.install_document(_text_document(3), None)
    window.undo_stack.clear()
    reported = []
    monkeypatch.setattr(window, "_report_failure", lambda description, exc: reported.append(str(exc)))
    with mock.patch("app.window.MAX_LAYERS", 4):
        assert window.mutate("Ajouter", lambda doc: doc.add_text("b"))
        assert not window.mutate("Ajouter", lambda doc: doc.add_text("c"))
    assert reported and "calques" in reported[0]
    assert len(window.document.layers) == 4 and window.undo_stack.count() == 1


def test_sprites_that_do_not_fit_are_refused_with_a_message(window, monkeypatch):
    window.install_document(_text_document(3), None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[2]))
    sprites = [(0, column, Image.new("RGBA", (4, 4), (255, 0, 0, 255))) for column in range(3)]
    with mock.patch("app.window.MAX_LAYERS", 5):
        assert not window.add_sprite_layers(sprites, "Planche")
    assert warnings and "3 sprites" in warnings[0]
    assert len(window.document.layers) == 3


# --- Manifest size: checked when writing -------------------------------------------------------

def test_an_oversized_manifest_is_refused_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_MANIFEST_BYTES", 2000)
    path = tmp_path / "projet.manta"
    with pytest.raises(ValueError, match="Mo"):
        save_project(_text_document(40), path)
    assert not path.exists() and not (tmp_path / "projet.manta.tmp").exists()


# --- Damaged layers are never copied or exported as their hatched stand-in -------------------

def _damaged_project(window, tmp_path, monkeypatch):
    document = Document(40, 30)
    layer = document.add_image_bytes(png_bytes(6, 6), "Cassée", center=False)
    path = tmp_path / "abime.manta"
    save_project(document, path)
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[f"assets/{layer.asset}.png"] = entries[f"assets/{layer.asset}.png"][:40]
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(path), ""))
    window.open_document()
    window.select_layer(layer.id)
    return layer


def test_a_damaged_layer_is_not_copied(window, tmp_path, monkeypatch):
    QApplication.clipboard().clear()
    layer = _damaged_project(window, tmp_path, monkeypatch)
    assert not window.copy_layer()
    assert QApplication.clipboard().image().isNull()
    assert not window.cut_layer()
    assert window.document.layer(layer.id) is not None  # cutting failed: the layer stays


def test_a_damaged_layer_is_not_exported(window, tmp_path, monkeypatch):
    _damaged_project(window, tmp_path, monkeypatch)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **_k: errors.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(tmp_path / "c.png"), ""))
    window.export_selected_layer()
    assert errors and "illisible" in errors[0]
    assert not (tmp_path / "c.png").exists()


def test_a_copied_layer_keeps_its_exact_pixels(window):
    document = Document(20, 20)
    layer = document.add_image_bytes(png_bytes(3, 2, (200, 100, 50, 10)), "Voile", center=False)
    layer.flip_horizontal = True
    window.install_document(document, layer.id)
    assert window.copy_layer()
    image = QApplication.clipboard().image()
    color = image.pixelColor(0, 0)
    assert (image.width(), image.height()) == (3, 2)
    assert (color.red(), color.green(), color.blue(), color.alpha()) == (200, 100, 50, 10)


# --- Recovery copies ---------------------------------------------------------------------------

def test_a_restored_copy_is_rewritten_at_once(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from app.window import MainWindow

    directory = tmp_path / "recovery"
    directory.mkdir()
    crashed = "c" * 32
    save_project(_text_document(2), directory / f"{crashed}.manta")
    (directory / f"{crashed}.json").write_text(json.dumps({"saved_at": 1.0}), encoding="utf-8")
    monkeypatch.setattr(MainWindow, "_ask_recovery", lambda *_args: "restore")
    window = MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                        recovery_dir=directory)
    try:
        assert window.offer_session_recovery()
        own_copy, _meta = window.recovery.files(window.recovery.session_id)
        # Without waiting for the timer: a second crash now still finds the work.
        assert own_copy.exists() and len(open_project(own_copy).layers) == 2
        assert not (directory / f"{crashed}.manta").exists()
    finally:
        window._commit_pending_edits()
        window.undo_stack.setClean()
        window.close()


def test_a_copy_that_cannot_be_written_is_reported(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[2]))
    monkeypatch.setattr(recovery, "save_project", mock.Mock(side_effect=ValueError("disque plein")))
    assert window.mutate("Texte", lambda doc: doc.add_text("x"))
    assert not window.autosave_now()
    assert not window.autosave_now()
    assert len(warnings) == 1 and "disque plein" in warnings[0]  # one dialog, then the status bar
    assert "disque plein" in window.statusBar().currentMessage()


def test_an_unexpected_error_stays_inside_the_recovery_thread(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(recovery, "save_project", mock.Mock(side_effect=RuntimeError("panne")))
    writer = recovery.RecoveryWriter(Document(4, 4), 1, tmp_path / "c.manta", tmp_path / "c.json", None)
    writer.start()
    assert writer.wait(5000)
    assert not writer.succeeded and "panne" in writer.error


def test_the_error_report_opens_no_dialog_outside_the_interface_thread(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: shown.append(args))
    monkeypatch.setattr("sys.stderr", None)

    def fail():
        try:
            raise RuntimeError("dans un thread")
        except RuntimeError as exc:
            diagnostics.report_exception(type(exc), exc, exc.__traceback__)

    thread = threading.Thread(target=fail)
    thread.start()
    thread.join()
    assert shown == []


def test_an_unusable_recovery_folder_is_reported(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from app.window import MainWindow

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[2]))
    blocker = tmp_path / "fichier"
    blocker.write_text("not a folder")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings, recovery_dir=blocker / "recovery")
    try:
        assert window.recovery.lock is None and window.recovery.unavailable_reason
        assert window.mutate("Texte", lambda doc: doc.add_text("x"))
        assert not window.autosave_now()
        assert not window.autosave_now()
        assert len(warnings) == 1  # one dialog, then the status bar
        assert "récupération" in window.statusBar().currentMessage()
    finally:
        window._commit_pending_edits()
        window.undo_stack.setClean()
        window.close()

