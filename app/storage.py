"""Format .manta : ZIP contenant manifest.json et les images originales PNG."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from .model import Document


def save_project(document: Document, destination: str | Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    used = {layer.asset for layer in document.layers if layer.kind == "image"}
    try:
        with ZipFile(tmp, "w", ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(document.manifest(), indent=2, ensure_ascii=False))
            for asset_id in sorted(used):
                z.writestr(f"assets/{asset_id}.png", document.assets[asset_id])
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)


def open_project(path: str | Path) -> Document:
    try:
        with ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            if len(manifest.get("layers", [])) > 1000:
                raise ValueError("Projet avec trop de calques")
            assets = {}
            for layer in manifest["layers"]:
                if layer.get("kind") == "image":
                    asset_id = layer.get("asset")
                    # Prévient toute lecture arbitraire à partir d'un manifeste corrompu.
                    if not isinstance(asset_id, str) or len(asset_id) != 32 or not all(c in '0123456789abcdef' for c in asset_id):
                        raise ValueError("Identifiant d'image invalide")
                    if asset_id not in assets:
                        info = z.getinfo(f"assets/{asset_id}.png")
                        if info.file_size > 150 * 1024 * 1024:
                            raise ValueError("Image trop volumineuse")
                        assets[asset_id] = z.read(info)
        return Document.from_manifest(manifest, assets)
    except (BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Le fichier ne semble pas être un projet Manta Layers valide") from exc
