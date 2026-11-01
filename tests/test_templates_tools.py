"""Element templates and their library, tokens, spritesheets and remembered folders."""
import io
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QLabel, QListWidget, QMessageBox

from app import templates
from app.builtin_templates import BUILTIN_TEMPLATES, builtin_template
from app.graphics import qimage_to_pil, render_document
from app.imaging import SpriteGrid, extract_sprites, grid_cells, grid_shape
from app.model import Document, Layer
from app.paths import safe_file_stem
from app.sprite_dialog import MAX_DETAILED_CELLS, SpriteSheetDialog, export_sprites
from app.storage import open_project
from app.template_library import TemplateLibraryDialog
from app.templates import extract_elements, insert_elements, list_templates, save_template
from app.token_dialog import TokenDialog
from app.tokens import FRAMES, TokenSettings, _portrait, _rgb, max_border, render_token, supersampling


@pytest.fixture
def library(monkeypatch, tmp_path):
    directory = tmp_path / "modeles"
    monkeypatch.setattr(templates, "template_directory", lambda: directory)
    return directory


def png(size=(20, 20), color=(200, 30, 30, 255), box=None):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle(box or (0, 0, size[0] - 1, size[1] - 1), fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


# --- Element templates --------------------------------------------------------------------


@pytest.mark.parametrize("key", list(BUILTIN_TEMPLATES))
def test_bundled_templates_are_editable_vector_groups(qapp, key):
    document = builtin_template(key)
    assert len(document.folders) == 1 and document.layers
    assert {layer.kind for layer in document.layers} <= {"shape", "text"}  # no picture inside
    assert qimage_to_pil(render_document(document)).getbbox() is not None


def test_inserting_twice_creates_independent_layers_and_folders():
    source = Document(200, 100)
    image = source.add_image_bytes(png(), "Image", center=False)
    text = source.add_text("Texte")
    source.create_folder([image.id, text.id], "Paire")
    elements = extract_elements(source, [image.id, text.id], (0, 0, 200, 100))
    target = Document(400, 300)
    first = insert_elements(target, elements, (100, 100))
    second = insert_elements(target, elements, (0, 0))
    assert len(set(first) | set(second)) == 4 and len(target.folders) == 2
    assert target.layer(first[0]).x == 100 and target.layer(second[0]).x == 0
    assert target.layer(first[0]).asset == target.layer(second[0]).asset in target.assets


def test_window_inserts_a_template_centred_checked_and_undoable(window):
    window.install_document(Document(800, 600), None)
    window.undo_stack.clear()
    elements = builtin_template("builtin-banner")
    assert window.insert_template_elements(elements, "Bandeau")
    inserted = window.document.layers
    assert len(window.checked_layer_ids()) == len(inserted) == 2
    banner = next(layer for layer in inserted if layer.kind == "shape")
    assert (banner.x, banner.y) == ((800 - 440) / 2, (600 - 96) / 2)
    window.undo_stack.undo()
    assert window.document.layers == [] and window.document.folders == []


def test_library_lists_bundled_and_user_templates_and_manages_them(window, library, monkeypatch):
    save_template(builtin_template("builtin-label"), "Mon étiquette", None, kind="elements")
    save_template(Document(10, 10), "Projet complet", None)  # a preset: not offered here
    (library / "abime.manta").write_bytes(b"pas un zip")
    dialog = TemplateLibraryDialog(window)
    entries = [dialog.gallery.item(i).data(templates_role()) for i in range(dialog.gallery.count())]
    assert len(entries) == len(BUILTIN_TEMPLATES) + 1 and entries[-1][0] == "user"
    dialog.gallery.setCurrentRow(0)  # a bundled template: insert or duplicate only
    assert not dialog.delete_btn.isEnabled() and dialog.duplicate_btn.isEnabled()
    dialog.duplicate_selected()
    assert len(list_templates(kind="elements")) == 2
    user_row = next(i for i in range(dialog.gallery.count()) if dialog.gallery.item(i).text().startswith("Mon"))
    dialog.gallery.setCurrentRow(user_row)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renommée", True))
    dialog.rename_selected()
    assert "Renommée" in [info.name for info in list_templates(kind="elements")]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.delete_selected()
    assert "Renommée" not in [info.name for info in list_templates(kind="elements")]


def templates_role():
    from app.template_library import ENTRY_ROLE
    return ENTRY_ROLE


def test_library_dialog_choice_inserts_through_the_window(window, library, monkeypatch):
    window.install_document(Document(500, 400), None)

    def choose_first(dialog):
        dialog.gallery.setCurrentRow(0)
        dialog.action = "insert"
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TemplateLibraryDialog, "exec", choose_first)
    assert window.open_template_library()
    assert window.document.layers and window.document.folders


