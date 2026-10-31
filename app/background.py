"""Local background removal.

Two independent methods, both returning an 8-bit mask the size of the input
image (255 = keep, 0 = background):

* ``border_colour_mask``: no AI and no extra dependency. The background is the
  area connected to the image borders whose colour is close to the dominant
  border colour. Reliable on flat backgrounds and pixel art.
* ``onnx_mask``: a U²-Net family model run on the CPU with onnxruntime. Both
  onnxruntime and numpy are optional and imported lazily; the model file must
  already be on disk. ``download_model`` is a separate function that the UI
  only calls after an explicit confirmation: nothing is ever downloaded
  silently and no image ever leaves the computer.

These methods remove a whole background. Segmenting one object chosen with a
click is not supported: U²-Net models take no point prompt.
"""
from __future__ import annotations

import http.client
import importlib.util
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import selection
from .paths import user_data_directory

Progress = Callable[[str, int], None]
MODEL_RELEASE_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/{name}.onnx"


class BackgroundRemovalError(Exception):
    """Raised with a message meant for the user."""


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    input_size: int
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    download_size_mb: float


# Pre-processing of the models published with rembg (same normalisation).
KNOWN_MODELS = {
    "u2netp": ModelSpec("u2netp", "U²-Net léger", 320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 4.6),
    "u2net": ModelSpec("u2net", "U²-Net", 320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 176),
    "u2net_human_seg": ModelSpec("u2net_human_seg", "U²-Net personnes", 320,
                                 (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 176),
    "isnet-general-use": ModelSpec("isnet-general-use", "IS-Net généraliste", 1024,
                                   (0.5, 0.5, 0.5), (1.0, 1.0, 1.0), 179),
}
DEFAULT_DOWNLOAD = "u2netp"


def models_directory() -> Path:
    return user_data_directory() / "models"


def onnx_runtime_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("onnxruntime", "numpy"))


def spec_for(path: Path) -> ModelSpec:
    """Pre-processing for a model file, deduced from its name (U²-Net by default)."""
    stem = Path(path).stem.lower()
    if stem in KNOWN_MODELS:
        return KNOWN_MODELS[stem]
    if "isnet" in stem:
        return KNOWN_MODELS["isnet-general-use"]
    return ModelSpec(stem, Path(path).stem, 320, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225), 0)


def installed_models(directory: Path | None = None) -> list[Path]:
    directory = Path(directory) if directory is not None else models_directory()
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.onnx") if path.is_file())


# --- Method 1: border colour, no AI ------------------------------------------------

def dominant_border_colour(image: Image.Image) -> tuple[int, int, int, int]:
    """Most frequent colour on the outer frame; fully transparent pixels count as one."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    border = {(x, y) for x in range(width) for y in (0, height - 1)}
    border |= {(x, y) for y in range(height) for x in (0, width - 1)}
    counts = Counter((0, 0, 0, 0) if pixels[x, y][3] == 0 else pixels[x, y] for x, y in border)
    return counts.most_common(1)[0][0]


def border_colour_mask(image: Image.Image, tolerance: int = 32, feather: float = 0) -> Image.Image:
    """Keep everything except the border-connected area close to the border colour."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    reference = dominant_border_colour(rgba)
    # Similar colours anywhere, then a flood from a one-pixel frame keeps only
    # the regions that touch the borders.
    similar = selection.similar_colour(rgba, reference, tolerance)
    transparent = rgba.getchannel("A").point([255] + [0] * 255)
    candidates = ImageChops.lighter(similar, transparent)
    framed = Image.new("L", (width + 2, height + 2), 255)
    framed.paste(candidates, (1, 1))
    ImageDraw.floodfill(framed, (0, 0), 128, thresh=0)
    background = framed.crop((1, 1, width + 1, height + 1)).point(
        [255 if value == 128 else 0 for value in range(256)]
    )
    keep = ImageChops.invert(background)
    return keep.filter(ImageFilter.GaussianBlur(feather)) if feather > 0 else keep


# --- Method 2: local ONNX model -----------------------------------------------------

