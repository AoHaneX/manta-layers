"""Writing the final image (or one layer) as PNG, JPEG or WebP, and animations as GIF or APNG. No Qt."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from PIL import Image

FILE_FILTERS = "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp)"
GIF_FILTER = "GIF animé (*.gif)"
APNG_FILTER = "PNG animé (APNG) (*.png)"
# The document export also offers the animated formats.
DOCUMENT_FILE_FILTERS = f"{FILE_FILTERS};;{GIF_FILTER};;{APNG_FILTER}"
# GIF has no partial transparency: pixels at least half opaque become opaque.
GIF_ALPHA_THRESHOLD = 128


class ExportCancelled(Exception):
    """The user stopped an export: no file is written."""


def animation_format(chosen_filter: str) -> str | None:
    """"GIF" or "APNG" for an animated export filter, None for still images."""
    return {GIF_FILTER: "GIF", APNG_FILTER: "APNG"}.get(chosen_filter)


def with_animation_suffix(path: Path, animation: str) -> Path:
    """The path with the extension of the animated format, added when missing (see with_image_suffix)."""
    path = Path(path)
    extension = ".gif" if animation == "GIF" else ".png"
    return path if path.suffix.lower() == extension else path.with_name(path.name + extension)
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

    def write(output) -> None:
        if image_format == "JPEG":
            flat = Image.new("RGB", image.size, (255, 255, 255))
            flat.paste(image, mask=image.getchannel("A"))
            flat.save(output, format="JPEG", quality=95)
        elif image_format == "WEBP":
            image.save(output, format="WEBP", quality=95, method=4)
        else:
            image.save(output, format="PNG", optimize=True)

    _write_atomically(path, write)


def _write_atomically(path: Path, write: Callable) -> None:
    """Run ``write(file)`` on a temporary file next to ``path``, which replaces it once complete.

    A failure or a cancellation keeps the previous file intact and leaves nothing behind.
    """
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem[:40]}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            write(output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary)
        raise


def gif_frame(image: Image.Image) -> Image.Image:
    """RGBA frame ready for GIF: transparency is all or nothing, hidden colours are cleared."""
    frame = image.convert("RGBA")
    opaque = frame.getchannel("A").point(lambda a: 255 if a >= GIF_ALPHA_THRESHOLD else 0)
    cleared = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    cleared.paste(frame, mask=opaque)
    cleared.putalpha(opaque)
    return cleared


def save_animation(frames: list[Image.Image], durations: list[int], path: Path, animation: str,
                   cancelled: Callable[[], bool] = lambda: False,
                   progress: Callable[[int], None] = lambda _done: None) -> None:
    """Write composed RGBA frames as a GIF or an APNG looping forever.

    Each frame is shown for its duration in ms (GIF rounds to hundredths of a
    second). Every frame replaces the previous one entirely: GIF frames are
    disposed to the background, APNG frames are drawn without blending, so a
    transparent area never keeps a trace of the previous frame. ``cancelled``
    is polled between frames; ExportCancelled is raised then and no file is
    written. Pillow encoders may run in a worker thread.
    """
    path = Path(path)
    if len(frames) != len(durations) or not frames:
        raise ValueError("Aucune image à exporter")
    prepare = gif_frame if animation == "GIF" else (lambda image: image if image.mode == "RGBA"
                                                      else image.convert("RGBA"))

    class Following:
        """The frames after the first, prepared on the fly; Pillow's APNG writer reads them twice."""

        def __iter__(self):
            for index, image in enumerate(frames[1:], start=1):
                if cancelled():
                    raise ExportCancelled
                progress(index)
                yield prepare(image)

    def write(output) -> None:
        first = prepare(frames[0])
        if animation == "GIF":
            first.save(output, format="GIF", save_all=True, append_images=Following(),
                       duration=durations, loop=0, disposal=2, optimize=False)
        else:
            first.save(output, format="PNG", save_all=True, append_images=Following(),
                       duration=durations, loop=0, disposal=0, blend=0, default_image=False)
        if cancelled():
            raise ExportCancelled
        progress(len(frames))

    _write_atomically(path, write)
