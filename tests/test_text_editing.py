"""Text layers edited on the canvas: shapes, handles, inline typing and history."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app.graphics import CurvedTextGraphicItem  # noqa: E402
from app.model import Document  # noqa: E402
from app.storage import open_project, save_project  # noqa: E402


def install_text(window, text="Manta", **values):
    document = Document(800, 500)
    layer = document.add_text(text)
    layer.x, layer.y = 200, 200
    for key, value in values.items():
        setattr(layer, key, value)
    window.install_document(document, layer.id)
    window.undo_stack.clear()
    return layer.id


def viewport_point(window, item, local: QPointF) -> QPoint:
    return window.canvas.mapFromScene(item.mapToScene(local))


def test_shape_combo_changes_shape_in_one_undoable_step(window):
    layer_id = install_text(window, curve_intensity=-40.0, text_deformation="arc")
    window.text_shape_combo.setCurrentIndex(window.text_shape_combo.findData("u"))
    layer = window.document.layer(layer_id)
    assert (layer.text_deformation, layer.curve_intensity) == ("u", 40.0)
    assert isinstance(window.canvas.graphic_for(layer_id), CurvedTextGraphicItem)
    window.undo_stack.undo()
    assert window.document.layer(layer_id).text_deformation == "arc"


def test_dragging_a_custom_handle_on_the_canvas(window):
    layer_id = install_text(window, text_deformation="custom")
    item = window.canvas.graphic_for(layer_id)
    window.canvas.resetTransform()
    start_handle = item.shape_handles_local()[1]
    start = viewport_point(window, item, start_handle)
    end = start + QPoint(0, 60)
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), pos=start + QPoint(0, 30))
    QTest.mouseMove(window.canvas.viewport(), pos=end)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    controls = window.document.layer(layer_id).path_controls
    assert controls[1][1] > 0.2  # moved down from the default 0.2
    assert controls[0] == [0.25, -0.2]
    assert window.undo_stack.count() == 1
    window.undo_stack.undo()
    assert window.document.layer(layer_id).path_controls[1] == [0.75, 0.2]


def test_dragging_the_apex_of_a_straight_text_bends_it(window):
    layer_id = install_text(window)
    item = window.canvas.graphic_for(layer_id)
    start = viewport_point(window, item, item.shape_handles_local()[0])
    end = start - QPoint(0, 40)
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), pos=end)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    layer = window.document.layer(layer_id)
    assert layer.text_deformation == "arc" and layer.curve_intensity > 0
    assert window.curve_intensity.value() == round(layer.curve_intensity)


def test_inline_edit_commits_multiline_text_and_can_be_undone(window):
    layer_id = install_text(window, text="Avant")
    window.begin_inline_text_edit(layer_id)
    editor = window._inline["editor"]
    editor.setPlainText("Ligne 1\nLigne 2")
    assert window._inline["item"].lines == ["Ligne 1", "Ligne 2"]  # live preview
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert window._inline is None
    assert window.document.layer(layer_id).text == "Ligne 1\nLigne 2"
    window.undo_stack.undo()
    assert window.document.layer(layer_id).text == "Avant"


def test_inline_edit_escape_restores_the_text(window):
    layer_id = install_text(window, text="Garder")
    window.begin_inline_text_edit(layer_id)
    editor = window._inline["editor"]
    item = window._inline["item"]
    editor.setPlainText("Jeté")
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert window.document.layer(layer_id).text == "Garder"
    assert item.lines == ["Garder"]
    assert window.undo_stack.count() == 0


def test_typing_tool_letters_in_the_editor_does_not_switch_tools(window):
    layer_id = install_text(window)
    window.begin_inline_text_edit(layer_id)
    QTest.keyClicks(window._inline["editor"], "et")
    assert not window.eraser_active and not window.text_tool_active


def test_double_click_on_a_text_opens_the_editor(window):
    layer_id = install_text(window)
    item = window.canvas.graphic_for(layer_id)
    QTest.mouseDClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                      pos=viewport_point(window, item, item.boundingRect().center()))
    assert window._inline is not None and window._inline["layer_id"] == layer_id


def test_text_tool_creates_a_text_at_the_click(window):
    window.install_document(Document(800, 500), None)
    window.undo_stack.clear()
    window.set_text_tool_active(True)
    click = window.canvas.mapFromScene(QPointF(300, 250))
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=click)
    editor = window._inline["editor"]
    QTest.keyClicks(editor, "Bonjour")
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(window.document.layers) == 1
    layer = window.document.layers[0]
    assert layer.text == "Bonjour" and layer.kind == "text"
    assert layer.x == pytest.approx(300, abs=2)
    assert window.selected_id == layer.id and window.undo_stack.count() == 1
    # The temporary preview item is gone: one graphic per layer.
    assert len(window.canvas.scene().items()) == 1


def test_text_tool_with_empty_text_creates_nothing(window):
    window.install_document(Document(800, 500), None)
    window.set_text_tool_active(True)
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.canvas.mapFromScene(QPointF(100, 100)))
    QTest.keyClick(window._inline["editor"], Qt.Key.Key_Escape)
    assert window.document.layers == [] and len(window.canvas.scene().items()) == 0


def test_upright_letters_option_is_saved(window):
    layer_id = install_text(window, text_deformation="u", curve_intensity=70.0)
    window.upright_letters.click()
    assert window.document.layer(layer_id).path_orientation == "horizontal"
    item = window.canvas.graphic_for(layer_id)
    assert all(angle == 0 for *_rest, angle in item.placements)


def test_text_shape_survives_save_and_reopen(tmp_path):
    document = Document(600, 400)
    text = document.add_text("Courbe\nlibre")
    text.text_deformation, text.path_controls = "custom", [[0.1, -0.6], [0.9, 0.4]]
    text.path_orientation = "horizontal"
    path = tmp_path / "texte.manta"
    save_project(document, path)
    restored = open_project(path).layer(text.id)
    assert (restored.text, restored.text_deformation, restored.path_controls, restored.path_orientation) == \
        ("Courbe\nlibre", "custom", [[0.1, -0.6], [0.9, 0.4]], "horizontal")


def test_text_stays_vector_at_any_zoom(window):
    layer_id = install_text(window, text_deformation="arc", curve_intensity=50.0)
    item = window.canvas.graphic_for(layer_id)
    before = item.boundingRect()
    window.canvas.zoom_by(20)
    assert item.boundingRect() == before  # geometry is resolution independent
