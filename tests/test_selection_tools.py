"""Selection tools on the canvas and the operations on selected content."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app import selection as S  # noqa: E402
from app.graphics import render_layers  # noqa: E402
from app.model import Document  # noqa: E402
from app.storage import open_project, save_project  # noqa: E402
from conftest import png_bytes  # noqa: E402


def two_colour_document():
    """100×60 document: left half red, right half blue, on one layer at (10, 20)."""
    from PIL import Image
    import io
    image = Image.new("RGBA", (60, 30), (220, 20, 20, 255))
    image.paste((20, 20, 220, 255), (30, 0, 60, 30))
    data = io.BytesIO()
    image.save(data, format="PNG")
    document = Document(100, 60)
    layer = document.add_image_bytes(data.getvalue(), "Bicolore", center=False)
    layer.x, layer.y = 10.0, 20.0
    return document, layer.id


@pytest.fixture
def setup(window):
    document, layer_id = two_colour_document()
    window.install_document(document, layer_id)
    window.undo_stack.clear()
    window.canvas.resetTransform()
    window.canvas.scale(4, 4)
    return window, layer_id


def drag(window, start: QPointF, end: QPointF, modifier=Qt.KeyboardModifier.NoModifier):
    viewport = window.canvas.viewport()
    a, b = window.canvas.mapFromScene(start), window.canvas.mapFromScene(end)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, modifier, a)
    QTest.mouseMove(viewport, (a + b) / 2)
    QTest.mouseMove(viewport, b)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, modifier, b)


def test_rectangle_tool_and_modifiers_combine_selections(setup):
    window, _layer = setup
    window.set_selection_tool("rect")
    drag(window, QPointF(10, 20), QPointF(40, 50))
    assert S.bounds(window.selection_mask) == (10, 20, 40, 50)
    drag(window, QPointF(30, 20), QPointF(60, 50), Qt.KeyboardModifier.ShiftModifier)
    assert S.bounds(window.selection_mask) == (10, 20, 60, 50)
    drag(window, QPointF(10, 20), QPointF(20, 50), Qt.KeyboardModifier.AltModifier)
    assert S.bounds(window.selection_mask) == (20, 20, 60, 50)
    window.undo_stack.undo()
    assert S.bounds(window.selection_mask) == (10, 20, 60, 50)
    assert window.canvas.selection_path is not None


def test_click_without_drag_deselects(setup):
    window, _layer = setup
    window.select_all()
    window.set_selection_tool("ellipse")
    drag(window, QPointF(30, 30), QPointF(30, 30))
    assert window.selection_mask is None


def test_magic_wand_selects_the_clicked_colour_in_document_space(setup):
    window, _layer = setup
    window.set_selection_tool("wand")
    point = window.canvas.mapFromScene(QPointF(15, 25))
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert S.bounds(window.selection_mask) == (10, 20, 40, 50)


def test_delete_hides_pixels_through_a_layer_mask_and_undo_restores(setup):
    window, layer_id = setup
    source = window.document.assets[window.document.layer(layer_id).asset]
    window.set_selection(S.rectangle((100, 60), (10, 20, 25, 50)), "test")
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    layer = window.document.layer(layer_id)
    assert layer is not None and layer.mask is not None
    assert window.document.assets[layer.asset] == source  # source never rewritten
    rendered = render_layers(window.document, [layer_id])
    assert rendered.getpixel((15, 30))[3] == 0 and rendered.getpixel((30, 30))[3] == 255
    window.undo_stack.undo()
    assert window.document.layer(layer_id).mask is None


def test_layer_mask_survives_save_and_reopen(setup, tmp_path):
    window, layer_id = setup
    window.set_selection(S.rectangle((100, 60), (10, 20, 25, 50)), "test")
    window.clear_selection_content()
    path = tmp_path / "masque.manta"
    save_project(window.document, path)
    reopened = open_project(path)
    assert reopened.layer(layer_id).mask == window.document.layer(layer_id).mask
    assert render_layers(reopened, [layer_id]).getpixel((15, 30))[3] == 0


def test_reveal_restores_hidden_pixels_and_drops_a_full_mask(setup):
    window, layer_id = setup
    window.set_selection(S.rectangle((100, 60), (10, 20, 25, 50)), "test")
    window.clear_selection_content()
    window.reveal_selection_in_mask()
    assert window.document.layer(layer_id).mask is None


def test_copy_to_new_layer_keeps_position_and_only_selected_pixels(setup):
    window, layer_id = setup
    window.set_selection(S.rectangle((100, 60), (35, 25, 45, 35)), "test")
    assert window.selection_to_new_layer(cut=False)
    new = window.document.layer(window.selected_id)
    assert (new.x, new.y) == (35.0, 25.0)
    assert [layer.id for layer in window.document.layers].index(new.id) == 1
    pixels = render_layers(window.document, [new.id])
    assert pixels.getpixel((36, 30)) == (220, 20, 20, 255)
    assert pixels.getpixel((44, 30)) == (20, 20, 220, 255)
    assert pixels.getpixel((50, 30))[3] == 0
    assert window.document.layer(layer_id).mask is None


def test_cut_to_new_layer_is_a_single_undo_step(setup):
    window, layer_id = setup
    window.set_selection(S.rectangle((100, 60), (10, 20, 30, 30)), "test")
    count = window.undo_stack.count()
    window.selection_to_new_layer(cut=True)
    assert window.document.layer(layer_id).mask is not None
    assert len(window.document.layers) == 2 and window.undo_stack.count() == count + 1
    window.undo_stack.undo()
    assert len(window.document.layers) == 1 and window.document.layer(layer_id).mask is None


def test_ctrl_drag_moves_selected_pixels_and_selection(setup):
    window, layer_id = setup
    window.set_selection(S.rectangle((100, 60), (12, 22, 20, 30)), "test")
    window.set_selection_tool("rect")
    count = window.undo_stack.count()
    drag(window, QPointF(15, 25), QPointF(45, 35), Qt.KeyboardModifier.ControlModifier)
    moved = window.document.layer(window.selected_id)
    assert moved.id != layer_id and (moved.x, moved.y) == (42.0, 32.0)
    assert S.bounds(window.selection_mask) == (42, 32, 50, 40)
    assert window.undo_stack.count() == count + 1  # one macro for pixels and selection
    window.undo_stack.undo()
    assert len(window.document.layers) == 1 and S.bounds(window.selection_mask) == (12, 22, 20, 30)


def test_selection_follows_scaled_and_flipped_layers(window):
    document = Document(100, 100)
    layer = document.add_image_bytes(png_bytes(10, 10, (0, 200, 0, 255)), "Vert", center=False)
    layer.x, layer.y, layer.sx, layer.sy, layer.flip_horizontal = 20.0, 20.0, 4.0, 4.0, True
    window.install_document(document, layer.id)
    window.set_selection(S.rectangle((100, 100), (20, 20, 40, 60)), "test")  # left half on screen
    window.clear_selection_content()
    rendered = render_layers(window.document, [layer.id])
    assert rendered.getpixel((25, 30))[3] == 0 and rendered.getpixel((50, 30))[3] == 255


def test_copy_and_paste_returns_to_the_same_place(setup):
    window, _layer = setup
    window.set_selection(S.rectangle((100, 60), (50, 40, 60, 45)), "test")
    assert window.copy_selection()
    window.deselect()
    assert window.paste_image()
    pasted = window.document.layer(window.selected_id)
    assert (pasted.x, pasted.y) == (50.0, 40.0)


def test_pixel_edits_are_refused_on_text_layers(window):
    document = Document(100, 60)
    text = document.add_text("Vectoriel")
    window.install_document(document, text.id)
    window.select_all()
    count = window.undo_stack.count()
    window.clear_selection_content()
    assert window.undo_stack.count() == count and window.document.layer(text.id) is not None
    assert window.selection_to_new_layer(cut=False)  # copying a rendered text is allowed


def test_delete_without_selection_still_deletes_the_layer(setup):
    window, layer_id = setup
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    assert window.document.layer(layer_id) is None


def test_mask_view_toggle_and_document_resize_keep_selection_consistent(setup):
    window, _layer = setup
    window.select_all()
    window.show_selection_mask.setChecked(True)
    assert window.canvas.selection_overlay_image is not None
    window.mutate("Agrandir", lambda doc: (setattr(doc, "width", 150), setattr(doc, "height", 80)))
    assert window.selection_mask.size == (150, 80)


def test_new_document_starts_without_selection(setup, monkeypatch):
    window, _layer = setup
    window.select_all()
    window.install_document(Document(50, 50), None)
    window._reset_selection()
    assert window.selection_mask is None and window.canvas.selection_overlay_image is None


def test_viewport_points_are_used_by_drag_helper(setup):
    window, _layer = setup
    assert isinstance(window.canvas.mapFromScene(QPointF(1, 1)), QPoint)
