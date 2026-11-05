"""Layer panel: multiple selection, context menu, folders, merge and deletion."""
import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QInputDialog, QLineEdit, QMessageBox

from app import templates
from app.graphics import qimage_to_pil, render_document, render_layers
from app.layer_panel import FOLDER_ROLE
from app.model import Document
from app.templates import list_templates, open_project


def png(width, height, color, box=None):
    import io
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box or (0, 0, width - 1, height - 1), fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def three_layers(window):
    """Bottom red square, middle text, top half-transparent blue square overlapping the red one."""
    document = Document(100, 80)
    red = document.add_image_bytes(png(40, 40, (220, 20, 20, 255)), "Rouge", center=False)
    red.x, red.y = 10, 10
    document.add_text("Milieu").x = 60
    blue = document.add_image_bytes(png(40, 40, (20, 20, 220, 128)), "Bleu", center=False)
    blue.x, blue.y = 30, 20
    window.install_document(document, None)
    window.undo_stack.clear()
    return window, [layer.id for layer in document.layers]


def rows(window):
    return [(window.layer_list.item(i).data(Qt.ItemDataRole.UserRole), bool(window.layer_list.item(i).data(FOLDER_ROLE)))
            for i in range(window.layer_list.count())]


def answer_text(monkeypatch, text, accepted=True):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (text, accepted))


def menu_texts(window, row):
    menu = window.layer_context_menu(row)
    return [(action.text(), action.isEnabled()) for action in menu.actions() if action.text()]


def test_check_boxes_build_a_multiple_selection_with_highlighted_rows(three_layers, monkeypatch):
    window, (red, text, blue) = three_layers
    window.set_layer_checked(red, True)
    window.set_layer_checked(blue, True)
    assert window.checked_layer_ids() == [red, blue]
    assert window._layer_rows[red].property("checked") is True
    assert window._layer_rows[text].property("checked") is False
    monkeypatch.setattr(QApplication, "keyboardModifiers", lambda: Qt.KeyboardModifier.ControlModifier)
    window.layer_name_clicked(text)  # Ctrl+click adds without changing the current layer
    assert window.checked_layer_ids() == [red, text, blue]
    window.layer_name_clicked(text)
    assert text not in window.checked_ids
    assert window.undo_stack.count() == 0  # checking is not a document change


def test_context_menu_offers_the_four_actions_and_follows_the_selection_rule(three_layers):
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red, blue])
    row_of = {window.layer_list.item(i).data(Qt.ItemDataRole.UserRole): window.layer_list.item(i)
              for i in range(window.layer_list.count())}
    entries = dict(menu_texts(window, row_of[blue]))
    for label in ("Créer un dossier de calques…", "Fusionner les calques", "Supprimer", "Créer un modèle…"):
        assert entries[label] is True
    assert window.checked_layer_ids() == [red, blue]  # right-click inside the selection keeps it
    entries = dict(menu_texts(window, row_of[text]))
    assert window.checked_layer_ids() == [text]  # outside: only the clicked layer
    assert entries["Fusionner les calques"] is False  # a single layer cannot be merged
    assert window.selected_id == text


def test_folder_creation_collapse_visibility_and_undo(three_layers, monkeypatch):
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red, blue])
    answer_text(monkeypatch, "Carrés")
    assert window.create_folder_from_checked()
    folder = window.document.folders[0]
    assert folder.name == "Carrés"
    assert rows(window) == [(folder.id, True), (blue, False), (red, False), (text, False)]
    window.toggle_folder_collapsed(folder.id)
    assert rows(window) == [(folder.id, True), (text, False)]
    assert window.undo_stack.count() == 1  # folding is not an undoable change
    window.set_folder_visibility(folder.id, False)
    assert not window.canvas.graphic_for(red).isVisible()
    exported = qimage_to_pil(render_document(window.document))
    assert exported.getpixel((15, 15))[3] == 0  # hidden folder: absent from the export
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.document.folders == []


