"""Time of a document with animated layers, shared by the preview and the export (no Qt).

Every animation starts at 0 and loops forever: at the global time t, a layer
shows the frame playing at ``t % its duration``. The document lasts as long
as its longest animation, whatever the frame rates and frame counts.
"""
from __future__ import annotations

from bisect import bisect_right
from itertools import accumulate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Document, Layer


def frame_index(durations: list[int], time_ms: float) -> int:
    """Frame shown at ``time_ms`` by an animation with these frame durations, looping."""
    total = sum(durations)
    if len(durations) < 2 or total <= 0:
        return 0
    local = time_ms % total
    return min(len(durations) - 1, bisect_right(list(accumulate(durations)), local))


def layer_frame(layer: Layer, time_ms: float) -> int:
    return frame_index(layer.frame_durations, time_ms) if layer.is_animated else 0


def animated_layers(document: Document) -> list[Layer]:
    return [layer for layer in document.layers if layer.is_animated]


def document_duration(document: Document) -> int:
    """Length of the document's animation: its longest animated layer, 0 without any.

    Hidden or transparent layers count too: showing them again must not change the length.
    """
    return max((sum(layer.frame_durations) for layer in animated_layers(document)), default=0)


def frame_changes(document: Document) -> list[int]:
    """Instants (ms) where at least one animated layer changes frame, from 0 to the end, loops included."""
    end = document_duration(document)
    changes = {0}
    for layer in animated_layers(document):
        total = sum(layer.frame_durations)
        starts = [0, *accumulate(layer.frame_durations)][:-1]
        for loop_start in range(0, end, total):
            changes.update(loop_start + start for start in starts if loop_start + start < end)
    return sorted(changes)


def export_segments(document: Document, quantum: int = 1, minimum: int = 20) -> list[tuple[int, int]]:
    """(instant, display time) of each output frame, in ms, covering the whole document duration.

    Instants are snapped to ``quantum`` (10 ms for GIF, whose delays are in
    hundredths of a second). A frame shorter than ``minimum`` is merged into
    the previous one: viewers would show such short delays for 100 ms.
    """
    end = document_duration(document)
    if end <= 0:
        return [(0, 0)]
    instants = sorted({round(change / quantum) * quantum for change in frame_changes(document)} | {0})
    instants = [instant for instant in instants if instant < end]
    segments: list[tuple[int, int]] = []
    for index, instant in enumerate(instants):
        following = instants[index + 1] if index + 1 < len(instants) else end
        length = following - instant
        if segments and (length < minimum or segments[-1][1] < minimum):
            start, previous = segments[-1]
            segments[-1] = (start, previous + length)  # shown for the merged time, at its own instant
        else:
            segments.append((instant, length))
    return segments


def format_time(time_ms: float) -> str:
    """« 1,25 s » or « 1 min 05,0 s »."""
    seconds = max(0.0, time_ms) / 1000
    if seconds < 60:
        return f"{seconds:.2f} s".replace(".", ",")
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)} min {rest:04.1f} s".replace(".", ",")
