"""Whatever is still being typed is kept when the window closes or the project is saved."""
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QMessageBox

from app.storage import open_project


def _select_first_layer(window):
    layer = window.document.layers[-1]
    window.select_layer(layer.id)
    return layer


def _cancel_save_prompt(monkeypatch):
    asked = []

    def exec_(box):
        asked.append(box.text())
        box.button(QMessageBox.StandardButton.Cancel).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return asked


def test_a_layer_name_being_typed_is_kept_on_close(window, monkeypatch):
    layer = _select_first_layer(window)
    window.name_input.setFocus()
    window.name_input.setText("Nom tapé")  # no editingFinished: the field still has the focus
    asked = _cancel_save_prompt(monkeypatch)
    assert not window.maybe_save()
    assert asked, "closing must ask to save the typed name"
    assert window.document.layer(layer.id).name == "Nom tapé"


def test_a_number_being_typed_is_kept_on_save(window, tmp_path):
    layer = _select_first_layer(window)
    spin = window.inputs["x"]
    spin.setFocus()
    spin.lineEdit().setText(spin.textFromValue(123.0))
    window.project_path = tmp_path / "projet.manta"
    assert window.save_document()
    assert open_project(tmp_path / "projet.manta").layer(layer.id).x == 123.0
    assert not window.is_modified()


def test_text_typed_on_the_canvas_is_kept_on_close(window, monkeypatch):
    count = len(window.document.layers)
    window.begin_inline_text_create(QPointF(40, 40))
    window._inline["editor"].setPlainText("Bonjour")
    asked = _cancel_save_prompt(monkeypatch)
    assert not window.maybe_save()
    assert asked
    assert len(window.document.layers) == count + 1
    assert window.document.layers[-1].text == "Bonjour"


def test_nothing_typed_asks_nothing(window, monkeypatch):
    _select_first_layer(window)
    window.name_input.setFocus()
    monkeypatch.setattr(QMessageBox, "exec", lambda *_: (_ for _ in ()).throw(AssertionError("no prompt")))
    assert window.maybe_save()
