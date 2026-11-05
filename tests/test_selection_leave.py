"""Leaving the selection tools removes the selection outline; Ctrl+Z brings it back."""
import io

import pytest

pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402

from app.model import Document  # noqa: E402


def small_document(window):
    output = io.BytesIO()
    Image.new("RGBA", (10, 10), (40, 200, 120, 255)).save(output, format="PNG")
    document = Document(50, 50)
    layer = document.add_image_bytes(output.getvalue(), "x", center=False)
    window.install_document(document, layer.id)


@pytest.mark.parametrize("leave", [
    lambda w: w.set_eraser_active(True),
    lambda w: w.selection_tool_buttons["ellipse"].click(),
    lambda w: w.shape_tool_buttons["rectangle"].click(),
    lambda w: w.tabs.setCurrentIndex(0),
])
def test_leaving_the_selection_tools_removes_the_outline_and_undo_restores_it(window, leave):
    small_document(window)
    window.set_selection_tool("ellipse")
    window.apply_selection_shape("ellipse", QRectF(QPointF(5, 5), QPointF(30, 30)), Qt.KeyboardModifier.NoModifier)
    assert window.selection_mask is not None
    leave(window)
    assert window.selection_tool is None
    assert window.selection_mask is None and window.canvas.selection_path is None
    window.undo_stack.undo()
    assert window.selection_mask is not None


def test_switching_between_selection_tools_keeps_the_selection(window):
    window.set_selection_tool("rect")
    window.select_all()
    window.canvas.lasso_points = [QPointF(1, 1), QPointF(5, 1)]
    window.set_selection_tool("wand")
    assert window.selection_mask is not None
    assert window.canvas.lasso_points is None  # the outline being drawn belonged to the lasso


def test_a_selection_made_from_the_menu_without_tool_is_kept(window):
    window.select_all()
    window.set_eraser_active(True)
    assert window.selection_mask is not None
