"""Edge cases and handling mistakes across modules."""
import pytest

pytest.importorskip("PySide6")

from conftest import png_bytes  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402

from app import selection as S  # noqa: E402
from app.graphics import CurvedTextGraphicItem, render_layers  # noqa: E402
from app.model import Document, Layer  # noqa: E402

NO_MODIFIER = Qt.KeyboardModifier.NoModifier


def test_one_pixel_document_supports_every_selection_tool(window):
    document = Document(1, 1)
    layer = document.add_image_bytes(png_bytes(1, 1, (9, 9, 9, 255)), "Point")
    window.install_document(document, layer.id)
    window.apply_magic_wand(QPointF(0.5, 0.5), NO_MODIFIER)
    assert S.bounds(window.selection_mask) == (0, 0, 1, 1)
    window.clear_selection_content()
    assert render_layers(window.document, [layer.id]).getpixel((0, 0))[3] == 0
    window.apply_selection_shape("ellipse", QRectF(0, 0, 1, 1), NO_MODIFIER)
    assert window.selection_mask is not None


def test_wand_outside_the_document_changes_nothing(window):
    count = window.undo_stack.count()
    window.apply_magic_wand(QPointF(-5, 10_000), NO_MODIFIER)
    assert window.undo_stack.count() == count and window.selection_mask is None


def test_empty_and_whitespace_texts_render_without_errors():
    for text in ("", " ", "\n\n"):
        item = CurvedTextGraphicItem(Layer(kind="text", text=text, text_deformation="u", curve_intensity=90))
        assert item.boundingRect().width() > 0
        assert len(item.shape_handles_local()) == 1


def test_extreme_spacing_and_font_size_keep_letters_in_order():
    item = CurvedTextGraphicItem(Layer(kind="text", text="ABCDE", font_size=8, character_spacing=-50))
    xs = [point.x() for _char, _advance, point, _angle in item.placements]
    assert xs == sorted(xs)
    big = CurvedTextGraphicItem(Layer(kind="text", text="A", font_size=300, text_deformation="custom",
                                      path_controls=[[0, -1], [1, 1]]))
    assert big.boundingRect().isValid()


def test_corrupted_mask_asset_is_reported_and_rejected(window):
    layer = next(layer for layer in window.document.layers if layer.kind == "image")
    count = window.undo_stack.count()

    def corrupt(doc):
        doc.layer(layer.id).mask = "e" * 32
        doc.assets["e" * 32] = b"not a png"

    reported = []
    window._report_failure = lambda description, exc: reported.append(str(exc))
    assert not window.mutate("Masque abîmé", corrupt)
    assert reported and window.undo_stack.count() == count and not window.refreshing


def test_selection_ops_without_selection_or_layer_are_harmless(window):
    window.select_layer(None)
    window.last_selected_id = None
    count = window.undo_stack.count()
    window.clear_selection_content()
    window.reveal_selection_in_mask()
    window.remove_layer_mask()
    assert not window.selection_to_new_layer(cut=True)
    window.remove_background()
    assert window.undo_stack.count() == count


def test_selection_on_heavily_scaled_down_layer(window):
    document = Document(200, 200)
    layer = document.add_image_bytes(png_bytes(400, 400, (0, 0, 255, 255)), "Grand", center=False)
    layer.sx = layer.sy = 0.25  # displayed as 100 × 100
    window.install_document(document, layer.id)
    window.set_selection(S.rectangle((200, 200), (0, 0, 50, 100)), "test")
    window.clear_selection_content()
    rendered = render_layers(window.document, [layer.id])
    assert rendered.getpixel((25, 50))[3] == 0 and rendered.getpixel((75, 50))[3] == 255


def test_inline_editor_is_dropped_when_history_changes_the_scene(window):
    text = window.document.add_text("Avant")
    window.install_document(window.document, text.id)
    window.begin_inline_text_edit(text.id)
    window.mutate("Autre action", lambda doc: setattr(doc, "width", 640))
    assert window._inline is None and window.document.layer(text.id).text == "Avant"


