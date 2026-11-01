"""Error log of the application: the launcher runs it without a console (pythonw).

Unhandled exceptions, Qt warnings and hard crashes are written to
``<user data>/logs`` so that a problem met by the user can still be diagnosed.
The content of documents is never logged.
"""
from __future__ import annotations

import faulthandler
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import user_data_directory

LOGGER_NAME = "manta"
LOG_FILE = "manta.log"
CRASH_FILE = "crash.log"

_state: dict = {"crash_file": None, "reporting": False}


def log_directory() -> Path:
    return user_data_directory() / "logs"


def install_error_reporting(directory: Path | None = None, show_dialog: bool = True) -> Path | None:
    """Log unhandled exceptions, Qt messages and crashes; returns the log file, None if it cannot be written."""
    directory = Path(directory) if directory is not None else log_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        # Kept open for the whole session: faulthandler writes to it while crashing.
        crash_file = open(directory / CRASH_FILE, "a", encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger(LOGGER_NAME)
    for previous in list(logger.handlers):
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Native crashes (access violations, Qt fatal aborts) cannot reach Python code.
    if _state["crash_file"] is not None:
        _state["crash_file"].close()
    _state["crash_file"] = crash_file
    faulthandler.enable(file=crash_file)

    log_file = directory / LOG_FILE
    sys.excepthook = lambda kind, value, tb: report_exception(kind, value, tb, log_file, show_dialog)
    _install_qt_message_handler(logger)
    return log_file


def report_exception(kind, value, tb, log_file: Path | None = None, show_dialog: bool = True) -> None:
    """Log an unhandled exception, print it when a console exists, and warn the user once at a time."""
    details = "".join(traceback.format_exception(kind, value, tb))
    logging.getLogger(LOGGER_NAME).error("Unhandled exception\n%s", details)
    if sys.stderr is not None:
        sys.stderr.write(details)
    if not show_dialog or _state["reporting"]:
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    if QApplication.instance() is None:
        return
    _state["reporting"] = True  # a failure while the message is shown must not stack dialogs
    try:
        where = f"\n\nDétails enregistrés dans :\n{log_file}" if log_file else ""
        QMessageBox.warning(
            None, "Manta Layers — Erreur inattendue",
            f"Une erreur inattendue s'est produite : {value}\n\n"
            f"Enregistrez votre projet sous un nouveau nom par précaution.{where}",
        )
    finally:
        _state["reporting"] = False


def _install_qt_message_handler(logger: logging.Logger) -> None:
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(kind, _context, message):
        logger.log(levels.get(kind, logging.WARNING), "Qt: %s", message)
        if sys.stderr is not None:  # "--console" keeps showing Qt messages
            sys.stderr.write(f"{message}\n")
        if kind == QtMsgType.QtFatalMsg:
            for log_handler in logger.handlers:
                log_handler.flush()

    qInstallMessageHandler(handler)
