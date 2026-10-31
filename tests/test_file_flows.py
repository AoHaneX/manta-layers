"""File flows of the main window: open, save as, export, import, paste, save prompt.

The native file dialogs and message boxes are replaced by stubs, so the
tests exercise the real code paths without any user interaction.
"""
import pytest

pytest.importorskip("PySide6")

from conftest import png_bytes  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from app.model import Document  # noqa: E402
from app.storage import open_project, save_project  # noqa: E402

RED = (220, 20, 20, 255)


@pytest.fixture
def messages(monkeypatch):
    """Messages shown to the user, by kind, instead of blocking dialogs."""
    shown = {"critical": [], "warning": [], "information": []}
    for kind in shown:
        monkeypatch.setattr(QMessageBox, kind,
                            lambda _parent, title, text, *_args, kind=kind: shown[kind].append(text))
    return shown


@pytest.fixture
def small_document(window):
    """40 x 30 transparent document with a 10 x 10 red square at (5, 5)."""
    document = Document(40, 30)
    layer = document.add_image_bytes(png_bytes(10, 10, RED), "Carré", center=False)
    layer.x, layer.y = 5, 5
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    return window, layer


def answer_save(monkeypatch, path, selected_filter="PNG (*.png)"):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kw: (str(path), selected_filter))


def answer_open(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kw: (str(path), ""))


# --- Export ---------------------------------------------------------------------------

def test_png_export_keeps_size_and_transparency(small_document, monkeypatch, tmp_path, messages):
    window, _layer = small_document
    answer_save(monkeypatch, tmp_path / "rendu.png")
    window.export_image()
    with Image.open(tmp_path / "rendu.png") as image:
        assert image.size == (40, 30) and image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((10, 10)) == RED
    assert not messages["critical"] and not messages["warning"]


def test_jpeg_export_puts_transparent_areas_on_white(small_document, monkeypatch, tmp_path):
    window, _layer = small_document
    answer_save(monkeypatch, tmp_path / "rendu.jpg", "JPEG (*.jpg)")
    window.export_image()
    with Image.open(tmp_path / "rendu.jpg") as image:
        assert image.format == "JPEG" and image.size == (40, 30)
        assert all(channel > 245 for channel in image.getpixel((1, 1)))
        red = image.getpixel((10, 10))
        assert red[0] > 180 and red[1] < 70 and red[2] < 70


def test_webp_export(small_document, monkeypatch, tmp_path):
    window, _layer = small_document
    answer_save(monkeypatch, tmp_path / "rendu.webp", "WebP (*.webp)")
    window.export_image()
    with Image.open(tmp_path / "rendu.webp") as image:
        assert image.format == "WEBP" and image.size == (40, 30)


def test_export_adds_the_extension_of_the_chosen_filter(small_document, monkeypatch, tmp_path):
    window, _layer = small_document
    answer_save(monkeypatch, tmp_path / "rendu", "JPEG (*.jpg)")
    window.export_image()
    assert (tmp_path / "rendu.jpg").is_file()


def test_selected_layer_export_has_the_layer_size(small_document, monkeypatch, tmp_path):
    window, _layer = small_document
    answer_save(monkeypatch, tmp_path / "calque.png")
    window.export_selected_layer()
    with Image.open(tmp_path / "calque.png") as image:
        assert image.size == (10, 10) and image.getpixel((0, 0)) == RED


def test_cancelled_export_writes_nothing(small_document, monkeypatch, tmp_path):
    window, _layer = small_document
    answer_save(monkeypatch, "")
    window.export_image()
    assert not list(tmp_path.glob("*.png"))


# --- Projects -------------------------------------------------------------------------

def test_save_as_adds_the_manta_extension_and_marks_the_document_saved(small_document, monkeypatch, tmp_path):
    window, layer = small_document
    window.nudge_layer(3, 0)
    assert window.is_modified()
    answer_save(monkeypatch, tmp_path / "projet", "Projet Manta Layers (*.manta)")
    assert window.save_as_document()
    assert window.project_path == tmp_path / "projet.manta"
    assert not window.is_modified() and "projet.manta" in window.windowTitle()
    reopened = open_project(tmp_path / "projet.manta")
    assert reopened.layer(layer.id).x == 8