def onnx_mask(image: Image.Image, model_path: Path, progress: Progress | None = None,
              session_factory=None) -> Image.Image:
    """Predict the foreground with a U²-Net family model, entirely on this computer."""
    progress = progress or (lambda _message, _percent: None)
    model_path = Path(model_path)
    if not model_path.is_file():
        raise BackgroundRemovalError(f"Modèle introuvable : {model_path}")
    if session_factory is None and not onnx_runtime_available():
        raise BackgroundRemovalError(
            "onnxruntime n'est pas installé. Installez les dépendances facultatives : "
            "pip install -r requirements-ai.txt"
        )
    import numpy as np

    progress("Chargement du modèle…", 10)
    try:
        if session_factory is not None:
            session = session_factory(model_path)
        else:
            import onnxruntime
            session = onnxruntime.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise BackgroundRemovalError(f"Modèle illisible ({model_path.name}) : {exc}") from exc
    spec = spec_for(model_path)
    progress("Préparation de l'image…", 30)
    rgb = image.convert("RGB").resize((spec.input_size, spec.input_size), Image.Resampling.LANCZOS)
    array = np.asarray(rgb, dtype=np.float32)
    array = array / max(float(array.max()), 1e-6)
    array = (array - np.array(spec.mean, dtype=np.float32)) / np.array(spec.std, dtype=np.float32)
    tensor = array.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    progress("Analyse de l'image (processeur)…", 50)
    try:
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
    except Exception as exc:
        raise BackgroundRemovalError(f"Échec de l'analyse : {exc}") from exc
    progress("Construction du masque…", 90)
    prediction = np.squeeze(np.asarray(outputs[0], dtype=np.float32))
    if prediction.ndim != 2:
        raise BackgroundRemovalError("Sortie du modèle inattendue : ce n'est pas un modèle de détourage")
    low, high = float(prediction.min()), float(prediction.max())
    normalised = (prediction - low) / (high - low) if high > low else np.zeros_like(prediction)
    mask = Image.fromarray((normalised * 255).astype(np.uint8), mode="L")
    progress("Terminé", 100)
    return mask.resize(image.size, Image.Resampling.LANCZOS)


def refine(mask: Image.Image, hard_edges: bool, feather: float) -> Image.Image:
    """Optional clean-up: hard edges for pixel art, or a light blur for photos."""
    if hard_edges:
        mask = mask.point([0] * 128 + [255] * 128)
    return mask.filter(ImageFilter.GaussianBlur(feather)) if feather > 0 else mask


def preview(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Image as it will look once the mask is applied (transparency preserved)."""
    return selection.apply_alpha(image, mask)


def download_model(name: str, destination_dir: Path, progress: Progress | None = None,
                   cancelled: Callable[[], bool] = lambda: False, opener=urllib.request.urlopen) -> Path:
    """Download a known model. Only call this after the user explicitly agreed."""
    if name not in KNOWN_MODELS:
        raise BackgroundRemovalError(f"Modèle inconnu : {name}")
    progress = progress or (lambda _message, _percent: None)
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / f"{name}.onnx"
    partial = target.with_suffix(".onnx.part")
    url = MODEL_RELEASE_URL.format(name=name)
    try:
        with opener(url, timeout=30) as response, open(partial, "wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            while chunk := response.read(256 * 1024):
                if cancelled():
                    raise BackgroundRemovalError("Téléchargement annulé")
                output.write(chunk)
                received += len(chunk)
                percent = int(received * 100 / total) if total else 0
                progress(f"{received / 1_048_576:.1f} Mo reçus", percent)
        if total and received != total:
            raise BackgroundRemovalError("Téléchargement incomplet")
        partial.replace(target)
    except BackgroundRemovalError:
        partial.unlink(missing_ok=True)
        raise
    # A malformed Content-Length raises ValueError; a truncated chunked response
    # raises http.client.IncompleteRead, which is not an OSError.
    except (OSError, ValueError, http.client.HTTPException) as exc:
        partial.unlink(missing_ok=True)
        raise BackgroundRemovalError(f"Téléchargement impossible : {exc}") from exc
    return target
