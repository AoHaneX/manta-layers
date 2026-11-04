"""Shape layers, alignment guides and snapping."""
import pytest
from conftest import png_bytes
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.graphics import layer_transform, qimage_to_pil, render_document
from app.model import SHAPE_TYPES, Document, Layer
from app.shape_item import shape_from_drag
from app.storage import open_project, save_project

NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def test_dragged_boxes_click_defaults_and_constrained_squares():
    rect = shape_from_drag("rectangle", (50, 40), (10, 20), False, "#112233")
    assert (rect.x, rect.y, rect.shape_width, rect.shape_height) == (10, 20, 40, 20)
    assert rect.fill_color == "#112233" and rect.stroke_width == 0
    square = shape_from_drag("ellipse", (0, 0), (30, 10), True, "#112233")
    assert square.shape_width == square.shape_height == 30
    clicked = shape_from_drag("polygon", (100, 100), (100.5, 100), False, "#112233")
    assert (clicked.shape_width, clicked.shape_height) == (160, 110)
    assert (clicked.x + clicked.shape_width / 2, clicked.y + clicked.shape_height / 2) == (100, 100)


def test_lines_start_under_the_press_and_snap_to_45_degrees():
    line = shape_from_drag("arrow", (20, 30), (80, 95), True, "#ABCDEF")
    assert line.rotation == 45 and line.fill_color is None and line.stroke_color == "#ABCDEF"
    start = layer_transform(line).map(QPointF(0, line.shape_height / 2))
    assert (round(start.x(), 6), round(start.y(), 6)) == (20, 30)


def test_shape_properties_are_validated_and_saved(tmp_path):
    raw = Layer(kind="shape", shape_type="unknown", shape_width=-5, fill_color="red", stroke_width=9999,
                polygon_sides=1).__dict__
    layer = Layer.from_dict(dict(raw))
    assert (layer.shape_type, layer.shape_width, layer.fill_color) == ("rectangle", 1.0, None)
    assert (layer.stroke_width, layer.polygon_sides) == (500.0, 3)
    document = Document(50, 50)
    document.layers.append(shape_from_drag("ellipse", (5, 5), (45, 45), False, "#00FF00"))
    path = tmp_path / "formes.manta"
    save_project(document, path)
    reopened = open_project(path).layers[0]
    assert (reopened.kind, reopened.shape_type, reopened.fill_color) == ("shape", "ellipse", "#00FF00")


@pytest.mark.parametrize("kind", ["rectangle", "ellipse", "polygon", "speech", "thought", "banner"])
def test_closed_shapes_render_their_fill_in_exports(qapp, kind):
    document = Document(100, 100)
    document.layers.append(shape_from_drag(kind, (10, 10), (90, 90), False, "#FF0000"))
    image = qimage_to_pil(render_document(document))
    assert image.getpixel((50, 40))[:3] == (255, 0, 0)
    assert image.getpixel((2, 2))[3] == 0


def test_lines_and_arrows_render_their_outline(qapp):
    document = Document(100, 40)
    document.layers.append(shape_from_drag("arrow", (5, 20), (95, 20), False, "#0000FF"))
    image = qimage_to_pil(render_document(document))
    assert image.getpixel((40, 20))[:3] == (0, 0, 255) and image.getpixel((90, 20))[3] > 0
    assert image.getpixel((40, 5))[3] == 0


def test_shape_tool_creates_an_editable_layer_with_undo(window):
    window.install_document(Document(200, 150), None)
    window.undo_stack.clear()
    window.set_current_color("#336699")
    window.set_shape_tool("rectangle")
    assert window.any_tool_active()
    assert window.create_shape(QPointF(20, 20), QPointF(120, 80), NO_MODIFIER)
    layer = window.document.layers[-1]
    assert window.selected_id == layer.id and layer.fill_color == "#336699"
    assert window.set_shape_property("shape_width", 40.0)
    assert window.set_shape_property("stroke_color", "#000000")
    shape = window.document.layer(layer.id)
    assert (shape.shape_width, shape.stroke_width) == (40.0, 4.0)  # a chosen outline becomes visible
    assert not window.set_shape_property("shape_width", 40.0)  # no change, no history step
    window.undo_stack.undo()
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.document.layers == []


def test_shape_rows_follow_the_selected_layer(window):
    document = Document(100, 100)
    document.layers.append(shape_from_drag("polygon", (0, 0), (50, 50), False, "#123456"))
    document.add_text("Texte")
    window.install_document(document, document.layers[0].id)
    rows = window.shape_rows
    assert not rows.sides.isHidden() and rows.radius.isHidden()
    assert rows.fill.button.text() == "#123456"
    window.select_layer(document.layers[1].id)
    assert rows.width.isHidden()


def test_colour_values_are_shown_in_full(window, qapp):
    document = Document(100, 100)
    document.layers.append(shape_from_drag("rectangle", (0, 0), (50, 50), False, "#092B40"))
    window.install_document(document, document.layers[0].id)
    qapp.processEvents()
    for field in (window.shape_rows.fill, window.shape_rows.stroke):
        text_width = field.button.fontMetrics().horizontalAdvance(field.button.text())
        assert field.button.width() >= field.button.minimumWidth() >= text_width + 12


