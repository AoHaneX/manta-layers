"""Windows packaging: notices in step with the pinned build and license texts collected."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_collector():
    # Loaded by path: "packaging" is also the name of a library installed with pytest.
    spec = importlib.util.spec_from_file_location("collect_licenses", ROOT / "packaging" / "collect_licenses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pins():
    text = (ROOT / "packaging" / "requirements-build.txt").read_text(encoding="utf-8")
    return {name.lower(): version for name, version in re.findall(r"^([A-Za-z0-9_.-]+)==(\S+)", text, re.M)}


@pytest.mark.parametrize("package, label", [
    ("pyside6-essentials", "PySide6-Essentials"), ("pillow", "Pillow"), ("pyinstaller", "PyInstaller")])
def test_the_notices_name_the_pinned_versions(package, label):
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    row = next(line for line in notices.splitlines() if line.startswith("|") and label in line.split("|")[1])
    assert f"| {_pins()[package]} |" in row


def test_the_lgpl_and_gpl_texts_are_complete():
    lgpl = (ROOT / "packaging" / "licenses" / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl = (ROOT / "packaging" / "licenses" / "GPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3, 29 June 2007" in lgpl
    assert "GNU GENERAL PUBLIC LICENSE" in gpl and "END OF TERMS AND CONDITIONS" in gpl


def test_license_texts_are_collected(tmp_path, monkeypatch):
    collector = _load_collector()
    # PyInstaller is only installed in the build environment.
    monkeypatch.setattr(collector, "PACKAGE_LICENSES", [("pillow", "LICENSE", "Pillow-LICENSE.txt")])
    names = sorted(path.name for path in collector.collect(tmp_path / "licenses"))
    assert names == ["GPL-3.0.txt", "LGPL-3.0.txt", "Pillow-LICENSE.txt", "Python-LICENSE.txt"]
    assert "libjpeg-turbo" in (tmp_path / "licenses" / "Pillow-LICENSE.txt").read_text(encoding="utf-8")


def test_a_missing_license_stops_the_build(tmp_path, monkeypatch):
    collector = _load_collector()
    monkeypatch.setattr(collector, "PACKAGE_LICENSES", [("pillow", "ABSENT.txt", "x.txt")])
    with pytest.raises(FileNotFoundError):
        collector.collect(tmp_path)
