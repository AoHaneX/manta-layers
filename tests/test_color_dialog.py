"""Colour dialogs: picking a hue in the square never leaves a black colour black."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget  # noqa: E402

from app.dialogs import ColorDialog  # noqa: E402
from app.model import Document  # noqa: E402


def part(dialog, class_name):
    return next(child for child in dialog.findChildren(QWidget) if child.metaObject().className() == class_name)


def click_square(dialog):
    square = part(dialog, "QtPrivate::QColorPicker")
    QTest.mouseClick(square, Qt.MouseButton.LeftButton, pos=QPoint(square.width() // 3, square.height() // 4))


def test_a_click_in_the_square_from_black_gives_a_visible_colour(qapp):
    dialog = ColorDialog(QColor("#000000"), None, "Couleur du texte")
    dialog.show()
    click_square(dialog)
    color = dialog.currentColor()
    assert color.value() == 255 and color.hsvSaturation() > 0
    dialog.close()


def test_the_brightness_slider_can_still_go_down_to_black(qapp):
    dialog = ColorDialog(QColor("#3366FF"), None, "Couleur")
    dialog.show()
    slider = part(dialog, "QtPrivate::QColorLuminancePicker")
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width() // 2, slider.height() - 1))
    assert dialog.currentColor().name() == "#000000"
    dialog.close()


def test_a_black_text_gets_the_hue_picked_in_the_square(window):
    document = Document(300, 120)
    layer = document.add_text("Bonjour")
    window.install_document(document, layer.id)
    assert window.document.layer(layer.id).color == "#000000"

    def choose():
        dialog = next((widget for widget in QApplication.topLevelWidgets()
                       if isinstance(widget, ColorDialog) and widget.isVisible()), None)
        if dialog is None:
            QTimer.singleShot(20, choose)
            return
        click_square(dialog)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, choose)
    window.color_btn.click()
    color = QColor(window.document.layer(layer.id).color)
    assert color.value() == 255 and color.hsvSaturation() > 0
    assert window.undo_stack.undoText() == "Couleur du texte"
