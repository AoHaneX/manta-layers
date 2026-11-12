"""Layer opacity: a slider under the layer list, a live preview, one history step per gesture."""
import io
import json
import time
import zipfile

import pytest

pytest.importorskip("PySide6")

from conftest import png_bytes  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QAbstractSlider  # noqa: E402

from app import export, graphics  # noqa: E402
from app.graphics import qimage_to_pil, render_document, render_layers  # noqa: E402
from app.model import Document, Layer  # noqa: E402
from app.storage import open_project, save_project  # noqa: E402

RED = (220, 20, 20, 255)
BLUE = (20, 60, 220, 255)
HALF_GREEN = (30, 200, 60, 128)


def jpeg_bytes(width, height, color):
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="JPEG", quality=95)
    return output.getvalue()


@pytest.fixture
def two_layers(window):
    """60 × 40 document: an opaque red background and a half transparent green square on it."""
    document = Document(60, 40)
    base = document.add_image_bytes(png_bytes(60, 40, RED), "Fond", center=False)
    top = document.add_image_bytes(png_bytes(20, 20, HALF_GREEN), "Carré", center=False)
    top.x, top.y = 10, 10
    window.install_document(document, top.id)
    window.undo_stack.clear()
    window.undo_stack.setClean()
    return window, base.id, top.id


def drag(control, values):
    """A slider drag: previews only, then one value when the button is released."""
    control.slider.setSliderDown(True)
    for value in values:
        control.slider.setValue(value)
    control.slider.setSliderDown(False)  # emits sliderReleased


def alpha_at(document, layer_id, point):
    return render_layers(document, [layer_id]).getpixel(point)[3]


# --- The control -----------------------------------------------------------------

def test_the_control_sits_under_the_layer_list_and_new_layers_start_at_100(window):
    control = window.opacity_control
    layers_tab = window.tabs.widget(0)
    layout = layers_tab.layout()
    assert layout.indexOf(window.layer_list) == 0 and layout.indexOf(control) == 1
    assert (control.slider.minimum(), control.slider.maximum()) == (0, 100)
    assert (control.spin.minimum(), control.spin.maximum(), control.spin.suffix()) == (0, 100, " %")
    assert "opacity" not in window.inputs  # one control only
    assert Layer().opacity == 1.0
    document = Document(50, 50)
    layer = document.add_image_bytes(png_bytes(5, 5), "x")
    window.install_document(document, layer.id)
    assert control.value() == 100 and control.spin.value() == 100 and control.isEnabled()


def test_each_layer_keeps_its_own_opacity_and_the_control_follows_the_selection(two_layers):
    window, base, top = two_layers
    drag(window.opacity_control, [80, 30])
    window.select_layer(base)
    assert window.opacity_control.value() == 100
    window.select_layer(top)
    assert window.opacity_control.value() == 30 and window.opacity_control.spin.value() == 30
    assert window.document.layer(base).opacity == 1.0 and window.document.layer(top).opacity == 0.3


def test_the_control_is_disabled_without_an_editable_layer(two_layers):
    window, base, _top = two_layers
    window.select_layer(None)
    assert not window.opacity_control.isEnabled()
    window.toggle_lock(base)
    window.select_layer(base)
    assert not window.opacity_control.isEnabled()


# --- Preview and history ---------------------------------------------------------------

def test_a_drag_previews_at_once_and_records_one_step(two_layers, monkeypatch):
    window, _base, top = two_layers
    item = window.canvas.graphic_for(top)

    def no_render(*_args, **_kwargs):
        raise AssertionError("the preview must not render the image again")

    monkeypatch.setattr(graphics, "render_layer_with_mask", no_render)
    control = window.opacity_control
    control.slider.setSliderDown(True)
    for value in (90, 70, 50, 40):
        control.slider.setValue(value)
        assert item.opacity() == pytest.approx(value / 100)  # immediate, on the canvas item
        assert control.spin.value() == value
    assert window.undo_stack.count() == 0 and window.document.layer(top).opacity == 1.0
    monkeypatch.undo()
    control.slider.setSliderDown(False)
    assert window.undo_stack.count() == 1 and window.undo_stack.undoText() == "Opacité"
    assert window.document.layer(top).opacity == 0.4


