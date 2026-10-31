"""Shared pytest fixtures: an offscreen Qt application and an isolated main window."""
import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def png_bytes(width, height, color=(200, 10, 10, 255)):
    output = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture(scope="session")
def qapp():
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    """Main window whose settings and recovery files live in a temporary folder."""
    from PySide6.QtCore import QSettings

    from app.window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings, recovery_dir=tmp_path / "recovery")
    win.resize(1400, 860)
    win.show()
    qapp.processEvents()
    yield win
    win.undo_stack.setClean()
    win.close()
    qapp.processEvents()
