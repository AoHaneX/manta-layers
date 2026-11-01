"""Element templates and their library, tokens, spritesheets and remembered folders."""
import io

import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from app import templates
from app.builtin_templates import BUILTIN_TEMPLATES, builtin_template
from app.graphics import qimage_to_pil, render_document
from app.model import Document, Layer
from app.storage import open_project
from app.template_library import TemplateLibraryDialog
from app.templates import extract_elements, insert_elements, list_templates, save_template


@pytest.fixture
def library(monkeypatch, tmp_path):
    directory = tmp_path / "modeles"
    monkeypatch.setattr(templates, "template_directory", lambda: directory)
    return directory


def png(size=(20, 20), color=(200, 30, 30, 255), box=None):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box or (0, 0, size[0] - 1, size[1] - 1), fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# --- Element templates --------------------------------------------------------------------


@pytest.mark.parametrize("key", list(BUILTIN_TEMPLATES))
def test_bundled_templates_are_editable_vector_groups(qapp, key):
    document = builtin_template(key)
    assert len(document.folders) == 1 and document.layers
    assert {layer.kind for layer in document.layers} <= {"shape", "text"}  # no picture inside
    assert qimage_to_pil(render_document(document)).getbbox() is not None


def test_inserting_twice_creates_independent_layers_and_folders():
    source = Document(200, 100)
    image = source.add_image_bytes(png(), "Image", center=False)
    text = source.add_text("Texte")
    source.create_folder([image.id, text.id], "Paire")
    elements = extract_elements(source, [image.id, text.id], (0, 0, 200, 100))
    target = Document(400, 300)
    first = insert_elements(target, elements, (100, 100))
    second = insert_elements(target, elements, (0, 0))
    assert len(set(first) | set(second)) == 4 and len(target.folders) == 2
    assert target.layer(first[0]).x == 100 and target.layer(second[0]).x == 0
    assert target.layer(first[0]).asset == target.layer(second[0]).asset in target.assets


def test_window_inserts_a_template_centred_checked_and_undoable(window):
    window.install_document(Document(800, 600), None)
    window.undo_stack.clear()
    elements = builtin_template("builtin-banner")
    assert window.insert_template_elements(elements, "Bandeau")
    inserted = window.document.layers
    assert len(window.checked_layer_ids()) == len(inserted) == 2
    banner = next(layer for layer in inserted if layer.kind == "shape")
    assert (banner.x, banner.y) == ((800 - 440) / 2, (600 - 96) / 2)
    window.undo_stack.undo()
    assert window.document.layers == [] and window.document.folders == []


def test_library_lists_bundled_and_user_templates_and_manages_them(window, library, monkeypatch):
    save_template(builtin_template("builtin-label"), "Mon étiquette", None, kind="elements")
    save_template(Document(10, 10), "Projet complet", None)  # a preset: not offered here
    (library / "abime.manta").write_bytes(b"pas un zip")
    dialog = TemplateLibraryDialog(window)
    entries = [dialog.gallery.item(i).data(templates_role()) for i in range(dialog.gallery.count())]
    assert len(entries) == len(BUILTIN_TEMPLATES) + 1 and entries[-1][0] == "user"
    dialog.gallery.setCurrentRow(0)  # a bundled template: insert or duplicate only
    assert not dialog.delete_btn.isEnabled() and dialog.duplicate_btn.isEnabled()
    dialog.duplicate_selected()
    assert len(list_templates(kind="elements")) == 2
    user_row = next(i for i in range(dialog.gallery.count()) if dialog.gallery.item(i).text().startswith("Mon"))
    dialog.gallery.setCurrentRow(user_row)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renommée", True))
    dialog.rename_selected()
    assert "Renommée" in [info.name for info in list_templates(kind="elements")]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.delete_selected()
    assert "Renommée" not in [info.name for info in list_templates(kind="elements")]


def templates_role():
    from app.template_library import ENTRY_ROLE
    return ENTRY_ROLE


def test_library_dialog_choice_inserts_through_the_window(window, library, monkeypatch):
    window.install_document(Document(500, 400), None)

    def choose_first(dialog):
        dialog.gallery.setCurrentRow(0)
        dialog.action = "insert"
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TemplateLibraryDialog, "exec", choose_first)
    assert window.open_template_library()
    assert window.document.layers and window.document.folders


def test_editing_a_template_saves_it_back_with_its_name(window, library):
    path = save_template(builtin_template("builtin-speech"), "Ma bulle", None, kind="elements")
    assert window.edit_element_template(path, "Ma bulle", open_project(path))
    assert window.windowTitle().startswith("Modèle : Ma bulle")
    window.mutate("Ajout", lambda doc: doc.add_text("Nouveau"))
    assert window.save_document()
    info = templates.read_template_info(path)
    assert (info.name, info.kind) == ("Ma bulle", "elements")
    assert len(open_project(path).layers) == 3


def test_template_layer_fields_survive_extraction(qapp):
    source = Document(100, 100)
    shape = Layer(kind="shape", shape_type="speech", x=30, y=40, fill_color="#FFFFFF")
    source.layers.append(shape)
    elements = extract_elements(source, [shape.id], (30, 40, 230, 160))
    copy = elements.layers[0]
    assert (copy.x, copy.y, copy.shape_type, copy.fill_color) == (0, 0, "speech", "#FFFFFF")
