"""Layer folders in the document model: grouping, moves, visibility and persistence."""
import json
from zipfile import ZipFile

import pytest

from app.model import COMPATIBLE_VERSION, PROJECT_VERSION, Document, Layer
from app.storage import open_project, save_project


def stack(*names):
    document = Document(100, 100)
    for name in names:
        document.layers.append(Layer(id=name, name=name, kind="text", text=name))
    return document


def order(document):
    return [layer.id for layer in document.layers]


def test_folder_groups_layers_at_the_place_of_the_topmost_one():
    document = stack("a", "b", "c", "d", "e")  # bottom -> top
    folder = document.create_folder(["b", "d"], "  Mon   dossier ")
    assert folder.name == "Mon dossier"
    assert order(document) == ["a", "c", "b", "d", "e"]
    assert [layer.id for layer in document.folder_members(folder.id)] == ["b", "d"]


def test_creating_a_folder_requires_layers():
    with pytest.raises(ValueError):
        stack("a").create_folder(["missing"], "Vide")


def test_folder_visibility_hides_its_layers_only():
    document = stack("a", "b", "c")
    folder = document.create_folder(["b", "c"], "Groupe")
    folder.visible = False
    assert [document.is_visible(layer) for layer in document.layers] == [True, False, False]


def test_moving_layers_in_and_out_of_folders_keeps_blocks_contiguous():
    document = stack("a", "b", "c", "d", "e")
    first = document.create_folder(["a", "b"], "Un")
    second = document.create_folder(["d", "e"], "Deux")
    assert document.move_layer("a", "e", True, second.id)  # into the top of the second folder
    assert order(document) == ["b", "c", "d", "e", "a"]
    assert document.layer("a").folder == second.id
    assert document.move_layer("c", "b", False, None)  # below the first folder, top level
    assert order(document)[:2] == ["c", "b"]
    assert document.move_layer("b", "e", False, second.id)  # the first folder becomes empty
    assert document.folder(first.id) is None and document.layer("b").folder == second.id


def test_a_folder_moves_as_one_block_preserving_its_order():
    document = stack("a", "b", "c", "d", "e")
    folder = document.create_folder(["b", "c"], "Bloc")
    assert document.move_folder(folder.id, "e", True)
    assert order(document) == ["a", "d", "e", "b", "c"]
    assert not document.move_folder(folder.id, "b", True)  # onto itself
    other = document.create_folder(["a", "d"], "Autre")
    assert document.move_folder(folder.id, "a", False)  # below another folder, not inside it
    assert order(document)[:2] == ["b", "c"]
    assert {layer.folder for layer in document.folder_members(other.id)} == {other.id}


def test_step_moves_leave_a_folder_at_its_edge_and_step_over_other_folders():
    document = stack("a", "b", "c", "d")
    folder = document.create_folder(["b", "c"], "F")
    assert document.reorder_layer("a", 1)  # steps over the whole folder
    assert order(document) == ["b", "c", "a", "d"] and document.layer("a").folder is None
    assert document.reorder_layer("c", 1)  # top member leaves the folder in place
    assert order(document) == ["b", "c", "a", "d"] and document.layer("c").folder is None
    assert [layer.id for layer in document.folder_members(folder.id)] == ["b"]


def test_removing_layers_drops_empty_folders():
    document = stack("a", "b", "c")
    document.create_folder(["b"], "Seul")
    assert document.remove_layers(["b", "missing"]) == 1
    assert document.folders == []


def test_dissolving_a_folder_keeps_its_layers_in_place():
    document = stack("a", "b", "c")
    folder = document.create_folder(["a", "c"], "F")
    expected = order(document)
    document.dissolve_folder(folder.id)
    assert order(document) == expected and document.folders == []


def test_folders_survive_save_and_reopen_and_need_version_3(tmp_path):
    document = stack("a", "b", "c")
    folder = document.create_folder(["a", "b"], "Persistant")
    folder.visible, folder.collapsed = False, True
    path = tmp_path / "dossiers.manta"
    save_project(document, path)
    with ZipFile(path) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == PROJECT_VERSION
    reopened = open_project(path)
    restored = reopened.folder(folder.id)
    assert (restored.name, restored.visible, restored.collapsed) == ("Persistant", False, True)
    assert order(reopened) == order(document)


def test_projects_without_folders_stay_version_2(tmp_path):
    path = tmp_path / "simple.manta"
    save_project(stack("a"), path)
    with ZipFile(path) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == COMPATIBLE_VERSION


def test_corrupted_folder_data_is_repaired_on_load():
    raw = stack("a", "b", "c").manifest()
    raw["version"] = PROJECT_VERSION
    raw["folders"] = [{"id": "f", "name": 3}]
    raw["layers"][0]["folder"] = "f"
    raw["layers"][2]["folder"] = "f"  # not contiguous
    raw["layers"][1]["folder"] = "unknown"
    document = Document.from_manifest(raw, {})
    assert document.folder("f").name == "Dossier"
    assert [layer.id for layer in document.folder_members("f")] == ["a", "c"]
    assert document.layer("b").folder is None
    raw["folders"] = [{"id": "f"}, {"id": "f"}]
    with pytest.raises(ValueError):
        Document.from_manifest(raw, {})
