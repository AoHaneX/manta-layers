"""Format .manta : ZIP contenant manifest.json et les images originales PNG."""
from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from .model import Document


def save_project(
    document: Document,
    destination: str | Path,
    metadata: dict | None = None,
    thumbnail: bytes | None = None,
) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    used = {asset for layer in document.layers if layer.kind == "image"
            for asset in (layer.asset, layer.mask) if asset}
    try:
        with open(tmp, "wb") as handle:
            with ZipFile(handle, "w", ZIP_DEFLATED) as z:
                manifest = document.manifest()
                if metadata:
                    manifest["template"] = metadata
                z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
                for asset_id in sorted(used):
                    z.writestr(f"assets/{asset_id}.png", document.assets[asset_id])
                if thumbnail:
                    z.writestr("thumbnail.png", thumbnail)
            # Make sure the bytes reached the disk before replacing the old file.
            handle.flush()
            os.fsync(handle.fileno())
        # Re-read the temporary file: a corrupted write never replaces a good project.
        try:
            open_project(tmp)
        except ValueError as exc:
            raise ValueError(f"La vérification de la sauvegarde a échoué : {exc}") from exc
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ASSET_BYTES = 150 * 1024 * 1024


def read_manifest(archive: ZipFile) -> dict:
    """Lit le manifeste en refusant les fichiers démesurés ou mal formés."""
    if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
        raise ValueError("Manifeste de projet trop volumineux")
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifeste de projet invalide")
    return manifest


def open_project(path: str | Path) -> Document:
    try:
        with ZipFile(path) as z:
            manifest = read_manifest(z)
            layers = manifest.get("layers")
            if not isinstance(layers, list):
                raise ValueError("Liste de calques invalide")
            if len(layers) > 1000:
                raise ValueError("Projet avec trop de calques")
            assets = {}
            for layer in layers:
                if not isinstance(layer, dict) or layer.get("kind") != "image":
                    continue
                for key in ("asset", "mask"):
                    asset_id = layer.get(key)
                    if key == "mask" and asset_id is None:
                        continue
                    # Prévient toute lecture arbitraire à partir d'un manifeste corrompu.
                    if not isinstance(asset_id, str) or len(asset_id) != 32 or not all(c in '0123456789abcdef' for c in asset_id):
                        raise ValueError("Identifiant d'image invalide")
                    if key == "mask" and f"assets/{asset_id}.png" not in z.namelist():
                        continue  # a missing mask is dropped, the layer stays readable
                    if asset_id not in assets:
                        info = z.getinfo(f"assets/{asset_id}.png")
                        if info.file_size > MAX_ASSET_BYTES:
                            raise ValueError("Image trop volumineuse")
                        assets[asset_id] = z.read(info)
        return Document.from_manifest(manifest, assets)
    except (BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Le fichier ne semble pas être un projet Manta Layers valide") from exc