def test_keyboard_steps_in_a_row_are_one_history_entry(two_layers):
    window, _base, top = two_layers
    slider = window.opacity_control.slider
    for _ in range(5):
        slider.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
    assert window.document.layer(top).opacity == 0.95 and window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert window.document.layer(top).opacity == 1.0 and window.opacity_control.value() == 100


def test_undo_and_redo_restore_the_opacity_and_the_control(two_layers):
    window, _base, top = two_layers
    window.opacity_control.spin.setValue(25)
    assert window.document.layer(top).opacity == 0.25
    window.undo_stack.undo()
    assert window.document.layer(top).opacity == 1.0 and window.opacity_control.value() == 100
    assert window.canvas.graphic_for(top).opacity() == 1.0
    window.undo_stack.redo()
    assert window.document.layer(top).opacity == 0.25 and window.opacity_control.value() == 25


def test_a_value_being_typed_is_kept_on_save(two_layers, tmp_path):
    window, _base, top = two_layers
    spin = window.opacity_control.spin
    spin.setFocus()
    spin.lineEdit().setText("35 %")
    window.project_path = tmp_path / "projet.manta"
    assert window.save_document()
    assert open_project(tmp_path / "projet.manta").layer(top).opacity == 0.35


# --- Rendering -----------------------------------------------------------------------

def test_zero_hides_the_layer_without_touching_its_pixels(two_layers):
    window, _base, top = two_layers
    original = render_layers(window.document, [top])
    asset = window.document.assets[window.document.layer(top).asset]
    window.opacity_control.spin.setValue(0)
    assert render_layers(window.document, [top]).getchannel("A").getextrema() == (0, 0)
    assert window.document.assets[window.document.layer(top).asset] == asset
    window.opacity_control.spin.setValue(100)
    assert render_layers(window.document, [top]).tobytes() == original.tobytes()


def test_pixel_alpha_and_layer_opacity_multiply_with_normal_compositing(two_layers):
    window, base, top = two_layers
    window.opacity_control.spin.setValue(50)
    document = window.document
    assert alpha_at(document, top, (15, 15)) == pytest.approx(64, abs=1)  # 50 % of a 50 % pixel
    # Over the opaque red: green weighs 25 %, red 75 % ("over" compositing, not an RGB shift).
    pixel = render_layers(document).getpixel((15, 15))
    expected = [round(0.25 * g + 0.75 * r) for g, r in zip(HALF_GREEN[:3], RED[:3])]
    assert pixel[3] == 255 and all(abs(a - b) <= 2 for a, b in zip(pixel[:3], expected))


@pytest.mark.parametrize("kind", ["png", "jpeg", "text", "shape"])
def test_every_kind_of_layer_takes_its_opacity(window, kind):
    document = Document(80, 60)
    if kind == "png":
        layer = document.add_image_bytes(png_bytes(40, 30, BLUE), "PNG", center=False)
    elif kind == "jpeg":
        layer = document.add_image_bytes(jpeg_bytes(40, 30, BLUE[:3]), "JPEG", center=False)
    elif kind == "text":
        layer = document.add_text("Manta")
        layer.x, layer.y, layer.font_size = 2, 2, 40
    else:
        layer = Layer(kind="shape", name="Forme", fill_color="#1438DC", shape_width=40, shape_height=30)
        document.layers.append(layer)
    window.install_document(document, layer.id)
    full = render_layers(window.document, [layer.id]).getchannel("A").getextrema()[1]
    window.opacity_control.spin.setValue(40)
    faded = render_layers(window.document, [layer.id]).getchannel("A").getextrema()[1]
    assert full == 255 and faded == pytest.approx(102, abs=1)