def test_renaming_and_dissolving_a_folder(three_layers, monkeypatch):
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red, text])
    answer_text(monkeypatch, "Groupe")
    window.create_folder_from_checked()
    folder_id = window.document.folders[0].id
    answer_text(monkeypatch, "  Nouveau   nom ")
    assert window.rename_folder(folder_id)
    assert window.document.folder(folder_id).name == "Nouveau nom"
    assert window.dissolve_folder(folder_id)
    assert window.document.folders == [] and len(window.document.layers) == 3


def test_drag_and_drop_moves_layers_into_and_out_of_folders(three_layers, monkeypatch):
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red])
    answer_text(monkeypatch, "Dossier")
    window.create_folder_from_checked()
    folder_id = window.document.folders[0].id
    folder_row = next(window.layer_list.item(i) for i in range(window.layer_list.count())
                      if window.layer_list.item(i).data(FOLDER_ROLE))
    assert window.drop_in_layer_list("layer", blue, folder_row, upper=False)
    assert window.document.layer(blue).folder == folder_id
    text_row = next(window.layer_list.item(i) for i in range(window.layer_list.count())
                    if window.layer_list.item(i).data(Qt.ItemDataRole.UserRole) == text)
    assert window.drop_in_layer_list("layer", blue, text_row, upper=False)  # below the text, outside
    assert window.document.layer(blue).folder is None
    assert [layer.id for layer in window.document.layers] == [red, blue, text]
    assert not window.drop_in_layer_list("folder", folder_id, None, upper=False)  # already at the bottom
    text_row = next(window.layer_list.item(i) for i in range(window.layer_list.count())
                    if window.layer_list.item(i).data(Qt.ItemDataRole.UserRole) == text)
    assert window.drop_in_layer_list("folder", folder_id, text_row, upper=True)  # folder above the text
    assert [layer.id for layer in window.document.layers] == [blue, text, red]


def test_merge_keeps_appearance_alpha_and_position_and_can_be_undone(three_layers, monkeypatch):
    window, (red, text, blue) = three_layers
    before = render_layers(window.document, [red, blue])
    window.set_checked_layers([red, blue])
    # The text lies between them but does not overlap them: no warning is needed.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("no warning expected"))
    assert window.merge_checked_layers()
    merged = window.document.layers[-1]
    assert [layer.kind for layer in window.document.layers] == ["text", "image"]
    assert (merged.x, merged.y) == (10, 10)
    after = render_layers(window.document, [merged.id])
    assert after.tobytes() == before.tobytes()
    assert after.getpixel((35, 25))[3] == 255 and after.getpixel((65, 55))[3] == 128
    assert window.checked_layer_ids() == [merged.id]
    window.undo_stack.undo()
    assert [layer.id for layer in window.document.layers] == [red, text, blue]


def test_merge_warns_when_an_unselected_layer_in_between_overlaps(window, monkeypatch):
    document = Document(60, 60)
    bottom = document.add_image_bytes(png(40, 40, (255, 0, 0, 255)), "Bas", center=False)
    middle = document.add_image_bytes(png(40, 40, (0, 255, 0, 255)), "Milieu", center=False)
    top = document.add_image_bytes(png(10, 10, (0, 0, 255, 255)), "Haut", center=False)
    window.install_document(document, None)
    window.set_checked_layers([bottom.id, top.id])
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No)
    assert not window.merge_checked_layers()
    assert asked and len(window.document.layers) == 3 and window.document.layer(middle.id)


def test_merge_ignores_hidden_layers_and_needs_two_visible_ones(three_layers):
    window, (red, text, blue) = three_layers
    window.set_layer_visibility(blue, False)
    window.set_checked_layers([red, blue])
    assert not window.merge_checked_layers()
    assert len(window.document.layers) == 3


def test_deleting_checked_layers_spares_locked_ones_and_is_undoable(three_layers):
    window, (red, text, blue) = three_layers
    window.toggle_lock(text)
    window.set_checked_layers([red, text, blue])
    assert window.delete_checked_layers()
    assert [layer.id for layer in window.document.layers] == [text]
    window.undo_stack.undo()
    assert len(window.document.layers) == 3


