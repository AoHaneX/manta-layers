"""Dropping images asks whether to create a document from them or to add them as layers."""
import io

import pytest

pytest.importorskip("PySide6")

from conftest import png_bytes  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox  # noqa: E402

from app.dialogs import ImportChoiceDialog  # noqa: E402
from app.graphics import render_layer_with_mask, render_layers  # noqa: E402
from app.model import Document  # noqa: E402

RED = (220, 20, 20, 255)
HALF_BLUE = (20, 60, 220, 128)


def write_png(path, size, color):
    Image.new("RGBA", size, color).save(path, format="PNG")
    return str(path)


@pytest.fixture
def messages(monkeypatch):
    shown = {"warning": [], "critical": []}
    for kind in shown:
        monkeypatch.setattr(QMessageBox, kind,
                            lambda _parent, _title, text, *_args, kind=kind: shown[kind].append(text))
    return shown


@pytest.fixture
def choose(monkeypatch):
    """Answer the import choice with ``choose.answer`` ("new", "add" or None) and count the dialogs."""
    class Answer:
        answer: str | None = None
        shown: list = []

    def exec_(dialog):
        Answer.shown.append({key: button.isEnabled() for key, button in dialog.buttons.items()})
        dialog.choice = Answer.answer
        return 1 if Answer.answer else 0

    Answer.shown = []
    monkeypatch.setattr(ImportChoiceDialog, "exec", exec_)
    return Answer


@pytest.fixture
def current(window):
    """400 × 300 document holding one red 20 × 20 layer, with a clean history."""
    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(20, 20, RED), "Carré", center=False)
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    window.undo_stack.setClean()
    return window, layer.id


