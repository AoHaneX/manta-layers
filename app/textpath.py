"""Pure geometry of text paths.

This module has no Qt dependency so the shapes can be unit-tested. Every
function works in the text item's local coordinates: x runs from 0 to the
path width and ``dy`` is the vertical offset from the baseline, growing
downwards like Qt's y axis.
"""
from __future__ import annotations

from math import cos, isfinite, pi, sin

TEXT_SHAPES = ("straight", "arc", "u", "u_inverted", "custom")
SHAPE_LABELS = {
    "straight": "Droit",
    "arc": "Arc",
    "u": "U",
    "u_inverted": "U inversé",
    "custom": "Courbe personnalisée",
}
# Two cubic Bézier control points, expressed as fractions of the path width.
DEFAULT_CONTROLS = ((0.25, -0.2), (0.75, 0.2))
CONTROL_LIMIT = 1.0


def normalize_shape(deformation, intensity: float) -> tuple[str, float]:
    """Map current and legacy deformation names to a shape and an intensity.

    Older projects stored either a single signed ``curve`` or one of several
    directional modes with a positive intensity. A missing, non-numeric or
    non-finite intensity counts as 0 (no bending) instead of raising.
    """
    try:
        intensity = float(intensity)
    except (TypeError, ValueError, OverflowError):
        intensity = 0.0
    if not isfinite(intensity):
        intensity = 0.0
    intensity = max(-100.0, min(100.0, intensity))
    if not isinstance(deformation, str):
        deformation = "arc"
    if deformation == "curve":
        return ("straight", 0.0) if intensity == 0 else ("arc", intensity)
    if deformation == "arc_up":
        return "arc", abs(intensity)
    if deformation == "arc_down":
        return "arc", -abs(intensity)
    if deformation == "wave":
        return "custom", intensity
    if deformation in ("u", "u_inverted"):
        return deformation, abs(intensity)
    if deformation in TEXT_SHAPES:
        return deformation, intensity
    return "arc", intensity


def normalize_controls(raw) -> list[list[float]]:
    """Return two valid control points, falling back to the default S curve."""
    try:
        points = [[float(x), float(y)] for x, y in raw]
    except (TypeError, ValueError):
        points = []
    if len(points) != 2 or not all(isfinite(v) for point in points for v in point):
        return [list(point) for point in DEFAULT_CONTROLS]
    return [[max(0.0, min(1.0, x)), max(-CONTROL_LIMIT, min(CONTROL_LIMIT, y))] for x, y in points]


def u_depth(width: float, intensity: float) -> float:
    # At 100 the U becomes a half circle whose diameter is the path width.
    return width / 2 * abs(intensity) / 100


def _bezier(points, s: float) -> tuple[float, float]:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points
    inv = 1 - s
    a, b, c, d = inv ** 3, 3 * inv * inv * s, 3 * inv * s * s, s ** 3
    return a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3


def custom_points(width: float, controls) -> list[tuple[float, float]]:
    (c1x, c1y), (c2x, c2y) = normalize_controls(controls)
    return [(0.0, 0.0), (c1x * width, c1y * width), (c2x * width, c2y * width), (width, 0.0)]


def sample_path(
    shape: str,
    intensity: float,
    controls,
    width: float,
    arc_amplitude: float,
    samples: int = 64,
) -> list[tuple[float, float]]:
    """Polyline approximating the path, from x = 0 to x = width."""
    samples = max(2, int(samples))
    width = max(1.0, float(width))
    if shape == "arc":
        amplitude = arc_amplitude * intensity / 100
        return [(width * t, -4.0 * t * (1.0 - t) * amplitude)
                for t in (index / samples for index in range(samples + 1))]
    if shape in ("u", "u_inverted"):
        # Sampling by angle keeps the steep ends of the half ellipse smooth.
        depth = u_depth(width, intensity) * (1 if shape == "u" else -1)
        return [(width * (1 - cos(theta)) / 2, depth * sin(theta))
                for theta in (pi * index / samples for index in range(samples + 1))]
    if shape == "custom":
        points = custom_points(width, controls)
        return [_bezier(points, index / samples) for index in range(samples + 1)]
    return [(width * index / samples, 0.0) for index in range(samples + 1)]


def handle_points(shape: str, intensity: float, controls, width: float,
                  arc_amplitude: float) -> list[tuple[float, float]]:
    """Interactive handles of the shape: its apex, or the Bézier control points."""
    if shape == "custom":
        return custom_points(width, controls)[1:3]
    if shape == "arc":
        return [(width / 2, -arc_amplitude * intensity / 100)]
    if shape in ("u", "u_inverted"):
        depth = u_depth(width, intensity)
        return [(width / 2, depth if shape == "u" else -depth)]
    return [(width / 2, 0.0)]


def drag_handle(shape: str, index: int, x: float, dy: float, width: float, arc_amplitude: float,
                intensity: float, controls) -> tuple[str, float, list[list[float]]]:
    """New (shape, intensity, controls) after moving handle ``index`` to (x, dy).

    Dragging the apex of a straight text turns it into an arc.
    """
    width = max(1.0, float(width))
    controls = normalize_controls(controls)
    if shape == "custom":
        controls[index] = [max(0.0, min(1.0, x / width)),
                           max(-CONTROL_LIMIT, min(CONTROL_LIMIT, dy / width))]
        return shape, intensity, controls
    if shape in ("u", "u_inverted"):
        value = dy / (width / 2) * 100 * (1 if shape == "u" else -1)
        return shape, max(0.0, min(100.0, value)), controls
    value = -dy / max(1e-9, arc_amplitude) * 100
    return "arc", max(-100.0, min(100.0, value)), controls
