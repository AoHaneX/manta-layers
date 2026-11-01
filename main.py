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


# Same lower bound as requirements.txt: older releases have known image decoding flaws.
MINIMUM_PILLOW = 13


def outdated_pillow() -> str | None:
    """Installed Pillow version when it predates the security fixes required by requirements.txt."""
    try:
        from PIL import __version__ as version
    except ImportError:
        return None
    try:
        major = int(version.split(".")[0])
    except ValueError:
        return None
    return version if major < MINIMUM_PILLOW else None


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
    old_pillow = outdated_pillow()
    if old_pillow:
        QMessageBox.warning(
            window, "Bibliothèques à mettre à jour",
            f"Pillow {old_pillow} est installé ; Manta Layers demande Pillow {MINIMUM_PILLOW} ou plus récent, "
            "qui corrige des failles de sécurité dans la lecture des images.\n\n"
            "Fermez Manta Layers puis lancez installer_dependances.bat.",
        )
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
