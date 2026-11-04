"""The live eraser preview shows exactly what the saved stroke renders."""
import pytest
from conftest import png_bytes
from PySide6.QtCore import QPointF

from app.graphics import eraser_dab_origin, eraser_source_position
from app.model import Document


def _alpha(item):
    image = item.pixmap().toImage()
    return [[image.pixelColor(x, y).alpha() for x in range(image.width())] for y in range(image.height())]


def _stroke(window, flips, points, *, size, pixel_art, hardness, opacity=100):
    document = Document(48, 40)
    layer = document.add_image_bytes(png_bytes(30, 22, (200, 120, 40, 255)), "Calque", center=False)
    layer.x, layer.y = 4, 6
    layer.flip_horizontal, layer.flip_vertical = flips
    window.install_document(document, layer.id)
    window.eraser_size.setValue(size)
    window.eraser_pixel_art.setChecked(pixel_art)
    window.eraser_hardness.setValue(hardness)
    window.eraser_opacity.setValue(opacity)
    item = window.canvas.graphic_for(layer.id)
    canvas = window.canvas
    assert canvas.begin_eraser_preview(item, layer)
    canvas._apply_eraser_preview_segment(points[0], points[0])
    for start, end in zip(points, points[1:]):
        canvas._apply_eraser_preview_segment(start, end)
    preview = _alpha(item)
    canvas.cancel_eraser_preview()
    window.commit_eraser_stroke(layer.id, points)
    return preview, _alpha(window.canvas.graphic_for(layer.id))


@pytest.mark.parametrize("flips", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("size", [1, 2, 3, 4])
@pytest.mark.parametrize("position", [4.0, 4.5, 7.25])
def test_pixel_art_preview_matches_the_saved_stroke(window, flips, size, position):
    points = [QPointF(position, position), QPointF(position + 9, position + 3)]
    preview, final = _stroke(window, flips, points, size=size, pixel_art=True, hardness=100)
    assert preview == final


@pytest.mark.parametrize("flips", [(False, False), (True, True)])
@pytest.mark.parametrize("hardness, opacity", [(0, 100), (50, 100), (100, 40)])
def test_soft_preview_matches_the_saved_stroke(window, flips, hardness, opacity):
    points = [QPointF(5.3, 8.1), QPointF(20.7, 12.4), QPointF(26.0, 4.0)]
    preview, final = _stroke(window, flips, points, size=12, pixel_art=False, hardness=hardness, opacity=opacity)
    worst = max(abs(a - b) for row_a, row_b in zip(preview, final) for a, b in zip(row_a, row_b))
    assert worst <= 1


@pytest.mark.parametrize("size", [1, 2, 3, 5])
@pytest.mark.parametrize("position", [0.0, 3.0, 3.5, 6.999])
def test_mirrored_dab_covers_the_mirrored_pixels(size, position):
    extent = 20
    shown = eraser_dab_origin(position, size)
    source = eraser_dab_origin(eraser_source_position(position, extent, size, True), size)
    assert source == extent - shown - size
