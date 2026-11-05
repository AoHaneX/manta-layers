"""Magic wand on the source pixels of one layer: finer than the document grid, and outside the frame."""
import io

import pytest

pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app import selection as S  # noqa: E402
from app.graphics import layer_transform, render_layer_with_mask, render_layers  # noqa: E402
from app.model import Document  # noqa: E402

GREEN, BLACK = (40, 200, 120, 255), (0, 0, 0, 255)


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def thin_line_document():
    """A 40×8 green layer scaled to 85 %, with a black column the document grid skips."""
    document = Document(60, 30)
    for column in range(40):
        image = Image.new("RGBA", (40, 8), GREEN)
        image.paste(BLACK, (column, 0, column + 1, 8))
        layer = document.add_image_bytes(png(image), "Corail", center=False)
        layer.x, layer.y, layer.sx, layer.sy = 2.0, 3.0, 0.85, 0.85
        shown = render_layers(document, [layer.id])
        if not any(pixel[:3] == (0, 0, 0) and pixel[3] for pixel in shown.get_flattened_data()):
            return document, layer.id, column
        document.layers.remove(layer)
    raise AssertionError("no column hidden by the downscale")


def click(window, point: QPointF, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, modifier,
                     window.canvas.mapFromScene(point))


@pytest.fixture
def thin_line(window):
    document, layer_id, column = thin_line_document()
    window.install_document(document, layer_id)
    window.undo_stack.clear()
    window.canvas.resetTransform()
    window.canvas.scale(8, 8)
    window.set_selection_tool("wand")
    window.wand_tolerance.setValue(0)
    return window, layer_id, column


def source_point(window, layer_id, x, y):
    return layer_transform(window.document.layer(layer_id)).map(QPointF(x + 0.5, y + 0.5))


def test_wand_selects_a_source_line_thinner_than_a_document_pixel(thin_line):
    window, layer_id, column = thin_line
    click(window, source_point(window, layer_id, column, 4))
    assert window.selection_mask is not None
    exact = window._exact_selection(window.document.layer(layer_id))
    assert exact is not None and exact.getbbox() == (column, 0, column + 1, 8)
    assert window.canvas.selection_path is not None and not window.canvas.selection_path.isEmpty()
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    alpha = render_layer_with_mask(window.document.layer(layer_id), window.document).getchannel("A")
    assert alpha.getpixel((column, 4)) == 0
    assert all(alpha.getpixel((x, 4)) == 255 for x in range(40) if x != column)
    window.undo_stack.undo()
    assert window.document.layer(layer_id).mask is None


def test_exact_selection_survives_undo_redo_and_combines_with_shift(thin_line):
    window, layer_id, column = thin_line
    click(window, source_point(window, layer_id, column, 4))
    window.wand_contiguous.setChecked(False)  # every green pixel, on both sides of the line
    other = 0 if column > 3 else 39
    click(window, source_point(window, layer_id, other, 4), Qt.KeyboardModifier.ShiftModifier)
    layer = window.document.layer(layer_id)
    exact = window._exact_selection(layer)
    # Shift adds the green pixels to the black line: the whole layer.
    assert exact is not None and exact.getbbox() == (0, 0, 40, 8)
    window.undo_stack.undo()
    assert window._exact_selection(layer).getbbox() == (column, 0, column + 1, 8)
    window.undo_stack.undo()
    assert window.selection_mask is None and window.selection_layer is None
    window.undo_stack.redo()
    assert window._exact_selection(layer).getbbox() == (column, 0, column + 1, 8)


def test_exact_selection_is_ignored_once_the_layer_moved(thin_line):
    window, layer_id, column = thin_line
    click(window, source_point(window, layer_id, column, 4))
    window.mutate("Déplacer", lambda doc: setattr(doc.layer(layer_id), "x", 10.0), layer_id)
    assert window._exact_selection(window.document.layer(layer_id)) is None


def test_separating_an_exact_selection_keeps_the_layer_scale_and_pixels(thin_line):
    window, layer_id, column = thin_line
    click(window, source_point(window, layer_id, column, 4))
    assert window.selection_to_new_layer(cut=True)
    source = window.document.layer(layer_id)
    new = window.document.layer(window.selected_id)
    assert new.id != layer_id and (new.sx, new.sy) == (source.sx, source.sy)
    pixels = render_layer_with_mask(new, window.document)
    assert pixels.size == (1, 8) and pixels.getpixel((0, 4)) == BLACK
    # Same place on the canvas as the column it came from.
    assert layer_transform(new).map(QPointF(0, 0)) == layer_transform(source).map(QPointF(column, 0))
    assert render_layer_with_mask(source, window.document).getpixel((column, 4))[3] == 0


def test_wand_selects_and_deletes_pixels_outside_the_frame(window):
    image = Image.new("RGBA", (60, 30), (220, 20, 20, 255))
    image.paste((20, 20, 220, 255), (30, 0, 60, 30))
    document = Document(100, 60)
    layer = document.add_image_bytes(png(image), "Débord", center=False)
    layer.x, layer.y = -30.0, 10.0  # the red half is left of the frame
    window.install_document(document, layer.id)
    window.set_selection_tool("wand")
    click(window, QPointF(-10, 20))
    assert window.selection_mask is not None and S.is_empty(window.selection_mask)
    assert window._exact_selection(window.document.layer(layer.id)).getbbox() == (0, 0, 30, 30)
    window.clear_selection_content()
    alpha = render_layer_with_mask(window.document.layer(layer.id), window.document).getchannel("A")
    assert alpha.getpixel((5, 5)) == 0 and alpha.getpixel((45, 5)) == 255


def test_wand_on_all_layers_still_needs_a_click_inside_the_document(window):
    document = Document(50, 50)
    layer = document.add_image_bytes(png(Image.new("RGBA", (10, 10), GREEN)), "x", center=False)
    window.install_document(document, layer.id)
    window.set_selection_tool("wand")
    window.wand_all_layers.setChecked(True)
    click(window, QPointF(-5, -5))
    assert window.selection_mask is None
    assert "Échantillonner tous les calques" in window.statusBar().currentMessage()
