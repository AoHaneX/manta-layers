"""Shape layers, alignment guides and snapping."""
import pytest
from PySide6.QtCore import QPointF, Qt

from app.graphics import layer_transform, qimage_to_pil, render_document
from app.model import Document, Layer
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
