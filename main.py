"""Point d'entrée de l'application Manta Layers."""
from __future__ import annotations

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
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("PySide6 est absent. Sous Windows, lancez installer_dependances.bat puis lancer_manta_layers.bat")
        return 2

    app = QApplication(sys.argv)
    app.setApplicationName("Manta Layers")
    app.setOrganizationName("Blue Shrimp · ReefKit")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / 'assets' / 'manta.png')))
    try:
        from app.window import MainWindow
        window = MainWindow()
        window.show()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        QMessageBox.critical(None, "Manta Layers — Démarrage impossible", str(exc))
        return 1
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