@pytest.fixture
def two_squares(window):
    document = Document(200, 200)
    first = shape_from_drag("rectangle", (10, 10), (50, 50), False, "#FF0000")
    second = shape_from_drag("rectangle", (150, 150), (190, 190), False, "#00FF00")
    document.layers += [first, second]
    window.install_document(document, first.id)
    window.undo_stack.clear()
    return window, first.id, second.id


def drag(window, layer_id, travel: QPointF, modifiers=NO_MODIFIER):
    window.install_document(window.document.clone(), window.selected_id)  # a fresh, undragged scene
    canvas = window.canvas
    item = canvas.graphic_for(layer_id)
    press = item.sceneBoundingRect().center()
    canvas.mode, canvas.drag_item = "move", item
    canvas._start_move(item, press)
    canvas._after_move_step(modifiers, press + travel)
    return item


def test_dragged_layer_snaps_to_the_document_centre_and_shows_guides(two_squares):
    window, first, _second = two_squares
    window.snap_enabled = True
    item = drag(window, first, QPointF(67, 0))  # centre 30 -> 97, the document centre is 100
    assert item.sceneBoundingRect().center().x() == pytest.approx(100, abs=0.01)
    assert ("v", 100.0) in window.canvas.active_guides
    exported = qimage_to_pil(render_document(window.document))
    assert exported.getpixel((100, 5))[3] == 0  # guides never reach the export


def test_snapping_can_be_disabled_or_bypassed_with_alt(two_squares):
    window, first, _second = two_squares
    window.snap_enabled = False
    item = drag(window, first, QPointF(67, 0))
    assert item.sceneBoundingRect().center().x() == pytest.approx(97, abs=0.01)
    window.snap_enabled = True
    item = drag(window, first, QPointF(67, 0), Qt.KeyboardModifier.AltModifier)
    assert item.sceneBoundingRect().center().x() == pytest.approx(97, abs=0.01)


def test_snapping_aligns_with_other_layers(two_squares):
    window, first, second = two_squares
    window.snap_enabled = True
    item = drag(window, first, QPointF(138, 0))  # left edge 10 -> 148, the other square starts at 150
    assert item.sceneBoundingRect().left() == pytest.approx(150, abs=0.01)


def test_checked_layers_move_together_in_one_step(two_squares):
    window, first, second = two_squares
    window.snap_enabled = False
    window.set_checked_layers([first, second])
    drag(window, first, QPointF(5, 7))
    group = window.canvas._finish_move()
    assert len(group) == 2
    before = window.document.clone()
    positions = {graphic.data(0): (graphic.pos().x(), graphic.pos().y()) for graphic in group}
    assert window.commit_canvas_moves(before, positions)
    assert (window.document.layer(second).x, window.document.layer(second).y) == (155, 157)
    window.undo_stack.undo()
    assert window.document.layer(second).x == 150


# --- Undo or redo while the mouse button is held ----------------------------------------


def _mouse(widget, kind, position, button, buttons):
    event = QMouseEvent(kind, QPointF(position), QPointF(widget.mapToGlobal(position)), button, buttons,
                        NO_MODIFIER)
    QApplication.sendEvent(widget, event)


@pytest.fixture
def one_image(window):
    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(100, 100), "image")
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    return window, layer.id


def _press_undo_move_release(window, layer_id):
    viewport = window.canvas.viewport()
    start = window.canvas.mapFromScene(window.canvas.graphic_for(layer_id).sceneBoundingRect().center())
    end = start + QPoint(40, 0)
    _mouse(viewport, QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    window.undo_stack.undo()  # Ctrl+Z while the button is held: the scene is rebuilt
    _mouse(viewport, QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    _mouse(viewport, QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def test_undo_during_a_drag_abandons_the_drag(one_image):
    window, layer_id = one_image
    start_x = window.document.layer(layer_id).x
    window.nudge_layer(5, 0)
    _press_undo_move_release(window, layer_id)  # used to raise "C++ object already deleted"
    assert window.canvas.mode is None and window.canvas.drag_item is None
    assert window.document.layer(layer_id).x == start_x  # the undo is kept, the drag is dropped
    assert window.undo_stack.index() == 0


def test_undo_during_an_eraser_stroke_drops_the_stroke(one_image):
    window, layer_id = one_image
    window.nudge_layer(5, 0)
    window.set_eraser_active(True)
    _press_undo_move_release(window, layer_id)
    assert window.canvas.eraser_item is None
    assert window.document.layer(layer_id).eraser_strokes == []


@pytest.mark.parametrize("shape_type", SHAPE_TYPES)
def test_thick_outlines_stay_inside_the_layer_bounds(qapp, shape_type):
    """Merging crops to the bounds: they must hold the whole outline, sharp corners included."""
    from app.graphics import render_layers, render_layers_region

    document = Document(800, 800)
    layer = Layer(kind="shape", shape_type=shape_type, polygon_sides=3, shape_width=200, shape_height=180,
                  x=300, y=300, fill_color="#FF0000", stroke_color="#000000", stroke_width=40)
    document.layers.append(layer)
    ink = render_layers(document, [layer.id]).getchannel("A").getbbox()
    image, (left, top) = render_layers_region(document, [layer.id])
    assert left <= ink[0] and top <= ink[1]
    assert left + image.width >= ink[2] and top + image.height >= ink[3]
