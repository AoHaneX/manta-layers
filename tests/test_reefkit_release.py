"""Tests of packaging/reefkit_release.py, the release convention read by RiftKit Launcher.

Keep this file identical in every ReefKit application repository, like the helper itself.
"""

import dataclasses
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "packaging" / "reefkit_release.py"
spec = importlib.util.spec_from_file_location("reefkit_release", HELPER)
release = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release  # dataclasses look their module up while the class is created
spec.loader.exec_module(release)


@pytest.fixture
def config():
    return release.Config.load()


@pytest.fixture
def version(config):
    return release.read_version(config)


def make_portable(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in entries.items():
            entry = zipfile.ZipInfo(name)
            entry.filename = name  # ZipInfo turns "\" into "/" on Windows: keep the name as written
            bundle.writestr(entry, data)
    return path


def make_release(config, version, directory: Path, installer: bool = True) -> Path:
    make_portable(
        directory / config.portable(version),
        {config.executable: b"MZ", "_internal/base_library.zip": b"lib"},
    )
    if installer:
        (directory / config.setup(version)).write_bytes(b"MZ setup")
    return directory


def test_repository_configuration_follows_the_convention(config, version):
    assert config.portable(version) == f"{config.app_name}-v{version}-win64.zip"
    assert config.setup(version) == f"{config.app_name}-v{version}-setup.exe"
    assert release.read_version(config, f"v{version}") == version


def test_tag_must_match_the_code_version(config, version):
    with pytest.raises(release.ReleaseError, match="ne correspond pas"):
        release.read_version(config, f"v{version}.1")
    with pytest.raises(release.ReleaseError, match="ne correspond pas"):
        release.read_version(config, version)


def test_finalize_writes_checksums_and_structured_notes(config, version, tmp_path):
    make_release(config, version, tmp_path, installer=config.installer)
    lines = release.finalize(config, tmp_path, f"v{version}", allow_missing_installer=False)

    sums = (tmp_path / "SHA256SUMS.txt").read_bytes()
    assert b"\r" not in sums
    assert sums.decode("ascii").splitlines() == lines
    assert release.verify(config, tmp_path) == [f"OK  {line.split('  ')[1]}" for line in lines]
    notes = (tmp_path / "release-notes.md").read_text(encoding="utf-8")
    for heading in ("## Nouveautés", "## Téléchargements", "## Installation", "## Vérifier l'intégrité"):
        assert heading in notes
    assert release.sha256(tmp_path / config.portable(version)) in notes


def test_verify_detects_a_modified_file(config, version, tmp_path):
    make_release(config, version, tmp_path, installer=config.installer)
    release.finalize(config, tmp_path, None, allow_missing_installer=False)
    (tmp_path / config.portable(version)).write_bytes(b"tampered")
    with pytest.raises(release.ReleaseError, match="Empreinte"):
        release.verify(config, tmp_path)


def test_verify_rejects_legacy_asset_names(config, version, tmp_path):
    legacy = tmp_path / f"{config.app_name}-{version}-Windows-Portable.zip"
    legacy.write_bytes(b"zip")
    (tmp_path / "SHA256SUMS.txt").write_text(f"{release.sha256(legacy)}  {legacy.name}\n", encoding="ascii")
    with pytest.raises(release.ReleaseError, match="hors convention"):
        release.verify(config, tmp_path)


def test_executable_must_be_at_the_root_of_the_archive(config, tmp_path):
    archive = make_portable(tmp_path / "a.zip", {f"{config.app_name}/{config.executable}": b"MZ"})
    with pytest.raises(release.ReleaseError, match="racine"):
        release.check_portable(config, archive)


@pytest.mark.parametrize("name", ["_internal\\Qt6Core.dll", "../evil.dll", "/abs.dll", "C:/x.dll"])
def test_archive_paths_must_be_portable(config, tmp_path, name):
    archive = make_portable(tmp_path / "a.zip", {config.executable: b"MZ", name: b"x"})
    with pytest.raises(release.ReleaseError, match="non portable"):
        release.check_portable(config, archive)


def test_missing_installer_is_an_error_unless_allowed(config, version, tmp_path):
    if not config.installer:
        pytest.skip("this application has no installer")
    make_release(config, version, tmp_path, installer=False)
    with pytest.raises(release.ReleaseError, match="Installeur absent"):
        release.finalize(config, tmp_path, None, allow_missing_installer=False)
    assert len(release.finalize(config, tmp_path, None, allow_missing_installer=True)) == 1


def test_changelog_section_is_used_as_release_notes(config, tmp_path, monkeypatch):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Historique\n\n## 2.1.0 — novembre 2026\n\n### Ajouts\n\n- Nouveau.\n\n## 2.0.0\n\n- Ancien.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release, "ROOT", tmp_path)
    with_changelog = dataclasses.replace(config, changelog="CHANGELOG.md")
    assert release.changelog_section(with_changelog, "2.1.0") == "### Ajouts\n\n- Nouveau."
    assert release.changelog_section(with_changelog, "2.0.0") == "- Ancien."
    assert release.changelog_section(with_changelog, "3.0.0") is None


def test_version_sources_must_agree(config, tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('version = "1.2.4"\n', encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    sources = [
        {"file": "a.py", "pattern": r'__version__ = "([^"]+)"'},
        {"file": "b.toml", "pattern": r'^version = "([^"]+)"'},
    ]
    with pytest.raises(release.ReleaseError, match="ne concordent pas"):
        release.read_version(dataclasses.replace(config, version_sources=sources))
