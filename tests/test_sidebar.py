"""Left panel: readable text on its light illustration."""
import pytest

pytest.importorskip("PySide6")


def _luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = (channel(v) for v in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def test_subtitle_and_document_size_are_dark_on_the_light_top_of_the_panel(window):
    from PIL import Image
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QLabel

    from app.theme import COLORS
    from app.window_panels import ASSETS

    subtitle = next(label for label in window.left_panel.findChildren(QLabel)
                    if label.text().startswith("Éditeur d'images"))
    assert subtitle.objectName() == "brandSubtitle" and window.doc_info.objectName() == "docInfo"
    ink = QColor(COLORS["sidebar_ink"])
    with Image.open(ASSETS / "sidebar_ocean.png") as illustration:
        top = illustration.convert("RGB").crop((0, 0, illustration.width, illustration.height // 5))
        lightest = max(top.resize((8, 4)).get_flattened_data(), key=_luminance)
    light, dark = _luminance(lightest), _luminance((ink.red(), ink.green(), ink.blue()))
    assert (light + 0.05) / (dark + 0.05) >= 4.5  # WCAG AA for normal text
