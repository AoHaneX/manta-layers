"""Bibliothèque locale de modèles autonomes fondés sur le format .manta."""
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from .model import Document
from .paths import user_data_directory
from .storage import open_project, read_manifest, save_project


@dataclass(frozen=True)
class TemplateInfo:
    path: Path
    name: str
    width: int
    height: int
    thumbnail: bytes | None = None


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
            thumbnail = archive.read("thumbnail.png") if "thumbnail.png" in archive.namelist() else None
        name = str(metadata.get("name") or path.stem).strip() or path.stem
        return TemplateInfo(path, name, int(manifest["width"]), int(manifest["height"]), thumbnail)
    except (BadZipFile, KeyError, ValueError, TypeError, OverflowError, UnicodeDecodeError,
            json.JSONDecodeError, zlib.error, NotImplementedError, RuntimeError, EOFError,
            OSError) as exc:
        raise ValueError(f"Modèle invalide : {path.name}") from exc


def list_templates(directory: str | Path | None = None) -> list[TemplateInfo]:
    result = []
    for path in _directory(directory).glob("*.manta"):
        try:
            result.append(read_template_info(path))
        except ValueError:
            continue
    return sorted(result, key=lambda item: item.name.casefold())


def save_template(
    document: Document,
    name: str,
    thumbnail: bytes | None,
    directory: str | Path | None = None,
    destination: str | Path | None = None,
) -> Path:
    clean_name = " ".join(name.split()).strip()
    if not clean_name:
        raise ValueError("Le modèle doit avoir un nom")
    path = Path(destination) if destination is not None else _directory(directory) / f"{uuid4().hex}.manta"
    save_project(document, path, {"name": clean_name, "kind": "preset", "version": 1}, thumbnail)
    return path


def rename_template(path: str | Path, name: str) -> None:
    info = read_template_info(path)
    document = open_project(info.path)
    save_template(document, name, info.thumbnail, destination=info.path)


def duplicate_template(path: str | Path, directory: str | Path | None = None) -> Path:
    info = read_template_info(path)
    return save_template(open_project(info.path), f"{info.name} (copie)", info.thumbnail, directory)


def delete_template(path: str | Path) -> None:
    Path(path).unlink()


def instantiate_template(path: str | Path) -> Document:
    document = open_project(path).clone()
    for layer in document.layers:
        layer.locked = True
    return document
