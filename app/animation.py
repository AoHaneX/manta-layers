"""Animated GIF and APNG sources, decoded with Pillow only (no Qt).

On import, an animation is composed frame by frame (GIF disposal, APNG blend
and dispose operations, partial transparency) into full RGBA frames, stored
in the project as one lossless APNG: projects only hold PNG images, and every
animation is then read the same way. Frames are decoded on demand and kept
in a bounded cache: a long animation never sits whole in memory.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

# Delays of at most 10 ms are shown for 100 ms by browsers and most viewers:
# animations saved with a zero delay play at their usual speed here too.
SHORT_DELAY_MS = 10
DEFAULT_DELAY_MS = 100
# Bounds of an imported animation: frames are composed in memory on import.
MAX_FRAMES = 2000
MAX_DURATION_MS = 10 * 60 * 1000
MAX_ANIMATION_PIXELS = 160_000_000  # all frames together, about 640 MB in RGBA
ANIMATED_FORMATS = ("GIF", "PNG")


@dataclass
class Animation:
    """An imported animation: its first frame, the stored APNG and the frame durations."""

    first_frame: Image.Image
    apng: bytes
    durations: list[int]


def frame_delay(raw) -> int:
    """Display time of a frame in milliseconds, as viewers show it."""
    try:
        delay = round(float(raw))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_DELAY_MS
    return DEFAULT_DELAY_MS if delay <= SHORT_DELAY_MS else delay


def _animation_frames(source: Image.Image) -> range:
    """Indexes of the frames that make the animation.

    An APNG may start with a default image shown by viewers without APNG
    support, which is not part of the animation: seek(0) returns it then.
    """
    first = 1 if source.format == "PNG" and source.info.get("default_image") else 0
    return range(first, getattr(source, "n_frames", 1))


def read_animation(contents: bytes, max_dimension: int, max_pixels: int) -> Animation | None:
    """The animation held by a GIF or an APNG, or None when the image is not animated.

    Raises ValueError for a damaged or oversized animation; None leaves
    the image to the static import.
    """
    try:
        source = Image.open(BytesIO(contents), formats=ANIMATED_FORMATS)
    except Exception:
        return None  # not a GIF nor a PNG: the static import reports it
    with source:
        frames = _animation_frames(source)
        if not getattr(source, "is_animated", False) or len(frames) < 2:
            return None
        width, height = source.size
        if width > max_dimension or height > max_dimension or width * height > max_pixels:
            raise ValueError(f"Animation trop grande ({width} × {height} px)")
        if len(frames) > MAX_FRAMES:
            raise ValueError(f"Animation trop longue : {len(frames)} images, {MAX_FRAMES} au plus")
        if len(frames) * width * height > MAX_ANIMATION_PIXELS:
            raise ValueError("Animation trop volumineuse une fois décodée "
                             f"({len(frames)} images de {width} × {height} px)")
        composed: list[Image.Image] = []
        durations: list[int] = []
        try:
            for index in frames:
                source.seek(index)
                # Pillow composes each frame with the previous ones (disposal, blending).
                composed.append(source.convert("RGBA"))
                durations.append(frame_delay(source.info.get("duration")))
        except (OSError, ValueError, EOFError, SyntaxError) as exc:
            raise ValueError(f"Animation endommagée : {exc}") from exc
    if sum(durations) > MAX_DURATION_MS:
        raise ValueError("Animation trop longue : 10 minutes au plus")
    return Animation(composed[0], encode_apng(composed, durations), durations)


def encode_apng(frames: list[Image.Image], durations: list[int]) -> bytes:
    """Lossless APNG of full RGBA frames: each frame replaces the previous one entirely."""
    output = BytesIO()
    # Frames keep the source's metadata: an explicit default_image=False keeps the first
    # frame in the animation even when the source APNG had a separate default image.
    frames[0].save(output, format="PNG", save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, disposal=0, blend=0, default_image=False)
    return output.getvalue()


class FrameReader:
    """Frames of a stored APNG, decoded on demand.

    Pillow decodes APNG frames in order: moving forward from the current frame
    is cheap, going back reopens the file. Decoded frames are kept in a cache
    bounded by a memory budget, shared by every reader.
    """

    _cache: OrderedDict[tuple[str, int], Image.Image] = OrderedDict()
    _cached_bytes = 0
    BUDGET_BYTES = 256 * 1024 * 1024

    def __init__(self, key: str, contents: bytes):
        self.key = key
        self._contents = contents
        self._image: Image.Image | None = None

    def _open(self) -> Image.Image:
        image = Image.open(BytesIO(self._contents), formats=("PNG",))
        self._first = _animation_frames(image).start
        return image

    @property
    def frame_count(self) -> int:
        if self._image is None:
            self._image = self._open()
        return len(_animation_frames(self._image))

    def frame(self, index: int) -> Image.Image:
        """Full RGBA frame ``index`` of the animation (callers must not modify it)."""
        cached = self._cache.get((self.key, index))
        if cached is not None:
            self._cache.move_to_end((self.key, index))
            return cached
        if self._image is None:
            self._image = self._open()
        target = self._first + max(0, min(index, self.frame_count - 1))
        if target < self._image.tell():
            self._image.close()
            self._image = self._open()
        try:
            self._image.seek(target)
            frame = self._image.convert("RGBA")
        except (OSError, ValueError, EOFError, SyntaxError) as exc:
            raise ValueError(f"Animation illisible : {exc}") from exc
        self._remember((self.key, index), frame)
        return frame

    @classmethod
    def _remember(cls, key, frame: Image.Image) -> None:
        size = frame.width * frame.height * 4
        if size > cls.BUDGET_BYTES:
            return
        cls._cache[key] = frame
        cls._cached_bytes += size
        while cls._cached_bytes > cls.BUDGET_BYTES:
            _key, old = cls._cache.popitem(last=False)
            cls._cached_bytes -= old.width * old.height * 4

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()
        cls._cached_bytes = 0


_READERS: OrderedDict[str, FrameReader] = OrderedDict()
MAX_OPEN_READERS = 16


def frame_reader(asset_id: str, contents: bytes) -> FrameReader:
    """The shared reader of a stored animation (an asset id always designates the same content)."""
    reader = _READERS.get(asset_id)
    if reader is None:
        reader = FrameReader(asset_id, contents)
        _READERS[asset_id] = reader
        while len(_READERS) > MAX_OPEN_READERS:
            _READERS.popitem(last=False)
    _READERS.move_to_end(asset_id)
    return reader


def clear_readers() -> None:
    """Release the decoded frames of the previous document."""
    _READERS.clear()
    FrameReader.clear_cache()