def test_editing_a_template_saves_it_back_with_its_name(window, library):
    path = save_template(builtin_template("builtin-speech"), "Ma bulle", None, kind="elements")
    assert window.edit_element_template(path, "Ma bulle", open_project(path))
    assert window.windowTitle().startswith("Modèle : Ma bulle")
    window.mutate("Ajout", lambda doc: doc.add_text("Nouveau"))
    assert window.save_document()
    info = templates.read_template_info(path)
    assert (info.name, info.kind) == ("Ma bulle", "elements")
    assert len(open_project(path).layers) == 3


# --- Tokens --------------------------------------------------------------------------------


def test_circular_token_is_transparent_outside_with_its_border():
    portrait = Image.new("RGBA", (300, 200), (20, 120, 220, 255))
    token = render_token(portrait, TokenSettings(size=128, frame="circle", border_color="#FF0000", border_width=8))
    assert token.size == (128, 128) and token.mode == "RGBA"
    assert token.getpixel((0, 0))[3] == 0 and token.getpixel((64, 64)) == (20, 120, 220, 255)
    assert token.getpixel((64, 4))[:3] == (255, 0, 0)


@pytest.mark.parametrize("frame", ["square", "thick", "decorative"])
def test_other_frames_render_and_keep_a_transparent_corner_or_border(frame):
    token = render_token(Image.new("RGBA", (64, 64), (0, 255, 0, 255)),
                         TokenSettings(size=96, frame=frame, border_width=6))
    assert token.getpixel((48, 48))[3] == 255
    assert token.getpixel((0, 0))[3] < 255


def test_large_tokens_are_supersampled_less():
    from app.tokens import supersampling
    assert [supersampling(size) for size in (256, 1024, 2048, 4096)] == [4, 4, 2, 1]
    token = render_token(Image.new("RGBA", (40, 40), (255, 255, 255, 255)), TokenSettings(size=2048, border_width=0))
    assert token.size == (2048, 2048) and token.getpixel((1024, 1024))[3] == 255


def test_token_settings_are_validated_and_offsets_move_the_portrait():
    with pytest.raises(ValueError):
        render_token(Image.new("RGBA", (10, 10)), TokenSettings(size=10))
    with pytest.raises(ValueError):
        render_token(Image.new("RGBA", (10, 10)), TokenSettings(border_color="rouge"))
    half = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    half.paste((0, 0, 255, 255), (50, 0, 100, 100))
    centred = render_token(half, TokenSettings(size=100, border_width=0))
    shifted = render_token(half, TokenSettings(size=100, border_width=0, offset_x=30))
    assert centred.getpixel((60, 50))[:3] == (0, 0, 255) and shifted.getpixel((60, 50))[:3] == (255, 0, 0)


def reference_portrait(image, settings, big):
    """Former rendering: the whole source enlarged, then pasted on the token square."""
    source = image.convert("RGBA")
    scale = max(big / source.width, big / source.height) * settings.zoom
    width, height = max(1, round(source.width * scale)), max(1, round(source.height * scale))
    resample = Image.Resampling.NEAREST if settings.pixel_art else Image.Resampling.LANCZOS
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    factor = big / settings.size
    canvas.paste(source.resize((width, height), resample),
                 (round((big - width) / 2 + settings.offset_x * factor),
                  round((big - height) / 2 + settings.offset_y * factor)))
    return canvas


