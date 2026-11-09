"""Canvas driven by real mouse and wheel events: move, resize, rotate, eraser, Ctrl+drag, zoom."""
import pytest
from conftest import png_bytes
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from app import selection
from app.graphics import render_layer_with_mask

LEFT = Qt.MouseButton.LeftButton
NO_BUTTON = Qt.MouseButton.NoButton
NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def send(widget, kind, position, button, buttons, modifiers=NO_MODIFIER):
    event = QMouseEvent(kind, QPointF(position), QPointF(widget.mapToGlobal(position)), button, buttons, modifiers)
    QApplication.sendEvent(widget, event)


def mouse_drag(window, start: QPointF, end: QPointF, steps=4, modifiers=NO_MODIFIER):
    """Press at ``start``, move in steps to ``end`` and release (document coordinates)."""
    canvas, viewport = window.canvas, window.canvas.viewport()
    begin, finish = canvas.mapFromScene(start), canvas.mapFromScene(end)
    send(viewport, QEvent.Type.MouseButtonPress, begin, LEFT, LEFT, modifiers)
    for index in range(1, steps + 1):
        point = begin + (finish - begin) * index / steps
        send(viewport, QEvent.Type.MouseMove, point, NO_BUTTON, LEFT, modifiers)
    send(viewport, QEvent.Type.MouseButtonRelease, finish, LEFT, NO_BUTTON, modifiers)


@pytest.fixture
def image_layer(window):
    """A 40 × 20 image at (100, 60) in a 400 × 300 document, shown at 200 %."""
    from app.model import Document
    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(40, 20), "image", center=False)
    layer.x, layer.y = 100.0, 60.0
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    window.canvas.resetTransform()
    window.canvas.scale(2, 2)
    window.canvas.centerOn(QPointF(120, 70))
    window.snap_enabled = False
    return window, layer.id


def test_dragging_a_layer_moves_it_in_one_history_step(image_layer):
    window, layer_id = image_layer
    mouse_drag(window, QPointF(120, 70), QPointF(150, 90))
    layer = window.document.layer(layer_id)
    assert (layer.x, layer.y) == pytest.approx((130, 80), abs=1)
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert (window.document.layer(layer_id).x, window.document.layer(layer_id).y) == (100, 60)


def test_dragging_a_corner_handle_scales_the_layer(image_layer):
    window, layer_id = image_layer
    canvas = window.canvas
    item = canvas.graphic_for(layer_id)
    corner = item.mapToScene(canvas.local_handles(item)[2])  # bottom right, (140, 80)
    mouse_drag(window, corner, corner + QPointF(40, 20))
    layer = window.document.layer(layer_id)
    assert (layer.sx, layer.sy) == pytest.approx((2, 2), abs=0.05)
    assert (layer.x, layer.y) == pytest.approx((100, 60), abs=0.5)  # the opposite corner stays


def test_dragging_the_rotation_handle_turns_the_layer(image_layer):
    window, layer_id = image_layer
    canvas = window.canvas
    item = canvas.graphic_for(layer_id)
    handle = canvas.rotation_point(item)
    centre = item.mapToScene(item.boundingRect().center())
    distance = centre.y() - handle.y()
    mouse_drag(window, handle, centre + QPointF(distance, 0), steps=8)  # a quarter turn clockwise
    assert window.document.layer(layer_id).rotation == pytest.approx(90, abs=2)


def test_an_eraser_click_erases_the_pixel_under_the_pointer(image_layer):
    window, layer_id = image_layer
    window.canvas.resetTransform()
    window.canvas.scale(8, 8)
    window.canvas.centerOn(QPointF(110, 65))
    window.set_eraser_active(True)
    window.eraser_size_preset.setCurrentIndex(0)  # 1 × 1 px
    # Right half of the source pixel (10, 5): the old rounding erased its neighbour (11, 5).
    target = QPointF(100 + 10.7, 60 + 5.5)
    mouse_drag(window, target, target, steps=1)
    layer = window.document.layer(layer_id)
    assert layer.eraser_strokes and layer.eraser_strokes[0]["pixel_centered"]
    alpha = render_layer_with_mask(layer, window.document).getchannel("A")
    assert alpha.getpixel((10, 5)) == 0
    assert alpha.getpixel((11, 5)) == 255 and alpha.getpixel((9, 5)) == 255


def test_ctrl_dragging_the_selection_moves_its_pixels_to_a_new_layer(image_layer):
    window, layer_id = image_layer
    window.set_selection_tool("rect")  # Ctrl+drag belongs to the selection tools
    window.set_selection(selection.rectangle((400, 300), (100, 60, 110, 70), False), "Sélection")
    mouse_drag(window, QPointF(105, 65), QPointF(125, 65), modifiers=Qt.KeyboardModifier.ControlModifier)
    assert len(window.document.layers) == 2
    moved = window.document.layers[-1]
    assert (moved.x, moved.y) == pytest.approx((120, 60), abs=1)
    window.undo_stack.undo()  # one step: the new layer and the moved selection
    assert len(window.document.layers) == 1


def wheel(window, delta: QPoint):
    viewport = window.canvas.viewport()
    centre = QPointF(viewport.rect().center())
    event = QWheelEvent(centre, QPointF(viewport.mapToGlobal(centre)), QPoint(0, 0), delta, NO_BUTTON,
                        NO_MODIFIER, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(viewport, event)


def test_the_wheel_zooms_in_proportion_and_a_horizontal_wheel_does_not_zoom(image_layer):
    window, _layer_id = image_layer
    zoom = window.canvas.transform().m11()
    wheel(window, QPoint(120, 0))  # tilted wheel or Shift+wheel
    assert window.canvas.transform().m11() == pytest.approx(zoom)
    wheel(window, QPoint(0, 15))  # an eighth of a notch (touchpad, fine wheel)
    assert window.canvas.transform().m11() == pytest.approx(zoom * 1.15 ** (1 / 8))
    wheel(window, QPoint(0, -15))
    assert window.canvas.transform().m11() == pytest.approx(zoom)


def test_a_drawn_rectangle_selection_follows_the_mouse(image_layer):
    window, _layer_id = image_layer
    window.set_selection_tool("rect")
    mouse_drag(window, QPointF(100, 60), QPointF(120, 70))
    assert selection.bounds(window.selection_mask) == (100, 60, 120, 70)
    assert window.undo_stack.count() == 1 and not window.is_modified()


@pytest.fixture
def two_checked_layers(image_layer):
    window, layer_id = image_layer
    other = window.document.clone()
    second = other.add_image_bytes(png_bytes(40, 20, (0, 0, 200, 255)), "autre", center=False)
    second.x, second.y = 200.0, 60.0
    window.install_document(other, layer_id)
    window.undo_stack.clear()
    window.set_checked_layers([layer_id, second.id])
    window.select_layer(layer_id)
    return window, layer_id, second.id


def test_clicking_a_checked_layer_without_moving_records_nothing(two_checked_layers):
    window, layer_id, _other = two_checked_layers
    mouse_drag(window, QPointF(120, 70), QPointF(120, 70), steps=1)
    assert window.undo_stack.count() == 0
    assert not window.is_modified()


def test_dragging_checked_layers_moves_them_in_one_step(two_checked_layers):
    window, layer_id, other = two_checked_layers
    mouse_drag(window, QPointF(120, 70), QPointF(150, 90))
    assert window.undo_stack.count() == 1
    assert window.undo_stack.text(0) == "Déplacer 2 calques"
    assert window.document.layer(layer_id).x == pytest.approx(130, abs=1)
    assert window.document.layer(other).x == pytest.approx(230, abs=1)
