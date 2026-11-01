"""Free and polygonal lassos, and cropping of transparent margins."""
import io

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from app import selection as S
from app.graphics import render_layers
from app.imaging import alpha_bounds, trim_transparent
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


# --- Transparent margins ------------------------------------------------------------------


def test_trim_helpers_find_visible_pixels_and_handle_empty_images():
    image = Image.open(io.BytesIO(png_with_margins()))
    assert alpha_bounds(image) == (5, 4, 15, 12)
    cropped, box = trim_transparent(image)
    assert cropped.size == (10, 8) and box == (5, 4, 15, 12)
    assert trim_transparent(Image.new("RGBA", (4, 4))) is None


@pytest.mark.parametrize("transform", [
    {}, {"sx": 2.0, "sy": 0.5}, {"rotation": 33.0}, {"flip_horizontal": True, "flip_vertical": True, "rotation": -20.0},
])
def test_trimmed_layer_keeps_its_look_on_the_canvas(window, transform):
    document = Document(120, 100)
    layer = document.add_image_bytes(png_with_margins(), "Sprite", center=False)
    layer.x, layer.y = 40, 30
    for key, value in transform.items():
        setattr(layer, key, value)
    layer.eraser_strokes.append({"points": [[7, 6]], "size": 2, "shape": "square", "pixel_art": True,
                                 "hardness": 100, "opacity": 100})
    window.install_document(document, layer.id)
    before = render_layers(window.document)
    assert window.trim_layer_margins(layer.id)
    trimmed = window.document.layer(layer.id)
    with Image.open(io.BytesIO(window.document.assets[trimmed.asset])) as source:
        assert source.size == (11, 8)  # left margin 5 becomes 4: strokes need an even shift

    after = render_layers(window.document)
    old, new = before.tobytes(), after.tobytes()
    difference = sum(1 for index in range(0, len(old), 4) if old[index:index + 4] != new[index:index + 4])
    assert difference <= 4  # identical up to a few rotated edge pixels
    window.undo_stack.undo()
    assert window.document.layer(layer.id).asset == layer.asset


def test_trim_refuses_empty_full_text_and_locked_layers(window):
    document = Document(50, 50)
    empty = document.add_image_bytes(png_with_margins(color=(0, 0, 0, 0)), "Vide")
    full = document.add_image_bytes(png_with_margins((10, 10), (0, 0, 9, 9)), "Plein")
    text = document.add_text("Texte")
    locked = document.add_image_bytes(png_with_margins(), "Verrou")
    locked.locked = True
    window.install_document(document, None)
    for layer in (empty, full, text, locked):
        assert not window.trim_layer_margins(layer.id)
    assert window.undo_stack.count() == 0


def test_document_crop_to_content_keeps_the_image_and_is_undoable(window):
    document = Document(100, 80)
    layer = document.add_image_bytes(png_with_margins(), "Sprite", center=False)
    layer.x, layer.y = 20, 10
    window.install_document(document, layer.id)
    window.select_all()
    before = render_layers(window.document).crop((25, 14, 35, 22))
    assert window.crop_document_to_content()
    assert (window.document.width, window.document.height) == (10, 8)
    assert render_layers(window.document).tobytes() == before.tobytes()
    assert window.selection_mask is None
    window.undo_stack.undo()
    assert (window.document.width, window.document.height) == (100, 80)
    assert window.selection_mask is not None  # one undo step restores the selection too
