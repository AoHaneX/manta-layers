"""Project format versions, verified saves, undo history and session recovery."""
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from conftest import png_bytes

from app import storage
from app.model import COMPATIBLE_VERSION, PROJECT_VERSION, Document
from app.storage import open_project, save_project

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


def test_infinite_dimensions_are_reported_as_invalid(tmp_path):
    # JSON reads 1e400 as infinity.
    path = tmp_path / "infini.manta"
    with ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", '{"format": "MantaLayers", "version": 2, '
                                          '"width": 1e400, "height": 10, "layers": []}')
    with pytest.raises(ValueError):
        open_project(path)


def test_corrupted_compressed_image_is_reported_as_invalid(tmp_path):
    document = Document(8, 8)
    document.add_image_bytes(png_bytes(8, 8), "image")
    path = tmp_path / "abime.manta"
    save_project(document, path)
    data = bytearray(path.read_bytes())
    with ZipFile(path) as archive:
        entry = next(info for info in archive.infolist() if info.filename.startswith("assets/"))
    start = entry.header_offset + 30 + len(entry.filename) + len(entry.extra)
    for index in range(start + 2, start + min(entry.compress_size, 40)):
        data[index] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        open_project(path)


def test_saves_use_the_oldest_version_able_to_hold_the_project(tmp_path):
    # Folders and shapes need the current version; other projects stay readable by older releases.
    path = tmp_path / "neuf.manta"
    save_project(Document(10, 10), path)
    with ZipFile(path) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == COMPATIBLE_VERSION
    document = Document(10, 10)
    document.add_text("forme")
    document.layers[0].kind = "shape"
    save_project(document, path)
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


def wait_for_autosave(window, qapp, timeout=10):
    import time
    task = window._autosave_task
    assert task is not None and task.wait(timeout * 1000)
    deadline = time.monotonic() + timeout
    while window._autosave_task is not None and time.monotonic() < deadline:
        qapp.processEvents()  # delivers the end-of-thread notification
    assert window._autosave_task is None


def test_timer_autosave_runs_in_the_background(window, qapp, monkeypatch):
    import threading
    window.mutate("Agrandir", lambda doc: setattr(doc, "width", 300))
    threads = []
    real_save = storage.save_project

    def recording_save(*args, **kwargs):
        threads.append(threading.current_thread())
        return real_save(*args, **kwargs)

    monkeypatch.setattr("app.window.save_project", recording_save)
    assert window.autosave_now(background=True)
    assert not window.autosave_now(background=True)  # one copy at a time
    wait_for_autosave(window, qapp)
    project, meta = window._recovery_files(window._session_id)
    assert project.is_file() and meta.is_file()
    assert open_project(project).width == 300
    assert threads and threads[0] is not threading.main_thread()
    assert not window.autosave_now(background=True)  # nothing new since that copy


def test_saving_during_a_background_autosave_leaves_no_copy(window, qapp, tmp_path, monkeypatch):
    window.mutate("x", lambda doc: setattr(doc, "width", 300))
    assert window.autosave_now(background=True)
    monkeypatch.setattr(window, "project_path", tmp_path / "projet.manta")
    assert window.save_document()  # waits for the running copy, then deletes it
    qapp.processEvents()
    project, meta = window._recovery_files(window._session_id)
    assert not project.exists() and not meta.exists()
    assert window._autosave_task is None


def make_window(qapp, tmp_path, recovery):
    from PySide6.QtCore import QSettings

    from app.window import MainWindow
    return MainWindow(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                      recovery_dir=recovery)


def crashed_copy(recovery: Path, width=321, project_path=None):
    recovery.mkdir(parents=True, exist_ok=True)
    save_project(Document(width, 50), recovery / "dead.manta")
    (recovery / "dead.json").write_text(json.dumps({"saved_at": 1_700_000_000, "project_path": project_path}))


def answer_recovery(monkeypatch, answer):
    """Answer the recovery question of every window built next ("restore", "discard" or "later")."""
    from app.window import MainWindow
    monkeypatch.setattr(MainWindow, "_ask_recovery", lambda self, candidate, index, count: answer(
        self, candidate, index, count) if callable(answer) else answer)


def test_copy_left_by_a_crash_is_offered_and_restored(qapp, tmp_path, monkeypatch):
    recovery = tmp_path / "recovery"
    crashed_copy(recovery, project_path=str(tmp_path / "mon-projet.manta"))
    answer_recovery(monkeypatch, "restore")
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
    recovery = tmp_path / "recovery"
    crashed_copy(recovery)
    answer_recovery(monkeypatch, "discard")
    window = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()
    try:
        assert window.document.width != 321 and not (recovery / "dead.manta").exists()
    finally:
        window.close()


def test_copies_of_running_sessions_are_left_alone(qapp, tmp_path, monkeypatch):
    recovery = tmp_path / "recovery"
    answer_recovery(monkeypatch, lambda *_: pytest.fail("offered a live session"))
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


