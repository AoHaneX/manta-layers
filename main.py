"""Point d'entrée de l'application Manta Layers."""
from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_windows_taskbar() -> None:
    """Donne à Windows une identité stable pour l'icône de la barre des tâches."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "BlueShrimp.ReefKit.MantaLayers"
        )
    except (AttributeError, OSError):
        pass


def main() -> int:
    configure_windows_taskbar()
    # Started without a console: errors go to a log file in the user data folder.
    from app.diagnostics import LOGGER_NAME, install_error_reporting
    log_file = install_error_reporting()
    logger = logging.getLogger(LOGGER_NAME)
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        logger.error("PySide6 is missing")
        print("PySide6 est absent. Sous Windows, lancez installer_dependances.bat puis lancer_manta_layers.bat")
        return 2

    app = QApplication(sys.argv)
    app.setApplicationName("Manta Layers")
    app.setOrganizationName("Blue Shrimp · ReefKit")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'manta.png')))
    try:
        from app import __version__
        from app.window import MainWindow
        logger.info("Manta Layers %s started", __version__)
        window = MainWindow()
        window.show()
    except Exception as exc:
        logger.exception("Start-up failed")
        details = f"\n\nDétails : {log_file}" if log_file else ""
        QMessageBox.critical(None, "Manta Layers — Démarrage impossible", f"{exc}{details}")
        return 1
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
