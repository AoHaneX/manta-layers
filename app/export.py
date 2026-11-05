"""Writing the final image (or one layer) as PNG, JPEG or WebP. No Qt."""
from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path

from PIL import Image

FILE_FILTERS = "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)"
FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
# The WebP encoder refuses larger images, although a document may reach 16384 px.
WEBP_MAX_DIMENSION = 16383


def with_image_suffix(path: Path, chosen_filter: str = "") -> Path:
    """The path itself if it names an image format, else the path plus the filter's extension.

    The extension is added, never substituted: "carte.final" becomes
    "carte.final.png", not "carte.png", which may be another existing file.
    """
    path = Path(path)
    if path.suffix.lower() in FORMATS:
        return path
    extension = ".jpg" if "JPEG" in chosen_filter else ".webp" if "WebP" in chosen_filter else ".png"
    return path.with_name(path.name + extension)


def save_image(image: Image.Image, path: Path) -> None:
    """Save an RGBA image; JPEG has no transparency and is flattened on white.

    The image is encoded into a temporary file next to the destination, which
    replaces it only once complete: a failure keeps the previous file intact.
    """
    path = Path(path)
    image_format = FORMATS.get(path.suffix.lower())
    if image_format is None:
        raise ValueError(f"Format d'image non pris en charge : {path.suffix or 'sans extension'}")
    if image_format == "WEBP" and max(image.size) > WEBP_MAX_DIMENSION:
        raise ValueError(
            f"Le format WebP est limité à {WEBP_MAX_DIMENSION} pixels de côté ; l'image mesure "
            f"{image.width} × {image.height}. Exportez-la en PNG ou en JPEG.")
    if image.mode != "RGBA":
        image = image.convert("RGBA")  # convert() always copies: only when needed
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem[:40]}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            if image_format == "JPEG":
                flat = Image.new("RGB", image.size, (255, 255, 255))
                flat.paste(image, mask=image.getchannel("A"))
                flat.save(output, format="JPEG", quality=95)
            elif image_format == "WEBP":
                image.save(output, format="WEBP", quality=95, method=4)
            else:
                image.save(output, format="PNG", optimize=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise
