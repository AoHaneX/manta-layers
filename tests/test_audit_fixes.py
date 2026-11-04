"""Regression tests for the defects found by the third audit (docs/AUDIT_V3.md)."""
import json
import time
from zipfile import ZipFile

import pytest
from conftest import png_bytes
from PIL import Image
from PySide6.QtCore import QPointF, QSize
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app import graphics
from app.graphics import _interpolated_points, apply_eraser_strokes, grapheme_clusters, render_document
from app.model import Document, Layer
from app.storage import open_project, save_project


def _install(window, document, selected=None):
    window._start_session(document, None)
    if selected:
        window.select_layer(selected)


def _image_document(width=40, height=30, color=(200, 10, 10, 255)):
    document = Document(width, height)
    layer = document.add_image_bytes(png_bytes(10, 10, color), "Carré", center=False)
    layer.x, layer.y = 5, 5
    return document, layer


# --- P2-001 : folding a folder keeps the current layer ---------------------------------

def test_folding_a_folder_keeps_the_selected_layer(window):
    document, layer = _image_document()
    other = document.add_image_bytes(png_bytes(4, 4), "Autre", center=False)
    folder = document.create_folder([other.id], "Dossier")
    _install(window, document, layer.id)
    window.toggle_folder_collapsed(folder.id)
    assert window.selected_id == layer.id
    window.toggle_folder_collapsed(folder.id)
    assert window.selected_id == layer.id


# --- P2-002 : a change that cannot be shown leaves the history as it was ----------------

def test_a_failed_change_keeps_redo_and_saved_state(window, monkeypatch):
    document, layer = _image_document()
    _install(window, document, layer.id)
    window.nudge_layer(1, 0)
    time.sleep(0)  # distinct steps: no merge key shared within the same push
    window.mutate("Renommer", lambda doc: setattr(doc.layer(layer.id), "name", "A"), layer.id)
    window.undo_stack.setClean()
    window.undo_stack.undo()
    assert window.undo_stack.canRedo()
    clean_index = window.undo_stack.cleanIndex()

    def broken(_document):
        raise ValueError("rendu impossible")

    monkeypatch.setattr(window, "_make_scene", broken)
    monkeypatch.setattr(window, "_report_failure", lambda *_args: None)
    assert not window.mutate("Renommer", lambda doc: setattr(doc.layer(layer.id), "name", "B"), layer.id)
    assert window.undo_stack.canRedo()
    assert window.undo_stack.cleanIndex() == clean_index


# --- P2-004 : resizing the document records the selection ------------------------------

def test_undoing_a_resize_restores_the_whole_selection(window):
    window.install_document(Document(100, 100), None)
    window.undo_stack.clear()
    window.select_all()
    assert window.set_document_size(50, 50)
    assert window.selection_mask.size == (50, 50)
    window.undo_stack.undo()
    assert window.selection_mask.size == (100, 100)
    assert window.selection_mask.getbbox() == (0, 0, 100, 100)


def test_a_selection_left_outside_the_frame_disappears(window):
    from app import selection

    window.install_document(Document(100, 100), None)
    window.set_selection(selection.rectangle((100, 100), (60, 60, 90, 90)), "Sélection")
    window.set_document_size(50, 50)
    assert window.selection_mask is None


# --- P2-005 : redo selects the layer it creates ----------------------------------------

def test_redoing_a_duplicate_selects_the_copy(window):
    document, layer = _image_document()
    _install(window, document, layer.id)
    window.duplicate_layer()
    copy = window.selected_id
    assert copy != layer.id
    window.undo_stack.undo()
    window.select_layer(layer.id)
    window.undo_stack.redo()
    assert window.selected_id == copy


# --- P2-006 : the recovery copy follows the document shown -----------------------------

def test_leaving_a_document_deletes_its_recovery_copy(window, monkeypatch):
    document, layer = _image_document()
    _install(window, document, layer.id)
    window.nudge_layer(3, 0)
    assert window.autosave_now()
    copy, _meta = window.recovery.files(window.recovery.session_id)
    assert copy.exists()
    window._start_session(Document(20, 20), None)  # "Ne pas enregistrer", then another document
    assert not copy.exists()


