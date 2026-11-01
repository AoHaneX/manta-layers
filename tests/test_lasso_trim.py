"""Free and polygonal lassos, and cropping of transparent margins."""
import io

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app import selection as S
from app.graphics import render_layers
from app.model import Document


def png_with_margins(size=(30, 20), box=(5, 4, 14, 11), color=(200, 40, 40, 255)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box, fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# --- Selection engine -------------------------------------------------------------------


def test_pixel_perfect_polygon_is_hard_edged_and_needs_three_points():
    mask = S.polygon((20, 20), [(2, 2), (12, 2), (12, 12), (2, 12)])
    assert S.bounds(mask) == (2, 2, 12, 12) and set(mask.tobytes()) == {0, 255}
    assert S.is_empty(S.polygon((20, 20), [(1, 1), (5, 5)]))
    assert S.is_empty(S.polygon((20, 20), [(1, 1), (5, 5), (5, 5), (1, 1)]))


def test_antialiased_polygon_has_soft_edges_and_stays_in_the_document():
    mask = S.polygon((20, 20), [(-5, -5), (15.5, 2), (3, 30)], antialias=True)
    assert mask.size == (20, 20)
    assert any(0 < value < 255 for value in mask.tobytes())


# --- Canvas lassos ----------------------------------------------------------------------


@pytest.fixture
def image_window(window):
    document = Document(60, 40)
    layer = document.add_image_bytes(png_with_margins((60, 40), (0, 0, 59, 39)), "Fond", center=False)
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    return window, layer.id


def test_polygonal_lasso_selects_closes_and_can_be_undone(image_window):
    window, _layer_id = image_window
    window.set_selection_tool("polygon")
    canvas = window.canvas
    canvas.lasso_points = [QPointF(10, 10), QPointF(30, 10), QPointF(30, 30)]
    canvas.lasso_modifiers = Qt.KeyboardModifier.NoModifier
    canvas.finish_lasso()
    assert S.bounds(window.selection_mask) == (10, 10, 30, 30)
    assert canvas.lasso_points is None
    window.undo_stack.undo()
    assert window.selection_mask is None


def test_lasso_in_progress_is_cancelled_with_escape_and_shortened_with_backspace(image_window):
    window, _layer_id = image_window
    window.set_selection_tool("polygon")
    canvas = window.canvas
    canvas.setFocus()
    canvas.lasso_points = [QPointF(1, 1), QPointF(20, 1), QPointF(20, 20)]
    QTest.keyClick(canvas, Qt.Key.Key_Backspace)
    assert len(canvas.lasso_points) == 2
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.lasso_points is None and window.selection_mask is None
    assert len(window.document.layers) == 1  # Backspace did not delete the layer


def test_free_lasso_click_without_outline_selects_nothing(image_window):
    window, _layer_id = image_window
    window.set_selection_tool("lasso")
    viewport = window.canvas.viewport()
    point = window.canvas.mapFromScene(QPointF(20, 20))
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window.selection_mask is None and window.canvas.lasso_points is None


def test_lasso_selection_combines_and_its_pixels_can_be_hidden(image_window):
    window, layer_id = image_window
    window.apply_selection_polygon([(0, 0), (20, 0), (20, 20), (0, 20)], Qt.KeyboardModifier.NoModifier)
    window.apply_selection_polygon([(30, 0), (40, 0), (40, 10), (30, 10)], Qt.KeyboardModifier.ShiftModifier)
    assert S.bounds(window.selection_mask) == (0, 0, 40, 20)
    window.clear_selection_content()
    rendered = render_layers(window.document, [layer_id])
    assert rendered.getpixel((5, 5))[3] == 0 and rendered.getpixel((25, 5))[3] == 255
    assert rendered.getpixel((35, 5))[3] == 0