def gradient(width, height):
    image = Image.new("RGBA", (width, height))
    image.putdata([((x * 7) % 256, (y * 5) % 256, (x * y) % 256, 255) for y in range(height) for x in range(width)])
    return image


@pytest.mark.parametrize("source_size, settings", [
    ((120, 80), TokenSettings(size=128)),
    ((80, 120), TokenSettings(size=100, zoom=2.5, offset_x=-30, offset_y=18)),
    ((300, 200), TokenSettings(size=64, zoom=0.3, offset_y=40)),      # reduced, not covering the square
    ((16, 16), TokenSettings(size=128, zoom=1.5, offset_x=20, pixel_art=True)),
    ((24, 40), TokenSettings(size=96, zoom=3, offset_y=-25, pixel_art=True)),
])
def test_cropped_portrait_matches_the_former_full_enlargement(source_size, settings):
    big = settings.size * supersampling(settings.size)
    expected = reference_portrait(gradient(*source_size), settings, big)
    actual = _portrait(gradient(*source_size), settings, big)
    difference = max(high for _low, high in ImageChops.difference(expected, actual).getextrema())
    assert difference <= 2  # Lanczos coefficients may round differently by one or two levels


def test_token_portrait_memory_follows_the_token_size_not_the_source(monkeypatch):
    # tracemalloc does not see Pillow's pixel buffers: every image built is measured instead.
    largest = []
    original_new = Image.Image._new

    def spy(self, im):
        result = original_new(self, im)
        largest.append(result.width * result.height)
        return result

    monkeypatch.setattr(Image.Image, "_new", spy)
    panorama = Image.new("RGBA", (8000, 500), (20, 120, 220, 255))
    start = time.perf_counter()
    token = render_token(panorama, TokenSettings(size=4096, zoom=4, border_width=0))
    elapsed = time.perf_counter() - start
    assert token.size == (4096, 4096) and token.getpixel((2048, 2048)) == (20, 120, 220, 255)
    # Formerly a 262144 × 16384 enlargement (16 GiB); now nothing larger than the token itself.
    assert max(largest) <= 4096 * 4096
    assert elapsed < 2


@pytest.mark.parametrize("frame", list(FRAMES))
@pytest.mark.parametrize("size", [32, 97, 512])
def test_every_frame_draws_its_thickest_accepted_border(frame, size):
    limit = max_border(size, frame)
    token = render_token(Image.new("RGBA", (40, 30), (0, 200, 0, 255)),
                         TokenSettings(size=size, frame=frame, border_width=limit))
    assert token.size == (size, size)
    with pytest.raises(ValueError, match="Bordure trop épaisse"):
        TokenSettings(size=size, frame=frame, border_width=limit + 1).validate()


def test_thick_frame_border_is_limited_to_an_eighth_of_the_size():
    assert max_border(512, "thick") == 64 and max_border(512, "circle") == 128
    with pytest.raises(ValueError, match="maximum 64 px"):
        render_token(Image.new("RGBA", (10, 10)), TokenSettings(size=512, frame="thick", border_width=128))


@pytest.mark.parametrize("color", ["##D6A06A", "+1+2+3", "GGGGGG", "D6A06A", "#D6A06", "#D6A06A0", "", None])
def test_border_colours_must_be_strict_hexadecimal(color):
    with pytest.raises(ValueError, match="Couleur de bordure invalide"):
        _rgb(color)


def test_border_colour_accepts_both_cases():
    assert _rgb("#d6a06A") == (214, 160, 106)