def test_failed_save_reports_and_keeps_the_document_modified(small_document, monkeypatch, tmp_path, messages):
    window, _layer = small_document
    window.nudge_layer(1, 0)
    blocked = tmp_path / "dossier.manta"
    blocked.mkdir()  # a folder cannot be replaced by the saved file
    answer_save(monkeypatch, blocked, "Projet Manta Layers (*.manta)")
    assert not window.save_as_document()
    assert messages["critical"] and window.project_path is None and window.is_modified()


def test_open_installs_the_project_with_a_fresh_history(window, monkeypatch, tmp_path, messages):
    document = Document(64, 48)
    document.add_image_bytes(png_bytes(8, 8), "Image")
    document.add_text("Bonjour")
    save_project(document, tmp_path / "ouvert.manta")
    window.nudge_layer(1, 0)
    window.undo_stack.setClean()
    answer_open(monkeypatch, tmp_path / "ouvert.manta")
    window.open_document()
    assert (window.document.width, window.document.height) == (64, 48)
    assert [layer.id for layer in window.document.layers] == [layer.id for layer in document.layers]
    assert window.project_path == tmp_path / "ouvert.manta"
    assert window.undo_stack.count() == 0 and not window.is_modified()


def test_opening_a_damaged_project_changes_nothing(window, monkeypatch, tmp_path, messages):
    (tmp_path / "abime.manta").write_bytes(b"pas un projet")
    before = [layer.id for layer in window.document.layers]
    answer_open(monkeypatch, tmp_path / "abime.manta")
    window.open_document()
    assert messages["critical"]
    assert [layer.id for layer in window.document.layers] == before and window.project_path is None


# --- Import and clipboard -------------------------------------------------------------

def test_import_adds_valid_images_and_reports_the_others(small_document, tmp_path, messages):
    window, _layer = small_document
    (tmp_path / "bon.png").write_bytes(png_bytes(6, 4))
    (tmp_path / "faux.png").write_bytes(b"pas une image")
    count = len(window.document.layers)
    window._import_paths([str(tmp_path / "bon.png"), str(tmp_path / "faux.png"),
                          str(tmp_path / "absent.png")])
    assert len(window.document.layers) == count + 1
    assert window.document.layers[-1].name == "bon"
    assert window.selected_id == window.document.layers[-1].id
    assert len(messages["warning"]) == 2  # unreadable content, then missing file
    window.undo_stack.undo()
    assert len(window.document.layers) == count


def test_copied_layer_is_pasted_back_as_a_new_layer(small_document):
    window, layer = small_document
    assert window.copy_layer()
    assert window.paste_image()
    pasted = window.document.layers[-1]
    assert pasted.id != layer.id and pasted.name == "Image collée"
    assert window.selected_id == pasted.id


def test_paste_without_image_adds_nothing(small_document):
    window, _layer = small_document
    QApplication.clipboard().setText("du texte")
    count = len(window.document.layers)
    assert not window.paste_image()
    assert len(window.document.layers) == count


def test_external_image_is_pasted_in_the_centre(small_document):
    window, _layer = small_document
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FF00)
    QApplication.clipboard().setImage(image)
    assert window.paste_image()
    pasted = window.document.layers[-1]
    assert (pasted.x, pasted.y) == (18, 14)


def test_cut_layer_copies_then_deletes_it(small_document):
    window, layer = small_document
    assert window.cut_layer()
    assert window.document.layer(layer.id) is None
    assert not QApplication.clipboard().image().isNull()


# --- Save prompt ----------------------------------------------------------------------

@pytest.mark.parametrize("answer, expected, saved", [
    (QMessageBox.StandardButton.Cancel, False, False),
    (QMessageBox.StandardButton.Discard, True, False),
    (QMessageBox.StandardButton.Save, True, True),
])
def test_save_prompt_answers(small_document, monkeypatch, tmp_path, answer, expected, saved):
    window, _layer = small_document
    window.nudge_layer(2, 0)

    def click(box):
        box.button(answer).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", click)
    answer_save(monkeypatch, tmp_path / "invite.manta", "Projet Manta Layers (*.manta)")
    assert window.maybe_save() is expected
    assert (tmp_path / "invite.manta").exists() is saved
    assert window.is_modified() is not saved