def test_a_dropped_image_takes_its_opacity(window, tmp_path, monkeypatch):
    from app.dialogs import ImportChoiceDialog
    path = tmp_path / "depot.png"
    Image.new("RGBA", (10, 10), BLUE).save(path)
    monkeypatch.setattr(ImportChoiceDialog, "exec", lambda dialog: setattr(dialog, "choice", "add") or 1)
    window.install_document(Document(40, 40), None)
    window.import_dropped_images([str(path)])
    layer = window.document.layers[-1]
    assert window.selected_id == layer.id and window.opacity_control.value() == 100
    window.opacity_control.spin.setValue(60)
    assert alpha_at(window.document, layer.id, (20, 20)) == pytest.approx(153, abs=1)


def test_moving_and_merging_keep_the_appearance(two_layers):
    window, base, top = two_layers
    window.opacity_control.spin.setValue(50)
    assert window.nudge_layer(5, 0)
    assert window.document.layer(top).opacity == 0.5
    before = render_layers(window.document)
    window.set_checked_layers([base, top])
    assert window.merge_checked_layers()
    after = render_layers(window.document)
    assert len(window.document.layers) == 1
    worst = max(abs(a - b) for a, b in zip(before.tobytes(), after.tobytes()))
    assert worst <= 1


def test_preview_stays_fast_on_a_large_image(window):
    document = Document(4000, 3000)
    layer = document.add_image_bytes(png_bytes(4000, 3000, RED), "Grande", center=False)
    window.install_document(document, layer.id)
    control = window.opacity_control
    start = time.perf_counter()
    control.slider.setSliderDown(True)
    for value in range(100, 0, -2):
        control.slider.setValue(value)
    elapsed = time.perf_counter() - start
    control.slider.setSliderDown(False)
    assert elapsed < 0.5  # 50 preview steps: the image is never copied
    assert window.document.layer(layer.id).opacity == 0.02 and window.undo_stack.count() == 1


# --- Saving and exporting -------------------------------------------------------------

def test_save_and_reopen_restore_every_opacity_and_the_same_render(two_layers, tmp_path):
    window, base, top = two_layers
    window.opacity_control.spin.setValue(45)
    window.select_layer(base)
    window.opacity_control.spin.setValue(80)
    path = tmp_path / "opacite.manta"
    save_project(window.document, path)
    reopened = open_project(path)
    assert reopened.layer(base).opacity == 0.8 and reopened.layer(top).opacity == 0.45
    assert render_layers(reopened).tobytes() == render_layers(window.document).tobytes()


def test_older_projects_without_opacity_open_at_100(tmp_path):
    document = Document(20, 20)
    document.add_image_bytes(png_bytes(5, 5), "Ancien")
    source = tmp_path / "recent.manta"
    save_project(document, source)
    old = tmp_path / "ancien.manta"
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(old, "w") as copy:
        for info in archive.infolist():
            data = archive.read(info)
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                for layer in manifest["layers"]:
                    del layer["opacity"]
                data = json.dumps(manifest).encode("utf-8")
            copy.writestr(info, data)
    assert open_project(old).layers[0].opacity == 1.0


def test_png_export_keeps_the_transparency_and_jpeg_flattens_like_the_canvas(window, tmp_path):
    document = Document(30, 20)
    layer = document.add_image_bytes(png_bytes(10, 10, RED), "Rouge", center=False)
    layer.opacity = 0.5
    window.install_document(document, layer.id)
    image = qimage_to_pil(render_document(window.document))
    export.save_image(image, tmp_path / "rendu.png")
    export.save_image(image, tmp_path / "rendu.jpg")
    with Image.open(tmp_path / "rendu.png") as png:
        assert png.mode == "RGBA"
        assert png.getpixel((5, 5))[3] == pytest.approx(128, abs=1)
        assert png.getpixel((25, 15))[3] == 0  # transparent areas are not filled with white
    with Image.open(tmp_path / "rendu.jpg") as jpeg:
        expected = [round(0.5 * c + 0.5 * 255) for c in RED[:3]]  # half red over white
        assert all(abs(a - b) <= 6 for a, b in zip(jpeg.convert("RGB").getpixel((5, 5)), expected))