def test_token_dialog_border_limit_follows_frame_and_size(window):
    dialog = TokenDialog(window)
    assert dialog.border_width.maximum() == 128  # circle, 512 px
    dialog.border_width.setValue(100)
    dialog.frame.setCurrentIndex(dialog.frame.findData("thick"))
    assert dialog.border_width.maximum() == 64 and dialog.border_width.value() == 64
    dialog.size_spin.setValue(256)
    assert dialog.border_width.maximum() == 32
    dialog.frame.setCurrentIndex(dialog.frame.findData("square"))
    assert dialog.border_width.maximum() == 64
    dialog.settings().validate()


def wheel(widget, delta):
    event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    widget.wheelEvent(event)


def test_fine_wheel_zooms_the_token_preview_at_low_values(window):
    dialog = TokenDialog(window)
    dialog.zoom.setValue(20)
    for _index in range(20):
        wheel(dialog.preview, 15)  # an eighth of a notch: touchpads, high resolution mice
    assert dialog.zoom.value() == round(20 * 1.1 ** 2.5)
    for _index in range(20):
        wheel(dialog.preview, -15)
    assert dialog.zoom.value() == 20
    dialog.zoom.setValue(40)  # moved by the slider: the wheel starts again from there
    wheel(dialog.preview, 120)
    assert dialog.zoom.value() == 44


def test_previews_are_drawn_at_the_screen_density(window, monkeypatch):
    # A 150 % screen for the previews, 200 % for the thumbnail list. QLabel.pixmap() gives
    # back a converted copy, so the pixmaps are caught when they are set.
    monkeypatch.setattr(QLabel, "devicePixelRatioF", lambda _self: 1.5)
    monkeypatch.setattr(QListWidget, "devicePixelRatioF", lambda _self: 2.0)
    shown = []
    monkeypatch.setattr(QLabel, "setPixmap", lambda _self, pixmap: shown.append(pixmap))
    token_dialog = TokenDialog(window)
    token_dialog.set_source(Image.new("RGBA", (50, 80), (10, 200, 10, 255)), "Héros")
    assert (shown[-1].width(), shown[-1].devicePixelRatio()) == (480, 1.5)
    assert shown[-1].toImage().pixelColor(240, 240).name() == "#0ac80a"
    sprite_dialog = SpriteSheetDialog(window)
    sprite_dialog.cell_width.setValue(8)
    sprite_dialog.cell_height.setValue(8)
    sprite_dialog.set_sheet(sheet(), "planche")
    assert (shown[-1].width(), shown[-1].devicePixelRatio()) == (630, 1.5)
    assert sprite_dialog.cells.item(0).icon().availableSizes()[0].width() == 96  # 48 px at 200 %


def test_token_dialog_exports_a_png_and_adds_a_layer(window, monkeypatch, tmp_path):
    window.install_document(Document(600, 600), None)
    dialog = TokenDialog(window)
    dialog.set_source(Image.new("RGBA", (50, 80), (10, 200, 10, 255)), "Héros")
    dialog.size_spin.setValue(256)
    target = tmp_path / "jetons" / "heros"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "PNG (*.png)"))
    exported = dialog.export_png()
    assert exported == target.with_suffix(".png")
    with Image.open(exported) as image:
        assert image.size == (256, 256) and image.mode == "RGBA"
    assert window.initial_path("token") == str(target.parent)
    assert dialog.add_to_project()
    assert window.document.layers[-1].name == "Token : Héros"


# --- Spritesheets ------------------------------------------------------------------------


def sheet():
    image = Image.new("RGBA", (34, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 5, 5), fill=(255, 0, 0, 255))      # cell (0, 0): small sprite with margins
    draw.rectangle((10, 0, 17, 7), fill=(0, 255, 0, 255))    # cell (0, 1): full cell
    draw.rectangle((10, 8, 17, 15), fill=(0, 0, 255, 255))   # cell (1, 1); cell (1, 0) stays empty
    return image