def test_delete_key_targets_checked_layers_but_not_a_field_being_edited(three_layers, qapp):
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red, blue])
    window.name_input.setFocus()
    qapp.processEvents()
    if isinstance(QApplication.focusWidget(), QLineEdit):
        assert not window.delete_selection_or_layer()
        assert len(window.document.layers) == 3
    window.canvas.setFocus()
    qapp.processEvents()
    assert window.delete_selection_or_layer()
    assert [layer.id for layer in window.document.layers] == [text]


def test_template_created_from_checked_layers_keeps_folders_and_images(three_layers, monkeypatch, tmp_path):
    window, (red, text, blue) = three_layers
    monkeypatch.setattr(templates, "template_directory", lambda: tmp_path / "modeles")
    window.set_checked_layers([red, blue])
    answer_text(monkeypatch, "Duo")
    window.create_folder_from_checked()
    path = window.create_template_from_checked()
    assert [info.name for info in list_templates(kind="elements")] == ["Duo"]
    assert list_templates() == []  # not offered as a whole-project preset
    elements = open_project(path)
    assert [layer.name for layer in elements.layers] == ["Rouge", "Bleu"]
    assert len(elements.folders) == 1 and (elements.layers[0].x, elements.layers[0].y) == (0, 0)
    assert (elements.width, elements.height) == (60, 50)


def test_layer_cut_from_a_selection_stays_in_its_source_folder(three_layers, monkeypatch):
    from app import selection as S
    window, (red, text, blue) = three_layers
    window.set_checked_layers([red, text])
    answer_text(monkeypatch, "Groupe")
    window.create_folder_from_checked()
    folder_id = window.document.folders[0].id
    window.select_layer(red)
    window.set_selection(S.rectangle((100, 80), (10, 10, 30, 30)), "test")
    assert window.selection_to_new_layer(cut=True)
    new_layer = window.document.layer(window.selected_id)
    assert new_layer.folder == folder_id
    members = [layer.id for layer in window.document.folder_members(folder_id)]
    assert members == [red, new_layer.id, text]


def test_the_folder_check_box_toggles_at_every_click(window):
    document = Document(100, 100)
    first = document.add_image_bytes(png(10, 10, (255, 0, 0, 255)), "a")
    second = document.add_image_bytes(png(10, 10, (0, 0, 255, 255)), "b")
    folder = document.create_folder([first.id, second.id], "Dossier")
    window.install_document(document, None)
    row = next(window.layer_list.item(index) for index in range(window.layer_list.count())
               if window.layer_list.item(index).data(FOLDER_ROLE))
    assert row.data(Qt.ItemDataRole.UserRole) == folder.id
    box = window.layer_list.itemWidget(row).findChild(QCheckBox, "layerCheck")
    states = []
    for _ in range(3):
        box.click()  # the row is updated in place: its captured state used to stay "unchecked"
        states.append(set(window.checked_ids))
    assert states == [{first.id, second.id}, set(), {first.id, second.id}]


def test_the_layer_list_adds_its_rows_before_their_widgets(window, monkeypatch):
    """Interleaving addItem and setItemWidget relayouts the list each time: 4 s for 1,000 layers."""
    from PySide6.QtWidgets import QListWidget

    document = Document(64, 64)
    for index in range(30):
        document.add_image_bytes(png(4, 4, (index, 0, 0, 255)), f"Sprite {index}")
    folder = document.create_folder([document.layers[0].id, document.layers[1].id], "Dossier")
    assert folder is not None
    counts = []
    original = QListWidget.setItemWidget

    def recording(list_widget, item, widget):
        counts.append(list_widget.count())
        original(list_widget, item, widget)

    monkeypatch.setattr(QListWidget, "setItemWidget", recording)
    window.install_document(document, document.layers[5].id)
    rows = window.layer_list.count()
    assert rows == 31 and counts == [rows] * rows
    current = window.layer_list.currentItem()
    assert current is not None and current.data(Qt.ItemDataRole.UserRole) == document.layers[5].id
    assert all(window.layer_list.itemWidget(window.layer_list.item(index)) is not None for index in range(rows))
