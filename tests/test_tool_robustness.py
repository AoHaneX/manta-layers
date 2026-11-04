"""Tools on damaged layers, scene replacement during a click, shapes, eraser and token export."""
from zipfile import ZipFile

import pytest
import shiboken6
from conftest import png_bytes
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.model import Document
from app.storage import save_project


@pytest.fixture
def damaged(window, tmp_path, monkeypatch):
    """Project opened with one damaged image layer (shown hatched) and one intact layer."""
    document = Document(40, 30)
    intact = document.add_image_bytes(png_bytes(8, 8, (0, 0, 255, 255)), "Intact", center=False)
    broken = document.add_image_bytes(png_bytes(6, 6), "Cassée", center=False)
    path = tmp_path / "abime.manta"
    save_project(document, path)
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries[f"assets/{broken.asset}.png"] = entries[f"assets/{broken.asset}.png"][:40]
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(path), ""))
    window.open_document()
    window.select_layer(broken.id)
    reported = []
    monkeypatch.setattr(window, "_report_failure", lambda action, exc: reported.append(action))
    return window, intact, broken, reported


# --- P1-002 : the replaced scene is deleted after the event, never during it ----------------

def test_the_previous_scene_is_deleted_only_once_events_are_processed(window):
    previous = window.canvas_scene
    window.install_document(Document(30, 20), None)
    assert shiboken6.isValid(previous)  # still alive: it may be handling the current event
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(previous)  # and released afterwards, not kept forever


def test_a_click_that_commits_a_pending_curve_replaces_the_scene_safely(window):
    from PySide6.QtTest import QTest

    document = Document(400, 300)
    image = document.add_image_bytes(png_bytes(60, 60), "Image", center=False)
    image.x = image.y = 200
    text = document.add_text("Courbe")
    text.x, text.y = 10, 10
    window.install_document(document, text.id)
    window.canvas.fit_document()
    window.curve_intensity.setValue(40)  # starts the pending curve timer
    assert window.curve_commit_timer.isActive()
    scene = window.canvas_scene
    item = window.canvas.graphic_for(image.id)
    position = window.canvas.mapFromScene(item.sceneBoundingRect().center())
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert window.canvas_scene is not scene  # the curve was committed during the click
    assert window.document.layer(text.id).curve_intensity == 40
    assert window.selected_id == image.id