def test_grid_cells_respect_spacing_offset_and_image_limits():
    grid = SpriteGrid(8, 8, spacing_x=2)
    cells = grid_cells((34, 16), grid)
    assert [(row, column) for row, column, _box in cells] == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    assert cells[1][2] == (10, 0, 18, 8)
    assert grid_cells((34, 16), SpriteGrid(8, 8, columns=10)) == grid_cells((34, 16), SpriteGrid(8, 8, columns=10))
    assert all(box[2] <= 34 for _r, _c, box in grid_cells((34, 16), SpriteGrid(8, 8, columns=10)))
    assert grid_cells((4, 4), SpriteGrid(8, 8)) == []
    with pytest.raises(ValueError):
        grid_cells((10, 10), SpriteGrid(0, 8))


def test_explicit_grid_counts_are_clamped_to_the_image():
    grid = SpriteGrid(16, 16, columns=3000, rows=3000)
    start = time.perf_counter()
    cells = grid_cells((64, 64), grid)
    assert time.perf_counter() - start < 0.1
    assert grid_shape((64, 64), grid) == (4, 4) and len(cells) == 16
    assert grid_shape((64, 64), SpriteGrid(16, 16, columns=2, rows=9)) == (2, 4)
    assert grid_shape((64, 64), SpriteGrid(16, 16, offset_x=100)) == (0, 4)


def test_extraction_skips_empty_cells_trims_and_keeps_pixels():
    sprites = extract_sprites(sheet(), SpriteGrid(8, 8, columns=2, spacing_x=2), trim=True)
    assert [(row, column) for row, column, _image in sprites] == [(0, 0), (0, 1), (1, 1)]
    assert sprites[0][2].size == (4, 4) and sprites[0][2].getpixel((0, 0)) == (255, 0, 0, 255)
    assert len(extract_sprites(sheet(), SpriteGrid(8, 8, columns=2, spacing_x=2), skip_empty=False)) == 4


def test_exported_sprite_names_are_unique(tmp_path):
    sprites = extract_sprites(sheet(), SpriteGrid(8, 8, columns=2, spacing_x=2))
    first = export_sprites(sprites, tmp_path, "perso")
    second = export_sprites(sprites[:1], tmp_path, "perso")
    assert [path.name for path in first] == ["perso_01_01.png", "perso_01_02.png", "perso_02_02.png"]
    assert second[0].name == "perso_01_01-2.png"


def test_sprite_dialog_selection_and_layers_in_a_folder(window):
    window.install_document(Document(64, 64), None)
    dialog = SpriteSheetDialog(window)
    dialog.set_sheet(sheet(), "planche")
    dialog.cell_width.setValue(8)
    dialog.cell_height.setValue(8)
    dialog.columns.setValue(2)
    dialog.spacing_x.setValue(2)
    dialog.refresh()
    assert dialog.cells.count() == 3
    dialog.cells.item(0).setCheckState(dialog.cells.item(0).checkState().__class__.Unchecked)
    assert len(dialog.chosen_sprites()) == 2
    assert dialog.add_as_layers()
    assert len(window.document.layers) == 2 and window.document.folders[0].name == "planche"


def test_sprite_dialog_trims_through_the_shared_extraction(window):
    dialog = SpriteSheetDialog(window)
    dialog.set_sheet(sheet(), "planche")
    for spin, value in ((dialog.cell_width, 8), (dialog.cell_height, 8), (dialog.columns, 2), (dialog.spacing_x, 2)):
        spin.setValue(value)
    dialog.trim.setChecked(True)
    dialog.refresh()
    expected = extract_sprites(sheet(), SpriteGrid(8, 8, columns=2, spacing_x=2), trim=True)
    chosen = dialog.chosen_sprites()
    assert [(row, column, image.size) for row, column, image in chosen] == \
        [(row, column, image.size) for row, column, image in expected]
    assert chosen[0][2].size == (4, 4)
    assert all(not spin.keyboardTracking() for spin in (dialog.cell_width, dialog.columns, dialog.offset_y))


