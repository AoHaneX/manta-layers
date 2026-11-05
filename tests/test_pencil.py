"""Pencil: strokes in the current colour, with the eraser's sizes, kept non-destructive."""
import pytest
from conftest import png_bytes
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_canvas_mouse import image_layer, mouse_drag  # noqa: F401  (fixture)

from app.graphics import apply_eraser_strokes, crop_image_layer, render_layer_with_mask
from app.model import Document, Layer
from app.storage import open_project, save_project

RED = (200, 10, 10, 255)


def stroke(points, color="#3366FF", **settings):
    base = {"points": points, "size": 1, "shape": "square", "pixel_art": True, "hardness": 100,
            "opacity": 100, "pixel_centered": True}
    return {**base, **settings, "tool": "pencil", "color": color} if color else {**base, **settings}


def test_pencil_button_sits_under_fill_plus_and_shares_the_eraser_settings(window):
    layout = window.paint_global_btn.parentWidget().layout()
    assert layout.indexOf(window.pencil_btn) == layout.indexOf(window.paint_global_btn) + 1
    window.set_eraser_active(True)
    window.pencil_btn.click()
    assert window.pencil_active and not window.eraser_active
    assert window.eraser_settings.isVisibleTo(window.tools_tab)
    assert window.color_editor.isVisibleTo(window.tools_tab)  # the colour it draws with
    assert window.pencil_btn.isChecked() and window.pencil_action.isChecked()
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_B)
    assert not window.pencil_active and not window.eraser_settings.isVisibleTo(window.tools_tab)


def test_a_pencil_click_paints_the_pixel_under_the_pointer_without_rewriting_the_image(image_layer):  # noqa: F811
    window, layer_id = image_layer
    source = window.document.assets[window.document.layer(layer_id).asset]
    window.canvas.resetTransform()
    window.canvas.scale(8, 8)
    window.canvas.centerOn(QPointF(110, 65))
    window.set_current_color("#3366FF")
    window.set_pencil_active(True)
    window.eraser_size_preset.setCurrentIndex(1)  # 2 × 2 px, a size of the eraser
    target = QPointF(100 + 10.5, 60 + 5.5)
    mouse_drag(window, target, target, steps=1)
    layer = window.document.layer(layer_id)
    assert window.document.assets[layer.asset] == source
    assert layer.eraser_strokes[-1]["tool"] == "pencil" and layer.eraser_strokes[-1]["size"] == 2
    pixels = render_layer_with_mask(layer, window.document)
    painted = [(x, y) for y in range(20) for x in range(40) if pixels.getpixel((x, y)) == (0x33, 0x66, 0xFF, 255)]
    assert len(painted) == 4 and (10, 5) in painted
    assert window.undo_stack.undoText() == "Trait de crayon"
    window.undo_stack.undo()
    assert window.document.layer(layer_id).eraser_strokes == []


@pytest.mark.parametrize("hardness, opacity", [(100, 100), (100, 40), (30, 100)])
def test_pencil_preview_matches_the_saved_stroke(window, hardness, opacity):
    document = Document(48, 40)
    layer = document.add_image_bytes(png_bytes(30, 22, (200, 120, 40, 255)), "Calque", center=False)
    layer.flip_horizontal = True
    window.install_document(document, layer.id)
    window.set_current_color("#22AA66")
    window.set_pencil_active(True)
    window.eraser_size.setValue(6)
    window.eraser_pixel_art.setChecked(hardness == 100)
    window.eraser_hardness.setValue(hardness)
    window.eraser_opacity.setValue(opacity)
    item, canvas = window.canvas.graphic_for(layer.id), window.canvas
    points = [QPointF(5.3, 8.1), QPointF(20.7, 12.4)]
    assert canvas.begin_eraser_preview(item, layer)
    canvas._apply_eraser_preview_segment(points[0], points[0])
    canvas._apply_eraser_preview_segment(points[0], points[1])
    preview = item.pixmap().toImage()
    canvas.cancel_eraser_preview()
    window.commit_eraser_stroke(layer.id, points)
    final = window.canvas.graphic_for(layer.id).pixmap().toImage()
    worst = max(abs(preview.pixelColor(x, y).getRgb()[c] - final.pixelColor(x, y).getRgb()[c])
                for x in range(30) for y in range(22) for c in range(4))
    assert worst <= 1


def test_pencil_and_eraser_replay_in_the_order_they_were_drawn():
    image = Image.new("RGBA", (6, 3), RED)
    paint, erase = stroke([[2, 1]]), stroke([[2, 1]], color=None)
    assert apply_eraser_strokes(image, [paint, erase]).getpixel((2, 1))[3] == 0
    assert apply_eraser_strokes(image, [erase, paint]).getpixel((2, 1)) == (0x33, 0x66, 0xFF, 255)


def test_a_soft_pencil_on_transparent_pixels_takes_the_pencil_colour():
    image = Image.new("RGBA", (6, 3), (0, 0, 0, 0))
    result = apply_eraser_strokes(image, [stroke([[2, 1]], opacity=50)])
    assert result.getpixel((2, 1)) == (0x33, 0x66, 0xFF, 128)
    assert result.getpixel((4, 1)) == (0, 0, 0, 0)


def test_pencil_strokes_survive_save_and_reopen_and_bad_colours_are_dropped(tmp_path):
    document = Document(20, 20)
    layer = document.add_image_bytes(png_bytes(6, 6, RED), "Calque", center=False)
    layer.eraser_strokes = [stroke([[1, 1]], color="#abcdef"), stroke([[2, 2]], color="bleu")]
    path = tmp_path / "crayon.manta"
    save_project(document, path)
    reopened = open_project(path).layer(layer.id)
    assert reopened.eraser_strokes == [stroke([[1.0, 1.0]], color="#ABCDEF")]
    assert Layer.from_dict({"name": "x", "eraser_strokes": [stroke([[1, 1]], color=None)]}).eraser_strokes[0].get(
        "tool") is None  # an eraser stroke stays an eraser stroke


def test_trimming_a_layer_keeps_its_pencil_strokes_in_place():
    document = Document(40, 40)
    layer = document.add_image_bytes(png_bytes(20, 20, (0, 0, 0, 0)), "Calque", center=False)
    layer.eraser_strokes = [stroke([[12, 9]], size=2)]
    trimmed, assets = crop_image_layer(layer, document, (10, 8, 16, 12))
    probe = Document(40, 40, None, [trimmed], {**document.assets, **assets})
    pixels = render_layer_with_mask(trimmed, probe)
    assert pixels.getpixel((2, 1)) == (0x33, 0x66, 0xFF, 255)
