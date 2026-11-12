"""Format .manta : ZIP contenant manifest.json et les images originales PNG."""
from __future__ import annotations

import json
import os
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from . import model
from .model import MAX_ASSET_BYTES, MAX_LAYERS, Document


def save_project(
    document: Document,
    destination: str | Path,
    metadata: dict | None = None,
    thumbnail: bytes | None = None,
) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    used = document.used_assets()
    # The limits of open_project are checked before writing: a project that could
    # not be reopened is refused with its reason, and the previous file is kept.
    if len(document.layers) > MAX_LAYERS:
        raise ValueError(f"Le projet contient {len(document.layers)} calques : "
                         f"un projet en compte au plus {MAX_LAYERS}")
    asset_bytes = sum(len(document.assets[asset_id]) for asset_id in used)
    if asset_bytes > model.MAX_PROJECT_ASSET_BYTES:
        raise ValueError(
            f"Les images du projet occupent {asset_bytes / 1_073_741_824:.1f} Go : un projet en enregistre "
            f"au plus {model.MAX_PROJECT_ASSET_BYTES / 1_073_741_824:.0f} Go. "
            "Supprimez ou réduisez des calques image.")
    manifest = document.manifest()
    if metadata:
        manifest["template"] = metadata
    manifest_data = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    if len(manifest_data) > MAX_MANIFEST_BYTES:
        raise ValueError(
            f"Les réglages du projet (calques, traits de gomme, remplissages) occupent "
            f"{len(manifest_data) / 1_048_576:.0f} Mo : un projet en enregistre au plus "
            f"{MAX_MANIFEST_BYTES // 1_048_576} Mo. Fusionnez des calques ou rognez-en les retouches.")
    try:
        with open(tmp, "wb") as handle:
            with ZipFile(handle, "w", ZIP_DEFLATED) as z:
                z.writestr("manifest.json", manifest_data)
                # PNG data is already compressed: deflating it again only costs time
                # (2.3 s instead of 0.05 s for 100 MB of images).
                for asset_id in sorted(used):
                    z.writestr(f"assets/{asset_id}.png", document.assets[asset_id], compress_type=ZIP_STORED)
                if thumbnail:
                    z.writestr("thumbnail.png", thumbnail, compress_type=ZIP_STORED)
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


# Settings of every layer (strokes and fills included). Checked when writing
# (save_project) and when reading (read_manifest).
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
# Manta Layers only writes these. Other methods (LZMA, BZIP2) raise their own
# exceptions on damaged data: they are refused instead of being decoded.
READABLE_COMPRESSIONS = (ZIP_STORED, ZIP_DEFLATED)


def read_manifest(archive: ZipFile) -> dict:
    """Lit le manifeste en refusant les fichiers démesurés ou mal formés."""
    if any(info.compress_type not in READABLE_COMPRESSIONS for info in archive.infolist()):
        raise ValueError("Méthode de compression non prise en charge")
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
            if len(layers) > MAX_LAYERS:
                raise ValueError("Projet avec trop de calques")
            assets = {}
            names = set(z.namelist())
            total_bytes = 0  # decompressed size of the images read so far
            for layer in layers:
                if not isinstance(layer, dict) or layer.get("kind") != "image":
                    continue
                for key in ("asset", "mask", "animation"):
                    asset_id = layer.get(key)
                    optional = key != "asset"  # a lost mask or animation leaves a still image
                    if optional and asset_id is None:
                        continue
                    # Prévient toute lecture arbitraire à partir d'un manifeste corrompu.
                    if not isinstance(asset_id, str) or len(asset_id) != 32 or not all(c in '0123456789abcdef' for c in asset_id):
                        raise ValueError("Identifiant d'image invalide")
                    if optional and f"assets/{asset_id}.png" not in names:
                        continue  # dropped by Document.from_manifest, the layer stays readable
                    if asset_id not in assets:
                        info = z.getinfo(f"assets/{asset_id}.png")
                        if info.file_size > MAX_ASSET_BYTES:
                            raise ValueError("Image trop volumineuse")
                        # Checked before reading: sizes come from the archive directory,
                        # and z.read() refuses data longer than the declared size.
                        total_bytes += info.file_size
                        if total_bytes > model.MAX_PROJECT_ASSET_BYTES:
                            raise ValueError("Images du projet trop volumineuses")
                        assets[asset_id] = z.read(info)
        return Document.from_manifest(manifest, assets)
    # Damaged archives fail in many ways (corrupted compressed data, unsupported
    # or encrypted entries, truncated files): all mean "not a valid project".
    except (BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError, zlib.error,
            OverflowError, NotImplementedError, RuntimeError, EOFError) as exc:
        raise ValueError("Le fichier ne semble pas être un projet Manta Layers valide") from exc