def test_huge_grids_only_draw_lines_and_ask_before_output(window, monkeypatch):
    dialog = SpriteSheetDialog(window)
    dialog.set_sheet(Image.new("RGBA", (4096, 4096), (255, 0, 0, 255)), "planche")
    dialog.cell_width.setValue(1)  # "1 × 32", the intermediate value of a typed "16"
    dialog.cell_height.setValue(32)
    start = time.perf_counter()
    dialog.refresh()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5
    assert not dialog.detailed and dialog.cells.count() == 0
    assert dialog.cell_count == 4096 * 128 > MAX_DETAILED_CELLS and dialog.export_button.isEnabled()
    questions = []

    def refuse(*args, **kwargs):
        questions.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", refuse)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: pytest.fail("no folder asked"))
    layers = len(window.document.layers)
    assert dialog.export() == [] and not dialog.add_as_layers()
    assert len(questions) == 2 and len(window.document.layers) == layers
    dialog.cell_width.setValue(64)
    dialog.cell_height.setValue(64)
    dialog.refresh()
    assert dialog.detailed and dialog.cell_count == 64 * 64 and dialog.cells.count() == 1024


# --- Remembered folders ------------------------------------------------------------------


def test_folders_are_remembered_per_kind_per_template_and_across_sessions(qapp, tmp_path):
    from app.window import MainWindow
    settings_path = str(tmp_path / "settings.ini")
    first = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat), recovery_dir=tmp_path / "r")
    exports, other, projects = tmp_path / "exports", tmp_path / "modele_a", tmp_path / "projets"
    for directory in (exports, other, projects):
        directory.mkdir()
    try:
        first.remember_directory("export", exports)
        first.remember_directory("project", projects)
        first.template_origin = "modele-a"
        first.remember_directory("export", other)  # also becomes the general default
        first.template_origin = "modele-b"
        assert first.initial_path("export") == str(other)  # B never exported: general default
        first.remember_directory("export", exports)
        first.template_origin = "modele-a"
        assert first.initial_path("export") == str(other)  # B did not overwrite A's folder
        first.template_origin = None
        first.settings.sync()
    finally:
        first.undo_stack.setClean()
        first.close()
    second = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat), recovery_dir=tmp_path / "r")
    try:
        assert second.initial_path("export", "image.png") == str(exports / "image.png")
        assert second.initial_path("project") == str(projects)
        assert Path(second.initial_path("sprites")).is_dir()  # never used: a standard folder
    finally:
        second.close()


def test_missing_remembered_folder_falls_back_to_a_default(window, tmp_path):
    window.remember_directory("import", tmp_path / "supprime")
    assert Path(window.initial_path("import")).is_dir()
    assert window.initial_path("import") != str(tmp_path / "supprime")


def test_template_layer_fields_survive_extraction(qapp):
    source = Document(100, 100)
    shape = Layer(kind="shape", shape_type="speech", x=30, y=40, fill_color="#FFFFFF")
    source.layers.append(shape)
    elements = extract_elements(source, [shape.id], (30, 40, 230, 160))
    copy = elements.layers[0]
    assert (copy.x, copy.y, copy.shape_type, copy.fill_color) == (0, 0, "speech", "#FFFFFF")


@pytest.mark.parametrize("name, expected", [
    ("Token : héros", "Token _ héros"),
    ("a/b\\c", "a_b_c"),
    ("Boss?", "Boss_"),
    ("CON", "_CON"),
    ("lpt1.png", "_lpt1.png"),
    ("  fin. ", "fin"),
    ("...", "sprite"),
    ("", "sprite"),
])
def test_file_names_built_from_layer_names_are_valid(name, expected):
    assert safe_file_stem(name, "sprite") == expected


def test_sprites_of_a_token_layer_are_written_as_visible_files(tmp_path):
    sprites = [(0, 0, Image.new("RGBA", (4, 4), (255, 0, 0, 255))),
               (0, 1, Image.new("RGBA", (4, 4), (0, 255, 0, 255)))]
    written = export_sprites(sprites, tmp_path, "Token : héros")  # ":" used to write a hidden NTFS stream
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Token _ héros_01_01.png", "Token _ héros_01_02.png"]
    assert all(path.stat().st_size > 0 for path in written)
