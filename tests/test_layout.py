"""Window layout on short screens."""
from PySide6.QtWidgets import QPushButton, QScrollArea


def test_left_panel_scrolls_on_short_screens(window, qapp):
    # 1080p at 150 % leaves about 1280 x 670 logical pixels for the window.
    window.resize(1000, 600)
    qapp.processEvents()
    assert window.height() <= 600
    scroll = window.left_panel.findChild(QScrollArea, "leftPanelScroll")
    content = scroll.widget()
    assert scroll.verticalScrollBar().maximum() > 0
    # The content keeps the visible width: labels are never cut on the right.
    assert content.width() <= scroll.viewport().width()
    buttons = [button for button in content.findChildren(QPushButton) if button.isVisibleTo(content)]
    save_image = next(button for button in buttons if button.text() == "Sauvegarder l'image")
    scroll.ensureWidgetVisible(save_image)
    qapp.processEvents()
    top_left = save_image.mapTo(scroll.viewport(), save_image.rect().topLeft())
    assert 0 <= top_left.y() and top_left.y() + save_image.height() <= scroll.viewport().height()


def test_left_panel_does_not_scroll_when_there_is_room(window, qapp):
    window.resize(1400, 1000)
    qapp.processEvents()
    scroll = window.left_panel.findChild(QScrollArea, "leftPanelScroll")
    assert scroll.verticalScrollBar().maximum() == 0