# --- Memory: images and masks no layer uses any more ------------------------------------

def test_deleted_layers_and_replaced_masks_leave_no_image_behind(window):
    document = Document(50, 50)
    kept = document.add_image_bytes(png_bytes(20, 20), "gardé")
    removed = document.add_image_bytes(png_bytes(20, 20), "supprimé")
    window.install_document(document, kept.id)
    window.undo_stack.clear()
    window.select_layer(removed.id)
    window.delete_layer()
    assert set(window.document.assets) == {kept.asset}
    for _ in range(3):  # each masking writes a new mask; the previous one is forgotten
        window.selection_mask = S.rectangle((50, 50), (0, 0, 10, 10), False)
        window.select_layer(kept.id)
        window.clear_selection_content()
        window.selection_mask = S.invert(S.rectangle((50, 50), (0, 0, 10, 10), False))
        window.reveal_selection_in_mask()
    assert len(window.document.assets) <= 2
    while window.undo_stack.canUndo():
        window.undo_stack.undo()
    assert window.document.layer(removed.id) is not None  # undo still has its snapshot
    assert removed.asset in window.document.assets


def test_huge_images_are_refused_with_the_application_message():
    import io

    from PIL import Image
    output = io.BytesIO()
    Image.new("1", (16000, 12000)).save(output, format="PNG")  # Pillow's own bomb guard trips first
    with pytest.raises(ValueError, match="Image trop grande"):
        Document(10, 10).add_image_bytes(output.getvalue(), "énorme")


# --- Eraser placement ------------------------------------------------------------------

def _erase(point, size, centered):
    from PIL import Image

    from app.graphics import apply_eraser_strokes
    stroke = {"points": [point], "size": size, "shape": "square", "pixel_art": True,
              "hardness": 100, "opacity": 100}
    if centered is not None:
        stroke["pixel_centered"] = centered
    erased = apply_eraser_strokes(Image.new("RGBA", (6, 1), (255, 0, 0, 255)), [stroke])
    return [x for x in range(6) if erased.getpixel((x, 0))[3] == 0]


@pytest.mark.parametrize("x, size, expected", [
    (1.2, 1, [1]), (1.7, 1, [1]), (1.2, 2, [0, 1]), (1.7, 2, [1, 2]), (2.5, 3, [1, 2, 3]),
])
def test_new_eraser_strokes_cover_the_pixel_under_the_pointer(x, size, expected):
    assert _erase([x, 0.5], size, True) == expected


def test_older_eraser_strokes_keep_their_placement():
    assert _erase([1.7, 0.5], 1, None) == [2]  # projects saved before the fix look the same


def test_trimming_a_layer_with_new_strokes_keeps_its_look_for_any_shift():
    from PIL import Image

    from app.graphics import crop_image_layer, render_layer_with_mask
    document = Document(40, 40)
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    image.paste((0, 200, 0, 255), (3, 5, 17, 15))
    import io
    output = io.BytesIO()
    image.save(output, format="PNG")
    layer = document.add_image_bytes(output.getvalue(), "trim", center=False)
    layer.eraser_strokes = [{"points": [[8.3, 9.6], [12.7, 9.6]], "size": 3, "shape": "square",
                             "pixel_art": True, "hardness": 100, "opacity": 100, "pixel_centered": True}]
    trimmed, _assets = crop_image_layer(layer, document, (3, 5, 17, 15))  # odd shift: allowed now
    probe = Document(40, 40, None, [trimmed], {**document.assets, **_assets})
    expected = render_layer_with_mask(layer, document).crop((3, 5, 17, 15))
    assert render_layer_with_mask(trimmed, probe).tobytes() == expected.tobytes()
    assert (trimmed.x, trimmed.y) == (3, 5)
