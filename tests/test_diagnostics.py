"""Error log of an application started without a console, and start-up checks."""
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

from app import diagnostics


@pytest.fixture
def error_log(tmp_path, monkeypatch):
    from PySide6.QtCore import qInstallMessageHandler

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # restored after the test
    monkeypatch.setattr(diagnostics.faulthandler, "enable", lambda file: None)  # pytest keeps its own
    log_file = diagnostics.install_error_reporting(tmp_path / "logs", show_dialog=False)
    yield log_file
    qInstallMessageHandler(None)
    logger = diagnostics.logging.getLogger(diagnostics.LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    diagnostics._state["crash_file"].close()
    diagnostics._state["crash_file"] = None


def test_unhandled_exceptions_are_logged(error_log):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    text = error_log.read_text(encoding="utf-8")
    assert "Unhandled exception" in text and "RuntimeError: boom" in text


def test_qt_warnings_are_logged(error_log, qapp):
    from PySide6.QtCore import qWarning

    qWarning("audit warning")
    assert "Qt: audit warning" in error_log.read_text(encoding="utf-8")


def test_the_user_is_warned_once_per_error(monkeypatch, qapp):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))
    try:
        raise ValueError("inattendu")
    except ValueError:
        diagnostics.report_exception(*sys.exc_info(), log_file=None, show_dialog=True)
    assert len(shown) == 1 and "inattendu" in shown[0]


def test_an_outdated_pillow_is_detected(monkeypatch):
    import PIL

    import main
    monkeypatch.setattr(PIL, "__version__", "12.3.0")
    assert main.outdated_pillow() == "12.3.0"
    monkeypatch.setattr(PIL, "__version__", "13.0.0")
    assert main.outdated_pillow() is None
