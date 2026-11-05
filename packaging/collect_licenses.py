"""Copy the full license texts of the bundled components next to the Windows build.

Run with the Python of the build environment (packaging/build.ps1 does it), so that
the copied texts are those of the exact versions embedded by PyInstaller:

    python packaging/collect_licenses.py dist/MantaLayers/licenses
"""
from __future__ import annotations

import shutil
import sys
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Distribution name, license file inside its metadata, name in the build.
PACKAGE_LICENSES = [
    ("pillow", "LICENSE", "Pillow-LICENSE.txt"),
    ("pyinstaller", "COPYING.txt", "PyInstaller-COPYING.txt"),
]


def package_license(distribution: str, file_name: str) -> Path:
    files = metadata.distribution(distribution).files or []
    for entry in files:
        if entry.name == file_name and "dist-info" in str(entry):
            return Path(str(entry.locate()))
    raise FileNotFoundError(f"{file_name} introuvable dans les métadonnées de {distribution}")


def collect(destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    sources = [(Path(sys.base_prefix) / "LICENSE.txt", "Python-LICENSE.txt")]
    sources += [(package_license(name, file_name), target) for name, file_name, target in PACKAGE_LICENSES]
    sources += [(path, path.name) for path in sorted((HERE / "licenses").glob("*.txt"))]
    written = []
    for source, target in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Licence introuvable : {source}")
        written.append(Path(shutil.copyfile(source, destination / target)))
    return written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage : python collect_licenses.py <dossier de destination>")
    for path in collect(Path(sys.argv[1])):
        print(path.name)
