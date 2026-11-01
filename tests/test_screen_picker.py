"""Desktop-wide colour picker: sampling, scaling, sessions and their effect."""
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QMessageBox

from app import screen_picker
from app.model import Document
from app.screen_picker import ScreenColorPicker, sample_color


def capture(width, height, left_color, right_color):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(left_color))
    for x in range(width // 2, width):
        for y in range(height):
            image.setPixelColor(x, y, QColor(right_color))
    return image


def test_sampling_scales_positions_on_high_density_screens(qapp):
    image = capture(400, 200, "#112233", "#AABBCC")  # 200 % scaling of a 200 × 100 screen
    assert sample_color(image, QPointF(10, 10), QSize(200, 100)).name() == "#112233"
    assert sample_color(image, QPointF(150, 99.5), QSize(200, 100)).name() == "#aabbcc"
    assert sample_color(image, QPointF(200, 10), QSize(200, 100)) is None
    assert sample_color(QImage(), QPointF(1, 1), QSize(200, 100)) is None


class FakeScreen:
    def __init__(self, geometry, image):
        self._geometry, self._image = geometry, image

    def geometry(self):
        return self._geometry

    def grabWindow(self, _window_id):
        return QPixmap.fromImage(self._image) if not self._image.isNull() else QPixmap()


def test_a_session_covers_every_screen_and_frees_its_captures(qapp, monkeypatch):
    screens = [FakeScreen(QRect(0, 0, 100, 80), capture(100, 80, "#FF0000", "#00FF00")),
               FakeScreen(QRect(100, 0, 50, 40), capture(100, 80, "#0000FF", "#0000FF"))]
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: screens))
    picker = ScreenColorPicker()
    results = []
    picker.picked.connect(results.append)
    assert picker.start() and len(picker.overlays) == 2
    second = picker.overlays[1]
    assert second.color_at(QPointF(10, 10)).name() == "#0000ff"
    picker.finish(picker.overlays[0].color_at(QPointF(80, 10)))
    assert results == ["#00FF00"] and not picker.active and second.capture.isNull()


def test_escape_cancels_and_unavailable_screens_fail_cleanly(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "screens",
                        staticmethod(lambda: [FakeScreen(QRect(0, 0, 10, 10), capture(10, 10, "#000000", "#000000"))]))
    picker = ScreenColorPicker()
    cancelled = []
    picker.cancelled.connect(lambda: cancelled.append(True))
    picker.start()
    from PySide6.QtTest import QTest
    QTest.keyClick(picker.overlays[0], Qt.Key.Key_Escape)
    assert cancelled and not picker.active
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [FakeScreen(QRect(0, 0, 10, 10), QImage())]))
    failures = []
    picker.failed.connect(failures.append)
    assert not picker.start() and failures


def test_picked_colour_goes_to_the_tools_or_to_the_text_layer(window, monkeypatch):
    document = Document(50, 50)
    text = document.add_text("Couleur")
    window.install_document(document, text.id)
    window.undo_stack.clear()

    def fake_start(self):
        self.overlays = [object()]  # an active session
        return True

    monkeypatch.setattr(screen_picker.ScreenColorPicker, "start", fake_start)
    assert window.start_screen_picker()
    window._screen_picker.overlays = []
    window._screen_picker.picked.emit("#13579B")
    assert window.replacement_color == "#13579B" and window.undo_stack.count() == 0
    window.activate_picker("text", True)
    assert window.start_screen_picker()
    window._screen_picker.overlays = []
    window._screen_picker.picked.emit("#2468AC")
    assert window.document.layer(text.id).color == "#2468AC"
    assert window.undo_stack.count() == 1 and not window.picker_active


def test_failure_is_reported_without_side_effect(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: []))
    assert not window.start_screen_picker()
    assert warnings and window._screen_picker is None


def two_screens():
    return [FakeScreen(QRect(0, 0, 100, 80), capture(100, 80, "#FF0000", "#00FF00")),
            FakeScreen(QRect(100, 0, 50, 40), capture(100, 80, "#0000FF", "#0000FF"))]


def test_an_overlay_closed_from_outside_ends_the_session(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(two_screens))
    picker = ScreenColorPicker()
    cancelled = []
    picker.cancelled.connect(lambda: cancelled.append(True))
    assert picker.start()
    first, second = picker.overlays
    first.close()  # Alt+F4 or the window manager: the overlay deletes itself
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert cancelled == [True] and not picker.active
    assert not shiboken6.isValid(first) and not shiboken6.isValid(second)  # no frozen overlay left
    assert picker.start() and len(picker.overlays) == 2  # the tool is still available
    picker.cancel()
    assert cancelled == [True, True]


def test_an_overlay_deleted_behind_the_picker_is_skipped(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(two_screens))
    picker = ScreenColorPicker()
    cancelled = []
    picker.cancelled.connect(lambda: cancelled.append(True))
    assert picker.start()
    shiboken6.delete(picker.overlays[0])  # destroyed without any close event
    from PySide6.QtTest import QTest
    QTest.keyClick(picker.overlays[1], Qt.Key.Key_Escape)  # used to raise "already deleted"
    assert cancelled == [True] and not picker.active
