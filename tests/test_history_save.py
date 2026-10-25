"""Project format versions, verified saves, undo history and session recovery."""
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app import storage
from app.model import PROJECT_VERSION, Document
from app.storage import open_project, save_project
from conftest import png_bytes

ROOT = Path(__file__).resolve().parent.parent


def write_manifest(path, manifest, assets=()):
    with ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for asset_id, data in assets:
            archive.writestr(f"assets/{asset_id}.png", data)


def test_version_1_project_with_legacy_text_opens(tmp_path):
    asset = "a" * 32
    path = tmp_path / "ancien.mcrab"
    write_manifest(path, {
        "format": "MantaCrab", "version": 1, "width": 64, "height": 32, "background": None,
        "layers": [
            {"id": "img", "kind": "image", "asset": asset, "name": "Image"},
            {"id": "txt", "kind": "text", "text": "Arc", "text_deformation": "arc_down", "curve_intensity": 40},
            {"id": "old", "kind": "text", "text": "Droit", "text_deformation": "curve", "curve_intensity": 0},
        ],
    }, [(asset, png_bytes(4, 4))])
    document = open_project(path)
    assert document.layer("txt").text_deformation == "arc" and document.layer("txt").curve_intensity == -40
    assert document.layer("old").text_deformation == "straight"
    assert document.layer("img").mask is None and document.layer("txt").path_controls


def test_bundled_example_still_opens():
    document = open_project(ROOT / "exemples" / "Manta_Demo.manta")
    assert document.layers


def test_projects_from_newer_versions_are_refused_clearly(tmp_path):
    path = tmp_path / "futur.manta"
    write_manifest(path, {"format": "MantaLayers", "version": PROJECT_VERSION + 1,
                          "width": 4, "height": 4, "layers": []})
    with pytest.raises(ValueError, match="plus récente"):
        open_project(path)


@pytest.mark.parametrize("payload", [b"pas un zip", b""])
def test_invalid_files_are_detected(tmp_path, payload):
    path = tmp_path / "abime.manta"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        open_project(path)


def test_saves_use_the_current_version(tmp_path):
    path = tmp_path / "neuf.manta"
    save_project(Document(10, 10), path)
    with ZipFile(path) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == PROJECT_VERSION


def test_failed_verification_keeps_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "projet.manta"
    save_project(Document(10, 10), path)
    original = path.read_bytes()

    def corrupted(_path):
        raise ValueError("archive illisible")

    monkeypatch.setattr(storage, "open_project", corrupted)
    with pytest.raises(ValueError, match="vérification"):
        save_project(Document(20, 20), path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_mask_file_is_tolerated(tmp_path):
    asset, mask = "b" * 32, "c" * 32
    path = tmp_path / "sans-masque.manta"
    write_manifest(path, {"format": "MantaLayers", "version": 2, "width": 8, "height": 8,
                          "layers": [{"id": "i", "kind": "image", "asset": asset, "mask": mask}]},
                   [(asset, png_bytes(2, 2))])
    assert open_project(path).layer("i").mask is None


# --- History ------------------------------------------------------------------------

def image_layer(window):
    return next(layer for layer in window.document.layers if layer.kind == "image")


def test_arrow_key_bursts_merge_into_one_undo_step(window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    import app.window as window_module
    layer = image_layer(window)
    window.select_layer(layer.id)
    start_x, count = layer.x, window.undo_stack.count()
    clock = iter([100.0, 100.2, 100.4, 102.0])
    monkeypatch.setattr(window_module.time, "monotonic", lambda: next(clock))
    window.canvas.setFocus()
    for key in (Qt.Key.Key_Right, Qt.Key.Key_Right, Qt.Key.Key_Right):
        QTest.keyClick(window.canvas, key)
    assert window.document.layer(layer.id).x == start_x + 3
    assert window.undo_stack.count() == count + 1
    QTest.keyClick(window.canvas, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)  # after a pause
    assert window.undo_stack.count() == count + 2
    window.undo_stack.undo()
    window.undo_stack.undo()
    assert window.document.layer(layer.id).x == start_x


def test_locked_layers_are_not_nudged(window):
    layer = image_layer(window)
    window.select_layer(layer.id)
    window.toggle_lock(layer.id)
    assert not window.nudge_layer(5, 0)


def test_undo_covers_text_edits_transforms_and_selections_in_order(window):
    from app import selection as S
    layer = image_layer(window)
    window.select_layer(layer.id)
    window.nudge_layer(4, 0)
    window.select_all()
    window.mutate("Renommer", lambda doc: setattr(doc.layer(layer.id), "name", "Nouveau"), layer.id)
    window.undo_stack.undo()
    assert window.document.layer(layer.id).name != "Nouveau" and window.selection_mask is not None
    window.undo_stack.undo()
    assert window.selection_mask is None
    window.undo_stack.redo()
    assert S.bounds(window.selection_mask) == (0, 0, window.document.width, window.document.height)


# --- Session recovery -------------------------------------------------------------------

def test_autosave_only_when_there_are_unsaved_changes(window):
    assert not window.autosave_now()  # clean document
    window.mutate("Agrandir", lambda doc: setattr(doc, "width", 300))
    assert window.autosave_now()
    assert not window.autosave_now()  # nothing new since the last copy
    project, meta = window._recovery_files(window._session_id)
    assert project.is_file() and json.loads(meta.read_text())["saved_at"] > 0


def test_saving_or_closing_removes_the_recovery_copy(window, tmp_path, monkeypatch):
    window.mutate("x", lambda doc: setattr(doc, "width", 300))
    window.autosave_now()
    project, _meta = window._recovery_files(window._session_id)
    monkeypatch.setattr(window, "project_path", tmp_path / "projet.manta")
    assert window.save_document()
    assert not project.exists()


def make_window(qapp, tmp_path, recovery):
    from PySide6.QtCore import QSettings
    from app.window import MainWindow
    return MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                      recovery_dir=recovery)


def crashed_copy(recovery: Path, width=321, project_path=None):
    recovery.mkdir(parents=True, exist_ok=True)
    save_project(Document(width, 50), recovery / "dead.manta")
    (recovery / "dead.json").write_text(json.dumps({"saved_at": 1_700_000_000, "project_path": project_path}))


def test_copy_left_by_a_crash_is_offered_and_restored(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    recovery = tmp_path / "recovery"
    crashed_copy(recovery, project_path=str(tmp_path / "mon-projet.manta"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()  # the offer runs once the window is built
    try:
        assert window.document.width == 321
        assert not window.undo_stack.isClean()  # restored work still has to be saved
        assert window.project_path == tmp_path / "mon-projet.manta"
        assert not (recovery / "dead.manta").exists()
    finally:
        window.undo_stack.setClean()
        window.close()


def test_declined_recovery_deletes_the_copy(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    recovery = tmp_path / "recovery"
    crashed_copy(recovery)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()
    try:
        assert window.document.width != 321 and not (recovery / "dead.manta").exists()
    finally:
        window.close()


def test_copies_of_running_sessions_are_left_alone(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    recovery = tmp_path / "recovery"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("offered a live session"))
    first = make_window(qapp, tmp_path, recovery)
    first.mutate("x", lambda doc: setattr(doc, "width", 222))
    assert first.autosave_now()
    second = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()
    try:
        assert second.recovery_candidates() == []
    finally:
        for window in (first, second):
            window.undo_stack.setClean()
            window.close()
