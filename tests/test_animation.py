"""Animated GIF and APNG layers: import, shared time, rendering, exports and projects."""
import io
import os
import zipfile

import pytest

pytest.importorskip("PySide6")

from conftest import png_bytes  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog  # noqa: E402

from app import animation, export  # noqa: E402
from app.graphics import layer_pixmap, qimage_to_pil, render_at, render_document  # noqa: E402
from app.model import Document  # noqa: E402
from app.storage import open_project, save_project  # noqa: E402
from app.timeline import document_duration, export_segments, frame_changes, frame_index  # noqa: E402

RED, GREEN, BLUE, YELLOW = (220, 20, 20, 255), (20, 200, 60, 255), (20, 60, 220, 255), (240, 220, 20, 255)
HALF_BLUE = (20, 60, 220, 128)


def gif_bytes(colors, durations, size=(12, 8)):
    frames = [Image.new("RGBA", size, color) for color in colors]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0)
    return output.getvalue()


def apng_bytes(colors, durations, size=(12, 8), default=None):
    frames = [Image.new("RGBA", size, color) for color in colors]
    output = io.BytesIO()
    if default is None:
        frames[0].save(output, format="PNG", save_all=True, append_images=frames[1:], duration=durations, loop=0)
    else:
        # The default image is shown by viewers without APNG support, not played.
        Image.new("RGBA", size, default).save(output, format="PNG", save_all=True, append_images=frames,
                                              duration=durations, loop=0, default_image=True)
    return output.getvalue()


def pixel(document, point, time_ms):
    return render_at(document, time_ms).getpixel(point)


@pytest.fixture
def composed():
    """60 × 40 document: a red PNG background, a 15 s GIF and a 10 s APNG on top of it."""
    document = Document(60, 40)
    document.add_image_bytes(png_bytes(60, 40, RED), "Fond", center=False)
    gif = document.add_image_bytes(gif_bytes([GREEN, BLUE, YELLOW], [5000, 5000, 5000]), "GIF", center=False)
    apng = document.add_image_bytes(apng_bytes([BLUE, HALF_BLUE, GREEN, YELLOW], [2500] * 4), "APNG", center=False)
    gif.x, gif.y = 0, 0
    apng.x, apng.y = 40, 20
    return document, gif.id, apng.id


# --- Import ---------------------------------------------------------------------------

def test_an_animated_gif_becomes_one_animated_layer():
    document = Document(40, 40)
    layer = document.add_image_bytes(gif_bytes([RED, GREEN, BLUE], [100, 0, 250]), "anim")
    assert layer.is_animated and len(document.layers) == 1
    assert layer.frame_durations == [100, 100, 250]  # a zero delay plays for 100 ms, as in viewers
    reader = animation.frame_reader(layer.animation, document.assets[layer.animation])
    assert reader.frame_count == 3
    assert [reader.frame(index).getpixel((0, 0)) for index in (2, 0, 1)] == [BLUE, RED, GREEN]
    with Image.open(io.BytesIO(document.assets[layer.asset])) as still:
        assert still.getpixel((0, 0)) == RED  # the still image is the first frame


def test_an_animated_png_keeps_partial_transparency():
    document = Document(40, 40)
    layer = document.add_image_bytes(apng_bytes([RED, HALF_BLUE], [200, 300]), "apng")
    assert layer.is_animated and layer.frame_durations == [200, 300]
    assert animation.frame_reader(layer.animation, document.assets[layer.animation]).frame(1).getpixel((3, 3)) \
        == HALF_BLUE


def test_the_default_image_of_an_apng_is_not_part_of_the_animation():
    document = Document(40, 40)
    layer = document.add_image_bytes(apng_bytes([GREEN, BLUE], [400, 600], default=YELLOW), "apng")
    assert layer.is_animated and layer.frame_durations == [400, 600]
    with Image.open(io.BytesIO(document.assets[layer.asset])) as still:
        assert still.getpixel((0, 0)) == GREEN  # the first animated frame, not the default image
    reader = animation.frame_reader(layer.animation, document.assets[layer.animation])
    assert [reader.frame(index).getpixel((0, 0)) for index in (0, 1)] == [GREEN, BLUE]


@pytest.mark.parametrize("contents", [
    png_bytes(10, 10, RED),
    gif_bytes([RED], [100]),
    apng_bytes([GREEN], [100]),
], ids=["png", "gif-1-frame", "apng-1-frame"])
def test_still_images_and_single_frame_gifs_stay_still(contents):
    document = Document(40, 40)
    layer = document.add_image_bytes(contents, "fixe")
    assert not layer.is_animated and layer.animation is None and layer.frame_durations == []


