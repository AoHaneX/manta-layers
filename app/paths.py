"""Emplacements des données propres à l'utilisateur, hors du dossier de l'application."""
from __future__ import annotations

import os
import re
from pathlib import Path

# Characters Windows refuses in file names. A colon is worse than refused on
# NTFS: "a:b.png" silently writes into a hidden stream of a file named "a".
_FORBIDDEN_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL",
                   *(f"COM{index}" for index in range(1, 10)), *(f"LPT{index}" for index in range(1, 10))}


def user_data_directory() -> Path:
    """Dossier inscriptible même si l'application est installée en lecture seule."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "MantaLayers"


def safe_file_stem(name: str, fallback: str) -> str:
    """A file name stem built from a layer or document name, valid on Windows, macOS and Linux."""
    stem = _FORBIDDEN_CHARACTERS.sub("_", str(name)).strip(" .")
    if not stem:
        return fallback
    if stem.split(".")[0].rstrip(" ").upper() in _RESERVED_NAMES:
        stem = f"_{stem}"
    return stem
