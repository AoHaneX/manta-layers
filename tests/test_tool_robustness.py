"""Tools on damaged layers, scene replacement during a click, shapes, eraser and token export."""
from zipfile import ZipFile

import pytest
import shiboken6
from conftest import png_bytes
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import selection
from app.graphics import _eraser_dab, layers_bounds
from app.model import Document, Layer
from app.storage import save_project


@pytest.fixture
def damaged(window, tmp_path, monkeypatch):
    """Project opened with one damaged image layer (shown hatched) and one intact layer."""
    document = Document(40, 30)
    intact = document.add_image_bytes(png_bytes(8, 8, (0, 0, 255, 255)), "Intact", center=False)
    broken = document.add_image_bytes(png_bytes(6, 6), "Cassée", center=False)
    path = tmp_path / "abime.manta"
    save_project(document, path)
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[f"assets/{broken.asset}.png"] = entries[f"assets/{broken.asset}.png"][:40]
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(path), ""))
    window.open_document()
    window.select_layer(broken.id)
    reported = []
    monkeypatch.setattr(window, "_report_failure", lambda action, exc: reported.append(action))
    return window, intact, broken, reported


# --- P1-002 : the replaced scene is deleted after the event, never during it ----------------

def test_the_previous_scene_is_deleted_only_once_events_are_processed(window):
    previous = window.canvas_scene
    window.install_document(Document(30, 20), None)
    assert shiboken6.isValid(previous)  # still alive: it may be handling the current event
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(previous)  # and released afterwards, not kept forever


def test_a_click_that_commits_a_pending_curve_replaces_the_scene_safely(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    document = Document(400, 300)
    image = document.add_image_bytes(png_bytes(60, 60), "Image", center=False)
    image.x = image.y = 200
    text = document.add_text("Courbe")
    text.x, text.y = 10, 10
    window.install_document(document, text.id)
    window.canvas.fit_document()
    window.curve_intensity.setValue(40)  # starts the pending curve timer
    assert window.curve_commit_timer.isActive()
    scene = window.canvas_scene
    item = window.canvas.graphic_for(image.id)
    position = window.canvas.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert window.canvas_scene is not scene  # the curve was committed during the click
    assert window.document.layer(text.id).curve_intensity == 40
    assert window.selected_id == image.id


# --- P2-001 : every tool reports a damaged image instead of raising -------------------------

def test_trim_and_crop_report_a_damaged_image(damaged):
    window, _intact, broken, reported = damaged
    count = window.undo_stack.count()
    assert not window.trim_layer_margins(broken.id)
    assert not window.crop_document_to_content()
    assert reported == ["Rogner les marges transparentes", "Recadrer le document sur son contenu"]
    assert window.undo_stack.count() == count


def test_selection_tools_report_a_damaged_image(damaged):
    window, _intact, broken, reported = damaged
    window.set_selection(selection.full((40, 30)), "Tout")
    count = window.undo_stack.count()
    assert not window.copy_selection()
    assert not window.selection_to_new_layer(cut=True)
    window.wand_all_layers.setChecked(False)
    window.apply_magic_wand(QPointF(1, 1), Qt.KeyboardModifier.NoModifier)
    assert window.undo_stack.count() == count
    assert reported and set(reported) <= {"Pixels sélectionnés", "Baguette magique"}


def test_the_all_layers_wand_ignores_damaged_images(damaged):
    window, intact, _broken, reported = damaged
    window.wand_all_layers.setChecked(True)
    window.apply_magic_wand(QPointF(intact.x + 2, intact.y + 2), Qt.KeyboardModifier.NoModifier)
    assert not reported
    assert window.selection_mask is not None and window.selection_mask.getbbox() is not None


def test_background_removal_and_merge_report_a_damaged_image(damaged):
    window, intact, broken, reported = damaged
    window.remove_background()
    window.set_checked_layers([intact.id, broken.id])
    assert not window.merge_checked_layers()
    assert reported == ["Supprimer l'arrière-plan", "Fusionner les calques"]


def test_bounds_of_a_damaged_layer_use_its_declared_size(damaged):
    window, _intact, broken, _reported = damaged
    assert layers_bounds(window.document, [broken.id]) is not None


def test_dialogs_report_a_damaged_layer(damaged, monkeypatch):
    from app.sprite_dialog import SpriteSheetDialog
    from app.token_dialog import TokenDialog

    window, _intact, _broken, _reported = damaged
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: warnings.append(args[1]))
    sprites, token = SpriteSheetDialog(window), TokenDialog(window)
    try:
        sprites.use_selected_layer()
        token.use_selected_layer()
    finally:
        sprites.deleteLater()
        token.deleteLater()
    assert warnings == ["Image illisible", "Créateur de tokens"]


# --- P2-002 : a closed shape turned into a line or an arrow stays visible --------------------

@pytest.mark.parametrize("kind", ["line", "arrow"])
def test_a_rectangle_turned_into_a_line_stays_visible(window, kind):
    from PySide6.QtCore import Qt

    document = Document(200, 200)
    rectangle = Layer(kind="shape", shape_type="rectangle", fill_color="#FF0000", stroke_color="#000000",
                      stroke_width=0.0)
    document.layers.append(rectangle)
    window.install_document(document, rectangle.id)
    assert window.set_shape_property("shape_type", kind)
    layer = window.document.layer(rectangle.id)
    assert layer.stroke_width > 0 and layer.stroke_color
    assert window.canvas.graphic_for(rectangle.id).pen.style() != Qt.PenStyle.NoPen


# --- P2-003 : small round eraser dabs erase their pixels -------------------------------------

@pytest.mark.parametrize("size", [1, 2, 3])
@pytest.mark.parametrize("pixel_art", [True, False])
def test_round_eraser_dabs_cover_their_box(size, pixel_art):
    assert _eraser_dab(size, "circle", pixel_art, 100, 100).getbbox() == (0, 0, size, size)


def test_a_one_pixel_round_stroke_erases_one_pixel(window):
    from PySide6.QtCore import QPointF

    document = Document(20, 20)
    layer = document.add_image_bytes(png_bytes(8, 8), "Calque", center=False)
    window.install_document(document, layer.id)
    window.eraser_size.setValue(1)
    window.eraser_shape.setCurrentIndex(window.eraser_shape.findData("circle"))
    window.commit_eraser_stroke(layer.id, [QPointF(3.5, 3.5)])
    image = window.canvas.graphic_for(layer.id).pixmap().toImage()
    assert image.pixelColor(3, 3).alpha() == 0 and image.pixelColor(4, 3).alpha() == 255