def drop(window, target, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    # The handlers are called directly: Qt needs a real drag behind a QDropEvent it delivers.
    target.dropEvent(event)
    QApplication.processEvents()  # the choice is shown once the drop is over
    return event


# --- The dialog --------------------------------------------------------------------

def test_dialog_matches_the_reference_layout(window):
    dialog = ImportChoiceDialog(window)
    dialog.show()
    assert dialog.windowTitle() == "Open image" and dialog.isModal()
    assert [label.text() for label in dialog.findChildren(QLabel)] == [
        "Do you want to add the image as a layer in the current document or create a new?"]
    new, add = dialog.buttons["new"], dialog.buttons["add"]
    assert (new.text(), add.text()) == ("Create new", "Add current")
    # Two large buttons side by side, same size, icon above the label.
    assert new.size() == add.size() and new.width() >= 140 and new.height() >= 100
    assert new.geometry().top() == add.geometry().top() and new.geometry().right() < add.geometry().left()
    for button in (new, add):
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        assert not button.icon().isNull() and button.iconSize().width() >= 40
        assert button.objectName() == "importChoice"
    dialog.close()


def test_closing_the_dialog_imports_nothing(qapp):
    dialog = ImportChoiceDialog()
    dialog.show()
    dialog.reject()
    assert dialog.choice is None
    dialog = ImportChoiceDialog()
    dialog.buttons["new"].click()
    assert dialog.choice == "new" and dialog.result() == 1


def test_add_current_is_disabled_without_a_document(qapp):
    dialog = ImportChoiceDialog(can_add=False)
    assert dialog.buttons["new"].isEnabled() and not dialog.buttons["add"].isEnabled()


# --- Dropping -----------------------------------------------------------------------

@pytest.mark.parametrize("on_canvas", [True, False])
def test_a_drop_on_the_canvas_or_the_window_shows_the_choice(current, choose, tmp_path, on_canvas):
    window, _layer = current
    path = write_png(tmp_path / "photo.png", (30, 20), RED)
    target = window.canvas if on_canvas else window
    event = drop(window, target, [path])
    assert event.isAccepted()
    assert choose.shown == [{"new": True, "add": True}]


def test_a_blank_document_offers_both_choices(window, choose, tmp_path):
    window.install_document(Document(200, 100), None)
    drop(window, window.canvas, [write_png(tmp_path / "a.png", (10, 10), RED)])
    assert choose.shown == [{"new": True, "add": True}]


def test_cancelling_the_choice_changes_nothing(current, choose, tmp_path):
    window, layer_id = current
    choose.answer = None
    before = window.document.clone()
    drop(window, window.canvas, [write_png(tmp_path / "photo.png", (30, 20), RED)])
    assert window.document == before and window.undo_stack.count() == 0


def test_create_new_makes_a_transparent_document_the_size_of_the_image(current, choose, tmp_path):
    window, _layer = current
    choose.answer = "new"
    path = write_png(tmp_path / "fond.png", (2560, 1440), HALF_BLUE)
    drop(window, window.canvas, [path])
    document = window.document
    assert (document.width, document.height) == (2560, 1440)
    assert document.background is None and len(document.layers) == 1
    layer = document.layers[0]
    assert layer.name == "Calque 0" and (layer.x, layer.y, layer.sx, layer.sy) == (0, 0, 1, 1)
    assert window.selected_id == layer.id
    source = render_layer_with_mask(layer, document)
    assert source.size == (2560, 1440) and source.getextrema()[3] == (128, 128)  # exact pixels and alpha
    assert source.getpixel((0, 0)) == HALF_BLUE
    shown = render_layers(document, with_background=True)  # nothing behind: the alpha stays 128
    assert shown.getpixel((0, 0))[3] == 128 and shown.getpixel((2559, 1439))[3] == 128
    # A fresh history, and the whole document in view.
    assert window.undo_stack.count() == 0 and window.project_path is None
    shown = window.canvas.mapFromScene(QRectF(0, 0, 2560, 1440)).boundingRect()
    assert window.canvas.viewport().rect().adjusted(-2, -2, 2, 2).contains(shown)


def test_create_new_uses_the_image_as_displayed_after_its_exif_rotation(window, tmp_path):
    image = Image.new("RGB", (40, 10), (10, 200, 30))
    exif = image.getexif()
    exif[0x0112] = 6  # rotated by 90 degrees
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    document = Document.from_image_bytes(output.getvalue(), "Calque 0")
    assert (document.width, document.height) == (10, 40)


def test_create_new_adds_the_other_dropped_images_as_layers(current, choose, tmp_path):
    window, _layer = current
    choose.answer = "new"
    first = write_png(tmp_path / "grand.png", (100, 60), RED)
    second = write_png(tmp_path / "petit.png", (20, 10), HALF_BLUE)
    drop(window, window.canvas, [first, second])
    document = window.document
    assert (document.width, document.height) == (100, 60)
    assert [layer.name for layer in document.layers] == ["Calque 0", "petit"]
    assert (document.layers[1].x, document.layers[1].y) == (40, 25)  # centred
    assert window.selected_id == document.layers[1].id


def test_create_new_protects_unsaved_changes(current, choose, tmp_path, monkeypatch):
    window, layer_id = current
    window.mutate("Déplacer", lambda doc: setattr(doc.layer(layer_id), "x", 50.0), layer_id)
    choose.answer = "new"
    answers = []

    def answer(box):
        answers.append(box.text())
        box.button(answers_button[0]).click()

    answers_button = [QMessageBox.StandardButton.Cancel]
    monkeypatch.setattr(QMessageBox, "exec", answer)
    path = write_png(tmp_path / "photo.png", (30, 20), RED)
    drop(window, window.canvas, [path])
    assert len(answers) == 1
    assert (window.document.width, window.document.height) == (400, 300)
    assert window.document.layer(layer_id).x == 50.0 and window.undo_stack.count() == 1
    answers_button[0] = QMessageBox.StandardButton.Discard
    drop(window, window.canvas, [path])
    assert (window.document.width, window.document.height) == (30, 20)


def test_create_new_with_an_invalid_file_reports_it_and_keeps_the_document(current, choose, messages, tmp_path,
                                                                             monkeypatch):
    window, _layer = current
    window.mutate("Déplacer", lambda doc: setattr(doc.layers[0], "x", 50.0), None)
    choose.answer = "new"
    asked = []
    monkeypatch.setattr(type(window), "maybe_save", lambda self: asked.append(True) or True)
    broken = tmp_path / "abime.png"
    broken.write_bytes(b"not an image")
    before = window.document.clone()
    drop(window, window.canvas, [str(broken)])
    assert len(messages["warning"]) == 1 and "abime.png" in messages["warning"][0]
    assert window.document == before and asked == []  # not even asked to save


def test_add_current_adds_a_selected_layer_and_keeps_the_document(current, choose, tmp_path):
    window, layer_id = current
    choose.answer = "add"
    big = write_png(tmp_path / "immense.png", (600, 500), HALF_BLUE)
    drop(window, window.canvas, [big])
    document = window.document
    assert (document.width, document.height) == (400, 300)  # the canvas is not resized
    assert [layer.id for layer in document.layers][0] == layer_id and len(document.layers) == 2
    added = document.layers[1]
    assert added.name == "immense" and window.selected_id == added.id
    assert (added.x, added.y) == (-100, -100)  # centred, beyond the frame, at its own size
    assert render_layer_with_mask(added, document).size == (600, 500)  # not cropped to the frame
    assert render_layers(document, [added.id]).getpixel((200, 150))[3] == 128
    window.undo_stack.undo()
    assert [layer.id for layer in window.document.layers] == [layer_id]


def test_the_import_button_still_adds_layers_without_asking(current, choose, tmp_path, monkeypatch):
    window, _layer = current
    path = write_png(tmp_path / "bouton.png", (10, 10), RED)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_args, **_kw: ([path], ""))
    window.add_images()
    assert choose.shown == [] and window.document.layers[-1].name == "bouton"


def test_other_files_are_not_accepted(current, choose, tmp_path):
    window, _layer = current
    text = tmp_path / "notes.txt"
    text.write_text("x")
    event = drop(window, window.canvas, [str(text)])
    assert not event.isAccepted() and choose.shown == []


def test_dialog_is_drawn_like_the_reference(window):
    dialog = ImportChoiceDialog(window)  # styled by the window, as when a drop opens it
    dialog.show()
    QApplication.processEvents()
    image = dialog.grab().toImage()
    new = dialog.buttons["new"].geometry()
    # Rounded corners: the button corner shows the dialog background, its middle the button colour.
    corner = image.pixelColor(new.topLeft() + QPoint(1, 1))
    inside = image.pixelColor(new.center() + QPoint(0, new.height() // 2 - 6))
    background = image.pixelColor(QPoint(3, image.height() - 3))
    assert corner.name() != inside.name() and inside.name() != background.name()
    dialog.close()
