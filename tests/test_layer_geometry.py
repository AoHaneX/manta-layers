"""The canvas item and layer_transform agree: a rotated layer with sx != sy stays a rectangle."""
import io
import math

import pytest
from conftest import png_bytes
from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF, QRectF, Qt

from app.graphics import create_graphic, layer_transform, qimage_to_pil, render_document
from app.model import Document, Layer

GEOMETRIES = [(0, 1, 1), (35, 2.0, 0.5), (-120, 0.4, 3.0), (270, 1.7, 1.7), (12.5, 0.05, 50)]


def _layers(document):
    image = document.add_image_bytes(png_bytes(60, 40), "Image", center=False)
    text = document.add_text("Bonjour")
    shape = Layer(kind="shape", shape_type="speech", fill_color="#FFFFFF")
    document.layers.append(shape)
    return [image, text, shape]


@pytest.mark.parametrize("rotation, sx, sy", GEOMETRIES)
def test_the_scene_item_uses_the_layer_transform(qapp, rotation, sx, sy):
    document = Document(400, 300)
    for layer in _layers(document):
        layer.x, layer.y, layer.rotation, layer.sx, layer.sy = 100, 50, rotation, sx, sy
        item = create_graphic(layer, document)
        expected = layer_transform(layer)
        for point in (QPointF(0, 0), QPointF(60, 0), QPointF(0, 40), QPointF(17, 23)):
            mapped, wanted = item.sceneTransform().map(point), expected.map(point)
            assert (mapped.x(), mapped.y()) == pytest.approx((wanted.x(), wanted.y()), abs=1e-6), layer.kind


def test_a_rotated_non_uniform_layer_is_rendered_with_right_angles(qapp):
    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(60, 40), "Image", center=False)
    layer.x, layer.y, layer.rotation, layer.sx, layer.sy = 150, 100, 35, 2.0, 0.5
    transform = layer_transform(layer)
    origin, right, down = (transform.map(QPointF(*point)) for point in ((0, 0), (60, 0), (0, 40)))
    edge_a, edge_b = right - origin, down - origin
    cosine = (edge_a.x() * edge_b.x() + edge_a.y() * edge_b.y()) / (math.hypot(edge_a.x(), edge_a.y())
                                                                     * math.hypot(edge_b.x(), edge_b.y()))
    assert cosine == pytest.approx(0, abs=1e-9)
    # The rendered red pixels cover the rotated rectangle, whose area is 60·2 × 40·0.5.
    rendered = qimage_to_pil(render_document(document))
    covered = rendered.getchannel("A").point(lambda alpha: 255 if alpha > 127 else 0).histogram()[255]
    assert covered == pytest.approx(120 * 20, rel=0.05)


def test_clearing_a_selection_hides_the_selected_pixels_of_a_rotated_stretched_layer(window):
    document = Document(400, 300)
    source = Image.new("RGBA", (60, 40), (40, 160, 220, 255))
    ImageDraw.Draw(source).rectangle((20, 10, 40, 30), fill=(220, 40, 40, 255))
    output = io.BytesIO()
    source.save(output, format="PNG")
    layer = document.add_image_bytes(output.getvalue(), "Image", center=False)
    layer.x, layer.y, layer.rotation, layer.sx, layer.sy = 150, 100, 30, 1.6, 0.8
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    before = qimage_to_pil(render_document(window.document))
    area = QRectF(170, 110, 30, 25)
    window.apply_selection_shape("rect", area, Qt.KeyboardModifier.NoModifier)
    window.clear_selection_content()
    after = qimage_to_pil(render_document(window.document))
    inside = [(x, y) for x in range(171, 199) for y in range(111, 134) if before.getpixel((x, y))[3]]
    assert inside
    still_visible = [point for point in inside if after.getpixel(point)[3]]
    assert len(still_visible) <= len(inside) * 0.02  # only resampled border pixels may remain
    outside = [(x, y) for x in range(400) for y in range(300)
               if not (168 <= x < 202 and 108 <= y < 137) and before.getpixel((x, y)) != after.getpixel((x, y))]
    assert outside == []


def test_resizing_a_rotated_stretched_layer_keeps_the_opposite_corner(window):
    from test_canvas_mouse import mouse_drag

    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(40, 20), "Image", center=False)
    layer.x, layer.y, layer.rotation, layer.sx, layer.sy = 150, 100, 30, 1.6, 0.8
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    window.snap_enabled = False
    canvas = window.canvas
    canvas.resetTransform()
    canvas.scale(2, 2)
    canvas.centerOn(QPointF(180, 120))
    item = canvas.graphic_for(layer.id)
    handles = canvas.local_handles(item)
    fixed_before = item.mapToScene(handles[0])
    corner = item.mapToScene(handles[2])
    mouse_drag(window, corner, corner + QPointF(20, 12))
    resized = window.document.layer(layer.id)
    assert (resized.sx, resized.sy) != pytest.approx((1.6, 0.8), abs=0.01)
    assert resized.rotation == pytest.approx(30)
    item = canvas.graphic_for(layer.id)
    fixed_after = item.mapToScene(canvas.local_handles(item)[0])
    assert (fixed_after.x(), fixed_after.y()) == pytest.approx((fixed_before.x(), fixed_before.y()), abs=0.5)
    model_corner = layer_transform(resized).map(canvas.local_handles(item)[0])
    assert (model_corner.x(), model_corner.y()) == pytest.approx((fixed_after.x(), fixed_after.y()), abs=1e-6)


def test_rotating_a_stretched_layer_keeps_its_scale(window):
    from test_canvas_mouse import mouse_drag

    document = Document(400, 300)
    layer = document.add_image_bytes(png_bytes(40, 20), "Image", center=False)
    layer.x, layer.y, layer.sx, layer.sy = 150, 100, 2.0, 0.5
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    canvas = window.canvas
    canvas.resetTransform()
    canvas.scale(2, 2)
    canvas.centerOn(QPointF(190, 105))
    item = canvas.graphic_for(layer.id)
    handle = canvas.rotation_point(item)
    centre = item.mapToScene(item.boundingRect().center())
    distance = centre.y() - handle.y()
    mouse_drag(window, handle, centre + QPointF(distance, 0), steps=8)
    turned = window.document.layer(layer.id)
    assert turned.rotation == pytest.approx(90, abs=2)
    assert (turned.sx, turned.sy) == pytest.approx((2.0, 0.5))
    centre_after = canvas.graphic_for(layer.id).mapToScene(item.boundingRect().center())
    assert (centre_after.x(), centre_after.y()) == pytest.approx((centre.x(), centre.y()), abs=0.5)
