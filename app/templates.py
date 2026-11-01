"""Bibliothèque locale de modèles autonomes fondés sur le format .manta.

Two kinds of templates share the format:

* ``preset``: a whole document, offered when a new project is created;
* ``elements``: a group of layers (with their folders and images), inserted
  into the open project, as many times as needed, and kept editable.
"""
from __future__ import annotations

import json
import zlib
from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from .model import MAX_DIMENSION, Document, Folder, new_id
from .paths import user_data_directory
from .storage import open_project, read_manifest, save_project

TEMPLATE_KINDS = ("preset", "elements")
# Thumbnails are small previews; a larger entry is ignored rather than loaded.
MAX_THUMBNAIL_BYTES = 4 * 1024 * 1024
# Renaming or duplicating copies the thumbnail as stored, within this wider limit.
MAX_COPIED_THUMBNAIL_BYTES = 64 * 1024 * 1024
# Errors of a damaged or unexpected archive, turned into "invalid template".
_READ_ERRORS = (BadZipFile, KeyError, ValueError, TypeError, OverflowError, UnicodeDecodeError,
                json.JSONDecodeError, zlib.error, NotImplementedError, RuntimeError, EOFError, OSError)


@dataclass(frozen=True)
class TemplateInfo:
    path: Path
    name: str
    width: int
    height: int
    thumbnail: bytes | None = None
    kind: str = "preset"

    @property
    def key(self) -> str:
        """Stable identifier of the template (used to remember its folders)."""
        return self.path.stem


def template_directory() -> Path:
    return user_data_directory() / "templates"


def _directory(directory: str | Path | None) -> Path:
    result = Path(directory) if directory is not None else template_directory()
    result.mkdir(parents=True, exist_ok=True)
    return result


def read_template_info(path: str | Path) -> TemplateInfo:
    path = Path(path)
    try:
        with ZipFile(path) as archive:
            manifest = read_manifest(archive)
            metadata = manifest.get("template") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            thumbnail = None
            if "thumbnail.png" in archive.namelist():
                if archive.getinfo("thumbnail.png").file_size <= MAX_THUMBNAIL_BYTES:
                    thumbnail = archive.read("thumbnail.png")
        name = str(metadata.get("name") or path.stem).strip() or path.stem
        kind = str(metadata.get("kind")) if metadata.get("kind") in TEMPLATE_KINDS else "preset"
        width, height = int(manifest["width"]), int(manifest["height"])
        # A template that could not be instantiated must not appear in the gallery.
        if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
            raise ValueError(f"Dimensions hors limites : {width} × {height}")
        return TemplateInfo(path, name, width, height, thumbnail, kind)
    except _READ_ERRORS as exc:
        raise ValueError(f"Modèle invalide : {path.name}") from exc


def _stored_thumbnail(info: TemplateInfo) -> bytes | None:
    """Thumbnail entry as stored in the template, even one too large for the gallery.

    Falls back to what ``read_template_info`` loaded when the entry cannot be read.
    """
    try:
        with ZipFile(info.path) as archive:
            if "thumbnail.png" not in archive.namelist():
                return None
            entry = archive.getinfo("thumbnail.png")
            if entry.file_size > MAX_COPIED_THUMBNAIL_BYTES:
                return info.thumbnail
            return archive.read(entry)
    except _READ_ERRORS:
        return info.thumbnail


def list_templates(directory: str | Path | None = None, kind: str = "preset") -> list[TemplateInfo]:
    """Readable templates of one kind, by name; damaged files are skipped."""
    result = []
    for path in _directory(directory).glob("*.manta"):
        try:
            info = read_template_info(path)
        except ValueError:
            continue
        if info.kind == kind:
            result.append(info)
    return sorted(result, key=lambda item: item.name.casefold())


def save_template(
    document: Document,
    name: str,
    thumbnail: bytes | None,
    directory: str | Path | None = None,
    destination: str | Path | None = None,
    kind: str = "preset",
) -> Path:
    clean_name = " ".join(name.split()).strip()
    if not clean_name:
        raise ValueError("Le modèle doit avoir un nom")
    if kind not in TEMPLATE_KINDS:
        raise ValueError(f"Type de modèle inconnu : {kind}")
    path = Path(destination) if destination is not None else _directory(directory) / f"{uuid4().hex}.manta"
    save_project(document, path, {"name": clean_name, "kind": kind, "version": 1}, thumbnail)
    return path


def rename_template(path: str | Path, name: str) -> None:
    info = read_template_info(path)
    document = open_project(info.path)
    save_template(document, name, _stored_thumbnail(info), destination=info.path, kind=info.kind)


def duplicate_template(path: str | Path, directory: str | Path | None = None) -> Path:
    info = read_template_info(path)
    return save_template(open_project(info.path), f"{info.name} (copie)", _stored_thumbnail(info), directory,
                         kind=info.kind)


def delete_template(path: str | Path) -> None:
    Path(path).unlink()


def instantiate_template(path: str | Path) -> Document:
    document = open_project(path).clone()
    for layer in document.layers:
        layer.locked = True
    return document


# --- Element templates ----------------------------------------------------------------


def extract_elements(document: Document, layer_ids, bounds: tuple[float, float, float, float]) -> Document:
    """Copy some layers into a standalone document framed by ``bounds`` (left, top, right, bottom).

    Positions become relative to the frame; images, masks and folders used by
    the layers travel with them.
    """
    wanted = set(layer_ids)
    layers = [deepcopy(layer) for layer in document.layers if layer.id in wanted]
    if not layers:
        raise ValueError("Aucun calque pour créer le modèle")
    left, top, right, bottom = bounds
    width = max(1, min(MAX_DIMENSION, ceil(right - left)))
    height = max(1, min(MAX_DIMENSION, ceil(bottom - top)))
    for layer in layers:
        layer.x -= left
        layer.y -= top
        layer.locked = False
    assets = {asset: document.assets[asset] for layer in layers
              for asset in (layer.asset, layer.mask) if asset and asset in document.assets}
    used = {layer.folder for layer in layers}
    folders = [deepcopy(folder) for folder in document.folders if folder.id in used]
    subset = Document(width, height, None, layers, assets, folders)
    subset.normalize_folders()
    return subset


def insert_elements(target: Document, elements: Document, offset: tuple[float, float]) -> list[str]:
    """Add copies of the layers of ``elements`` on top of ``target``, shifted by ``offset``.

    Layers and folders get new ids, so the same template can be inserted
    again; images are shared by id (an id always designates the same content).
    Returns the new layer ids, bottom to top.
    """
    folder_ids: dict[str, str] = {}
    for folder in elements.folders:
        copy = Folder(name=folder.name, visible=folder.visible, collapsed=folder.collapsed)
        folder_ids[folder.id] = copy.id
        target.folders.append(copy)
    new_ids = []
    for source in elements.layers:
        layer = deepcopy(source)
        layer.id = new_id()
        layer.x += offset[0]
        layer.y += offset[1]
        layer.folder = folder_ids.get(source.folder)
        for asset in (layer.asset, layer.mask):
            if asset and asset in elements.assets:
                target.assets.setdefault(asset, elements.assets[asset])
        target.layers.append(layer)
        new_ids.append(layer.id)
    target.normalize_folders()
    return new_ids