def test_orphan_locks_without_copy_are_cleaned(qapp, tmp_path):
    import subprocess
    import sys
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    orphan = recovery / "gone.lock"
    # A real crash: another process takes the lock and dies without releasing it.
    subprocess.run([sys.executable, "-c",
                    "import os, sys; from PySide6.QtCore import QLockFile; "
                    "lock = QLockFile(sys.argv[1]); assert lock.tryLock(0); os._exit(0)", str(orphan)],
                   check=True, timeout=60)
    assert orphan.exists()
    window = make_window(qapp, tmp_path, recovery)
    try:
        assert not orphan.exists()
    finally:
        window.close()


def test_copy_without_metadata_is_still_offered(qapp, tmp_path, monkeypatch):
    recovery = tmp_path / "recovery"
    crashed_copy(recovery)
    (recovery / "dead.json").unlink()  # crash between the two writes of the autosave
    offers = []
    answer_recovery(monkeypatch, lambda window, candidate, index, count: offers.append(
        window._recovery_text(candidate, index, count)[0]) or "restore")
    window = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()
    try:
        assert window.document.width == 321
        assert "une date inconnue" not in offers[0]  # dated from the file itself
        assert not (recovery / "dead.manta").exists()
    finally:
        window.undo_stack.setClean()
        window.close()


def test_metadata_without_copy_is_cleaned(qapp, tmp_path, monkeypatch):
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    (recovery / "gone.json").write_text(json.dumps({"saved_at": 1_700_000_000}))
    answer_recovery(monkeypatch, lambda *_: pytest.fail("nothing to restore"))
    window = make_window(qapp, tmp_path, recovery)
    qapp.processEvents()
    try:
        assert not (recovery / "gone.json").exists()
    finally:
        window.close()


def test_selection_changes_alone_do_not_mark_the_document_as_modified(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda *_: pytest.fail("no save prompt expected"))
    window.select_all()
    window.invert_selection()
    assert window.undo_stack.count() == 2  # selections stay undoable
    assert not window.is_modified() and "*" not in window.windowTitle()
    assert not window.autosave_now()
    assert window.maybe_save()


def test_document_edits_still_count_around_selection_changes(window):
    layer = image_layer(window)
    window.select_layer(layer.id)
    window.select_all()
    window.nudge_layer(4, 0)
    assert window.is_modified() and "*" in window.windowTitle()
    window.undo_stack.undo()  # back to the saved document, selection kept
    assert not window.is_modified()


def test_moving_selected_pixels_marks_the_document_as_modified(window):
    layer = image_layer(window)
    if layer.locked:
        window.toggle_lock(layer.id)
    window.undo_stack.setClean()
    window.select_layer(layer.id)
    window.select_all()
    window.move_selection_content(3, 2)  # one undo macro: new layer plus moved selection
    assert window.is_modified()


def crashed_session(recovery: Path, session_id: str, saved_at: float, width: int):
    recovery.mkdir(parents=True, exist_ok=True)
    save_project(Document(width, 10), recovery / f"{session_id}.manta")
    (recovery / f"{session_id}.json").write_text(json.dumps({"project_path": None, "saved_at": saved_at}))


@pytest.fixture
def two_copies(window):
    older, newer = "a" * 32, "b" * 32
    crashed_session(window.recovery_dir, older, 1000.0, 11)
    crashed_session(window.recovery_dir, newer, 2000.0, 22)
    return window, older, newer


def answer_each_copy(window, monkeypatch, answers):
    asked = []

    def ask(candidate, index, count):
        asked.append((candidate["id"], index, count))
        return answers[len(asked) - 1]

    monkeypatch.setattr(window, "_ask_recovery", ask)
    return asked


def test_restoring_the_newest_copy_keeps_the_other_for_later(two_copies, monkeypatch):
    window, older, newer = two_copies
    asked = answer_each_copy(window, monkeypatch, ["restore"])
    assert window.offer_session_recovery()
    assert asked == [(newer, 0, 2)]
    assert window.document.width == 22
    assert not (window.recovery_dir / f"{newer}.manta").exists()
    assert (window.recovery_dir / f"{older}.manta").exists()  # never deleted without being shown
    # It is offered again at the next start.
    asked = answer_each_copy(window, monkeypatch, ["discard"])
    assert not window.offer_session_recovery()
    assert asked == [(older, 0, 1)]
    assert not (window.recovery_dir / f"{older}.manta").exists()


def test_each_copy_can_be_deleted_or_kept(two_copies, monkeypatch):
    window, older, newer = two_copies
    answer_each_copy(window, monkeypatch, ["discard", "later"])
    assert not window.offer_session_recovery()
    assert not (window.recovery_dir / f"{newer}.manta").exists()
    assert (window.recovery_dir / f"{older}.manta").exists()
    assert [candidate["id"] for candidate in window.recovery_candidates()] == [older]  # its lock was released


def test_the_recovery_question_offers_restore_delete_and_later(two_copies):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    window, _older, newer = two_copies
    seen = []

    def click_later():
        box = QApplication.activeModalWidget()
        seen.extend(button.text() for button in box.buttons())
        next(button for button in box.buttons() if button.text() == "Plus tard").click()

    QTimer.singleShot(0, click_later)
    candidate = window.recovery_candidates()[0]
    try:
        assert window._ask_recovery(candidate, 0, 2) == "later"
    finally:
        for item in window.recovery_candidates() + [candidate]:
            item["lock"].unlock()
    assert sorted(seen) == ["Plus tard", "Restaurer", "Supprimer"]
    assert candidate["id"] == newer
