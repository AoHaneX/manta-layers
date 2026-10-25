"""Emplacements des données propres à l'utilisateur, hors du dossier de l'application."""
from __future__ import annotations

import os
from pathlib import Path


def user_data_directory() -> Path:
    """Dossier inscriptible même si l'application est installée en lecture seule."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "MantaLayers"