def test_undoing_back_to_the_saved_state_deletes_the_copy(window):
    document, layer = _image_document()
    _install(window, document, layer.id)
    window.nudge_layer(3, 0)
    assert window.autosave_now()
    copy, _meta = window.recovery.files(window.recovery.session_id)
    window.undo_stack.undo()
    assert not window.autosave_now()
    assert not copy.exists()


# --- P2-007 : "Save as" asks before replacing the completed name -----------------------

def test_save_as_asks_before_replacing_the_completed_file(window, monkeypatch, tmp_path):
    existing = tmp_path / "plan.v2.manta"
    existing.write_bytes(b"ancien")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(tmp_path / "plan.v2"), ""))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **_k: asked.append(args[2]) or QMessageBox.StandardButton.No)
    assert not window.save_as_document()
    assert asked and existing.read_bytes() == b"ancien"


# --- P2-008 : far away eraser points cost nothing --------------------------------------

def test_far_away_eraser_points_render_quickly():
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    stroke = {"points": [[10.0, 10.0], [1e12, 10.0], [10.0, 20.0]], "size": 4, "pixel_art": True,
              "pixel_centered": True}
    start = time.monotonic()
    result = apply_eraser_strokes(image, [stroke])
    assert time.monotonic() - start < 2
    assert result.getpixel((30, 10))[3] == 0  # the part inside the image is still erased


def test_clipping_keeps_the_same_dab_positions():
    bounds = (-5.0, -5.0, 45.0, 45.0)
    points = [[-300.0, 12.3], [80.7, 30.1], [20.0, -90.0], [10.0, 10.0]]
    full = [point for point in _interpolated_points(points, 0.5)
            if bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]]
    clipped = [point for point in _interpolated_points(points, 0.5, bounds)
               if bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]]
    assert clipped == full


def test_a_forged_project_with_huge_strokes_opens(tmp_path):
    asset = "a" * 32
    path = tmp_path / "forge.manta"
    with ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({
            "format": "MantaLayers", "version": 2, "width": 32, "height": 32, "background": None,
            "layers": [{"id": "img", "kind": "image", "asset": asset, "name": "Image", "eraser_strokes": [
                {"points": [[0, 0], [1e12, 0]] + [[1, 1]] * 200_000, "size": 3, "pixel_centered": True},
            ]}],
        }))
        archive.writestr(f"assets/{asset}.png", png_bytes(8, 8))
    document = open_project(path)
    assert len(document.layer("img").eraser_strokes[0]["points"]) == 100_000
    start = time.monotonic()
    graphics.render_layer_with_mask(document.layer("img"), document)
    assert time.monotonic() - start < 5


# --- P2-009 : a damaged image does not lock the whole project out -----------------------

def test_a_project_with_a_damaged_image_still_opens(window, monkeypatch, tmp_path):
    document, layer = _image_document()
    broken = document.add_image_bytes(png_bytes(6, 6), "Cassée", center=False)
    path = tmp_path / "abime.manta"
    save_project(document, path)
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[f"assets/{broken.asset}.png"] = entries[f"assets/{broken.asset}.png"][:40]  # truncated
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(path), ""))
    window.open_document()
    assert window.document.layer(broken.id) is not None
    assert warnings and "Cassée" in warnings[0]
    # The rest stays editable, and the damaged layer itself can be moved or deleted.
    assert window.mutate("Renommer", lambda doc: setattr(doc.layer(layer.id), "name", "Intact"), layer.id)
    assert window.mutate("Supprimer", lambda doc: doc.remove_layers([broken.id]))
    # Exporting still refuses the damaged image rather than leaving it out silently.
    window.undo_stack.undo()
    with pytest.raises(ValueError):
        render_document(window.document)


# --- P2-011 : the copy goes back in place, whatever the timing of the notification ------

def test_pasting_our_copy_puts_it_back_in_place_after_a_late_notification(window):
    document, layer = _image_document()
    _install(window, document, layer.id)
    from app import selection

    window.set_selection(selection.rectangle((40, 30), (7, 7, 12, 12)), "Sélection")
    assert window.copy_selection()
    QApplication.clipboard().dataChanged.emit()  # Windows notifies after the copy
    assert window.paste_image()
    pasted = window.document.layer(window.selected_id)
    assert (pasted.x, pasted.y) == (7.0, 7.0)