def test_a_damaged_animation_is_refused_and_the_document_is_untouched(window, tmp_path, monkeypatch):
    data = gif_bytes([RED, GREEN, BLUE], [100, 100, 100], size=(64, 64))
    broken = tmp_path / "abime.gif"
    broken.write_bytes(data[: len(data) * 2 // 3])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text, *_args: warnings.append(text))
    before = window.document.clone()
    window._import_paths([str(broken)])
    assert window.document == before and window.undo_stack.count() == 0
    assert len(warnings) == 1 and "endommagée" in warnings[0]


def test_oversized_animations_are_refused(monkeypatch):
    monkeypatch.setattr(animation, "MAX_FRAMES", 2)
    with pytest.raises(ValueError, match="trop longue"):
        Document(40, 40).add_image_bytes(gif_bytes([RED, GREEN, BLUE], [100] * 3), "long")


# --- Shared time ------------------------------------------------------------------------

def test_two_animations_of_15_and_10_seconds_loop_on_15_seconds(composed):
    document, gif, apng = composed
    assert document_duration(document) == 15000
    gif_layer, apng_layer = document.layer(gif), document.layer(apng)
    # At 12 s the 15 s GIF shows its third frame, the 10 s APNG has looped (local 2 s).
    assert frame_index(gif_layer.frame_durations, 12000) == 2
    assert frame_index(apng_layer.frame_durations, 12000) == 0
    assert frame_changes(document) == [0, 2500, 5000, 7500, 10000, 12500]
    segments = export_segments(document)
    assert sum(length for _start, length in segments) == 15000 and segments[0] == (0, 2500)


def test_variable_frame_durations_pick_the_right_frame():
    durations = [100, 50, 850]
    assert [frame_index(durations, t) for t in (0, 99, 100, 149, 150, 999, 1000, 1150)] == [0, 0, 1, 1, 2, 2, 0, 2]


def test_short_frames_are_merged_and_gif_times_snapped_to_hundredths(window):
    document = Document(20, 20)
    document.add_image_bytes(gif_bytes([RED, GREEN, BLUE], [30, 30, 30]), "a", center=False)
    document.add_image_bytes(apng_bytes([RED, GREEN], [45, 50]), "b", center=False)
    for quantum in (1, 10):
        segments = export_segments(document, quantum=quantum)
        assert all(length >= 20 for _start, length in segments)
        assert all(start % quantum == 0 for start, _length in segments)
        assert sum(length for _start, length in segments) == document_duration(document)


def test_removing_the_longest_animation_shortens_the_document(window, composed):
    document, gif, _apng = composed
    window.install_document(document, gif)
    window.seek_animation(12000)
    assert window.playback_bar.isVisibleTo(window) and window.playback_bar.slider.maximum() == 14999
    window.mutate("Supprimer", lambda doc: doc.layers.remove(doc.layer(gif)), None)
    assert document_duration(window.document) == 10000
    assert window.animation_time_ms == 2000  # kept inside the new length
    window.mutate("Supprimer", lambda doc: doc.layers.remove(next(layer for layer in doc.layers if layer.is_animated)), None)
    assert not window.playback_bar.isVisibleTo(window) and window.animation_time_ms == 0


def test_seeking_shows_every_animation_at_that_time(window, composed):
    document, gif, apng = composed
    window.install_document(document, gif)
    for time_ms in (0, 6000, 12600):
        window.seek_animation(time_ms)
        for layer_id in (gif, apng):
            layer = window.document.layer(layer_id)
            shown = window.canvas.graphic_for(layer_id).pixmap()
            assert shown.cacheKey() == layer_pixmap(layer, window.document, time_ms).cacheKey()
    assert window.playback_bar.slider.value() == 12600


def test_playing_follows_the_clock_and_loops(window, composed, monkeypatch):
    document, gif, _apng = composed
    window.install_document(document, gif)
    window.play_animation()
    assert window.playing and window._play_timer.isActive()
    monkeypatch.setattr(window._play_clock, "elapsed", lambda: 16_000)
    window._play_tick()
    assert window.animation_time_ms == 1000  # 16 s on a 15 s loop
    window.toggle_animation()
    assert not window.playing and not window._play_timer.isActive()
    window.rewind_animation()
    assert window.animation_time_ms == 0


# --- Rendering ------------------------------------------------------------------------------

def test_render_at_composes_frames_backgrounds_opacity_and_transforms(composed):
    document, gif, apng = composed
    assert pixel(document, (5, 5), 0) == GREEN and pixel(document, (5, 5), 7000) == BLUE
    assert pixel(document, (45, 25), 0) == BLUE and pixel(document, (45, 25), 10600) == BLUE  # looped
    blended = pixel(document, (45, 25), 3000)  # half transparent blue over the red background
    assert blended[3] == 255 and abs(blended[0] - (20 * 128 + 220 * 127) // 255) <= 2
    document.layer(gif).opacity = 0.5
    faded = pixel(document, (5, 5), 0)
    assert abs(faded[1] - (200 + 20) // 2) <= 2  # green over red at 50 %
    document.layer(gif).x, document.layer(gif).sx = 20, 2.0
    assert pixel(document, (5, 5), 0) == RED and pixel(document, (43, 5), 0)[:3] != RED[:3]
    document.layer(gif).visible = False
    assert pixel(document, (30, 5), 7000) == RED


def test_partial_gif_frames_are_composed_over_the_previous_ones():
    first = Image.new("RGBA", (10, 10), RED)
    second = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    second.paste(BLUE, (0, 0, 5, 10))  # only the left half changes
    output = io.BytesIO()
    first.save(output, format="GIF", save_all=True, append_images=[second], duration=[100, 100], loop=0,
               disposal=1)
    document = Document(10, 10)
    document.add_image_bytes(output.getvalue(), "partiel", center=False)
    assert pixel(document, (2, 5), 100) == BLUE and pixel(document, (8, 5), 100) == RED


# --- Exports ----------------------------------------------------------------------------------

def test_still_exports_show_the_first_frames(window, composed, tmp_path):
    document, gif, _apng = composed
    window.install_document(document, gif)
    window.seek_animation(7000)  # the canvas shows another time: still exports stay at 0 s
    still = qimage_to_pil(render_document(window.document))
    export.save_image(still, tmp_path / "fixe.png")
    export.save_image(still, tmp_path / "fixe.jpg")
    with Image.open(tmp_path / "fixe.png") as png:
        assert png.getpixel((5, 5)) == GREEN and png.getpixel((45, 25)) == BLUE
    with Image.open(tmp_path / "fixe.jpg") as jpeg:
        assert all(abs(a - b) <= 8 for a, b in zip(jpeg.getpixel((5, 5)), GREEN[:3]))
    assert window.document.layer(gif).is_animated  # the document keeps its animations


def reimported(path):
    with Image.open(path) as image:
        frames = []
        for index in range(image.n_frames):
            image.seek(index)
            frames.append((image.convert("RGBA"), int(image.info.get("duration", 0))))
        return frames, image.info.get("loop")


@pytest.mark.parametrize("animation_format, quantum", [("APNG", 1), ("GIF", 10)])
def test_animated_export_loops_forever_with_the_right_length_and_frames(window, composed, tmp_path,
                                                                        animation_format, quantum):
    tmp_path = tmp_path / "exports"
    tmp_path.mkdir()
    document, gif, _apng = composed
    window.install_document(document, gif)
    destination = window.export_animation(tmp_path / "anim", animation_format)
    assert destination is not None and destination.suffix == (".gif" if animation_format == "GIF" else ".png")
    frames, loop = reimported(destination)
    assert loop == 0 and len(frames) == 6 and sum(duration for _frame, duration in frames) == 15000
    # Each output frame matches the composition at its instant (GIF: opaque pixels only).
    start = 0
    for image, duration in frames:
        expected = render_at(window.document, start + duration // 2)
        for point in ((5, 5), (45, 25), (30, 30)):
            got, want = image.getpixel(point), expected.getpixel(point)
            assert all(abs(a - b) <= 12 for a, b in zip(got, want)), (start, point, got, want)
        start += duration
    assert not [name for name in os.listdir(tmp_path) if name.endswith(".tmp")]


def test_apng_export_keeps_partial_transparency(window, tmp_path):
    document = Document(20, 20)
    document.add_image_bytes(apng_bytes([HALF_BLUE, RED], [300, 300]), "verre", center=False)
    window.install_document(document, None)
    destination = window.export_animation(tmp_path / "verre.png", "APNG")
    frames, _loop = reimported(destination)
    first = frames[0][0]
    # Rendering composes premultiplied colours: they may move by one unit, the alpha stays.
    assert first.getpixel((3, 3))[3] == 128 and all(abs(a - b) <= 1 for a, b in zip(first.getpixel((3, 3)), HALF_BLUE))
    assert first.getpixel((15, 15))[3] == 0


def test_cancelling_the_export_writes_nothing(window, composed, tmp_path, monkeypatch):
    tmp_path = tmp_path / "exports"
    tmp_path.mkdir()
    document, gif, _apng = composed
    window.install_document(document, gif)
    monkeypatch.setattr(QProgressDialog, "wasCanceled", lambda _self: True)
    assert window.export_animation(tmp_path / "annule.gif", "GIF") is None
    assert os.listdir(tmp_path) == []
    frames = [Image.new("RGBA", (8, 8), color) for color in (RED, GREEN)]
    with pytest.raises(export.ExportCancelled):
        export.save_animation(frames, [100, 100], tmp_path / "stop.png", "APNG", cancelled=lambda: True)
    assert os.listdir(tmp_path) == []


def test_exporting_a_still_document_as_an_animation_is_explained(window, tmp_path, monkeypatch):
    tmp_path = tmp_path / "exports"
    tmp_path.mkdir()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text, *_args: shown.append(text))
    window.install_document(Document(20, 20), None)
    assert window.export_animation(tmp_path / "rien.gif", "GIF") is None
    assert shown and "aucun calque animé" in shown[0] and os.listdir(tmp_path) == []


# --- Projects ------------------------------------------------------------------------------------

def test_projects_keep_their_animations_and_reopen_at_zero_paused(window, composed, tmp_path):
    document, gif, apng = composed
    document.layer(gif).opacity, document.layer(apng).sx = 0.4, 1.5
    window.install_document(document, gif)
    window.play_animation()
    window.seek_animation(9000)
    path = tmp_path / "anime.manta"
    window.project_path = path
    assert window.save_document()
    window._start_session(Document(10, 10), None)
    window._start_session(open_project(path), path)
    reopened = window.document
    assert reopened.layer(gif).is_animated and reopened.layer(gif).frame_durations == [5000] * 3
    assert reopened.layer(apng).frame_durations == [2500] * 4
    assert reopened.layer(gif).opacity == 0.4 and reopened.layer(apng).sx == 1.5
    assert window.animation_time_ms == 0 and not window.playing
    assert window.playback_bar.isVisibleTo(window) and document_duration(reopened) == 15000
    assert render_at(reopened, 7000).tobytes() == render_at(document, 7000).tobytes()


def test_a_project_whose_animation_is_lost_shows_the_first_frame(composed, tmp_path):
    document, gif, _apng = composed
    path, damaged = tmp_path / "complet.manta", tmp_path / "sans_animation.manta"
    save_project(document, path)
    lost = f"assets/{document.layer(gif).animation}.png"
    with zipfile.ZipFile(path) as archive, zipfile.ZipFile(damaged, "w") as copy:
        for info in archive.infolist():
            if info.filename != lost:
                copy.writestr(info, archive.read(info))
    layer = open_project(damaged).layer(gif)
    assert not layer.is_animated and layer.animation is None and layer.asset


# --- Interface ------------------------------------------------------------------------------------

def test_dropping_a_gif_can_create_a_document_of_its_size(window, tmp_path, monkeypatch):
    from app.dialogs import ImportChoiceDialog
    path = tmp_path / "anim.gif"
    path.write_bytes(gif_bytes([RED, GREEN], [200, 300], size=(32, 24)))
    monkeypatch.setattr(ImportChoiceDialog, "exec", lambda dialog: setattr(dialog, "choice", "new") or 1)
    window.import_dropped_images([str(path)])
    assert (window.document.width, window.document.height) == (32, 24)
    layer = window.document.layers[0]
    assert layer.is_animated and window.document.background is None
    assert window.playback_bar.isVisibleTo(window) and window.animation_time_ms == 0


def test_animated_layers_are_marked_in_the_layer_list(window, composed):
    from PySide6.QtWidgets import QLabel
    document, gif, _apng = composed
    window.install_document(document, gif)
    tooltips = [label.toolTip() for label in window.layer_list.findChildren(QLabel)]
    assert tooltips.count("Calque animé (GIF ou APNG)") == 2 and "Calque image" in tooltips


def test_pixel_tools_are_refused_on_animated_layers(window, composed):
    document, gif, apng = composed
    window.install_document(document, gif)
    assert not window.paint_bucket_btn.isEnabled()
    assert window.refuse_animated(window.document.layer(gif), "la gomme")
    assert "calque animé" in window.statusBar().currentMessage()
    assert not window.trim_layer_margins(gif)
    window.set_checked_layers([gif, apng])
    assert not window.merge_checked_layers()
    before = window.document.clone()
    window.commit_eraser_stroke(gif, [])
    assert window.document == before


def test_playback_bar_follows_the_style_and_starts_paused(window, composed):
    document, gif, _apng = composed
    window.install_document(document, gif)
    bar = window.playback_bar
    assert bar.objectName() == "playbackBar" and bar.time_label.text() == "0,00 s / 15,00 s"
    from PySide6.QtCore import Qt
    assert bar.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # the panel colour, not the system one
    bar.slider.setValue(3000)  # dragging the slider
    QApplication.processEvents()
    assert window.animation_time_ms == 3000 and bar.time_label.text().startswith("3,00 s")
