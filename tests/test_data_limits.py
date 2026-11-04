"""Data robustness: layer and manifest limits, damaged layers, recovery copies."""
from unittest import mock

import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox

from app import recovery
from app.model import MAX_LAYERS, Document, Layer
from app.storage import open_project, save_project


def _text_document(count):
    document = Document(64, 64)
    document.layers = [Layer(id=f"t{index}", kind="text", text="a") for index in range(count)]
    return document


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


def test_a_copy_that_cannot_be_written_is_reported(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[2]))
    monkeypatch.setattr(recovery, "save_project", mock.Mock(side_effect=ValueError("disque plein")))
    assert window.mutate("Texte", lambda doc: doc.add_text("x"))
    assert not window.autosave_now()
    assert not window.autosave_now()
    assert len(warnings) == 1 and "disque plein" in warnings[0]  # one dialog, then the status bar
    assert "disque plein" in window.statusBar().currentMessage()