# --- P2-012 : text is laid out by user-perceived characters ------------------------------

@pytest.mark.parametrize("text, count", [
    ("ab", 2), ("été", 3), ("\U0001F44D\U0001F3FD!", 2), ("\U0001F1EB\U0001F1F7", 1), ("", 0),
])
def test_text_is_split_into_graphemes(text, count):
    assert len(grapheme_clusters(text)) == count
    assert "".join(grapheme_clusters(text)) == text


def test_a_decomposed_accent_is_placed_with_its_letter(qapp):
    item = graphics.CurvedTextGraphicItem(Layer(kind="text", text="é"))
    assert [placement[0] for placement in item.placements] == ["é"]


# --- P2-013 : the colour tools read the exact source colour ------------------------------

def test_the_picker_reads_semi_transparent_colours_exactly(window):
    document = Document(20, 20)
    layer = document.add_image_bytes(png_bytes(4, 4, (200, 100, 50, 10)), "Voile", center=False)
    _install(window, document, layer.id)
    item = window.canvas.graphic_for(layer.id)
    window.picker_target = "tools"
    assert window.sample_canvas_color(item, item.mapToScene(QPointF(1.5, 1.5)))
    assert window.replacement_color == "#C86432"


def test_a_click_just_outside_the_layer_reads_nothing(window):
    document, layer = _image_document()
    _install(window, document, layer.id)
    item = window.canvas.graphic_for(layer.id)
    assert window._layer_pixel(window.document.layer(layer.id), item, item.mapToScene(QPointF(-0.5, 3))) is None


# --- P2-014 / P2-015 : exports and thumbnails without useless copies ---------------------

def test_thumbnails_are_rendered_at_their_size(qapp):
    document = Document(16000, 9000)
    image = render_document(document, QSize(320, 180))
    assert (image.width(), image.height()) == (320, 180)


def test_export_keeps_pixels_when_converting(qapp):
    from app.graphics import qimage_to_pil

    document, _layer = _image_document()
    exported = qimage_to_pil(render_document(document))
    assert exported.size == (40, 30)
    assert exported.getpixel((7, 7)) == (200, 10, 10, 255)
    assert exported.getpixel((0, 0))[3] == 0


# --- P2-003 : the history keeps the changes, not a copy of the whole document per step ---

def test_history_memory_grows_with_the_changes(window):
    import tracemalloc

    document, layer = _image_document(64, 64)
    document.add_image_bytes(png_bytes(8, 8), "Autre", center=False)
    _install(window, document, layer.id)
    points = [QPointF(1 + index * 0.1, 2) for index in range(300)]
    tracemalloc.start()
    try:
        baseline = tracemalloc.get_traced_memory()[0]
        for _ in range(40):
            window.commit_eraser_stroke(layer.id, points)
        retained = tracemalloc.get_traced_memory()[0] - baseline
    finally:
        tracemalloc.stop()
    assert len(window.document.layer(layer.id).eraser_strokes) == 40
    # Copying every earlier stroke into each step retained about 65 MB here.
    assert retained < 15 * 1024 * 1024, retained


def test_unchanged_layers_are_shared_between_steps(window):
    document, layer = _image_document()
    other = document.add_image_bytes(png_bytes(8, 8), "Autre", center=False)
    _install(window, document, layer.id)
    window.nudge_layer(1, 0)
    window.mutate("Renommer", lambda doc: setattr(doc.layer(layer.id), "name", "B"), layer.id)
    first, second = window.undo_stack.command(0), window.undo_stack.command(1)
    assert second.before is first.after
    assert second.after.layer(other.id) is second.before.layer(other.id)
    assert second.after.layer(layer.id) is not second.before.layer(layer.id)
    # Undo and redo still restore each state exactly.
    window.undo_stack.undo()
    assert window.document.layer(layer.id).name == "Carré"
    window.undo_stack.undo()
    assert window.document.layer(layer.id).x == 5
    window.undo_stack.redo()
    window.undo_stack.redo()
    assert window.document.layer(layer.id).name == "B" and window.document.layer(layer.id).x == 6
