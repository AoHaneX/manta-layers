"""Element templates bundled with Manta Layers.

They are built from shape and text layers, never from pictures, so every part
stays editable once inserted. Colours come from the ReefKit palette.
"""
from __future__ import annotations

from .model import Document, Folder, Layer
from .theme import COLORS

NAVY, PANEL, CYAN, COPPER, LIGHT = (COLORS[key] for key in ("background", "panel", "primary", "copper", "text"))
WHITE = "#FFFFFF"


def _shape(name: str, kind: str, x: float, y: float, width: float, height: float, fill: str | None,
           stroke: str | None = None, stroke_width: float = 0.0, **extra) -> Layer:
    layer = Layer(name=name, kind="shape", shape_type=kind, x=x, y=y, shape_width=width, shape_height=height,
                  fill_color=fill, stroke_color=stroke, stroke_width=stroke_width, **extra)
    layer.normalize_shape_fields()
    return layer


def _text(text: str, x: float, y: float, size: int, color: str) -> Layer:
    return Layer(name=f"Texte : {text}", kind="text", text=text, x=x, y=y, font_size=size, color=color,
                 font_family="Segoe UI")


def _grouped(name: str, width: int, height: int, layers: list[Layer]) -> Document:
    folder = Folder(name=name)
    for layer in layers:
        layer.folder = folder.id
    return Document(width, height, None, layers, {}, [folder])


def _speech() -> Document:
    return _grouped("Bulle de dialogue", 320, 200, [
        _shape("Bulle", "speech", 0, 0, 320, 200, WHITE, NAVY, 4),
        _text("Bonjour !", 70, 38, 36, NAVY),
    ])


def _thought() -> Document:
    return _grouped("Bulle de pensée", 330, 230, [
        _shape("Pensée", "thought", 0, 0, 330, 230, WHITE, NAVY, 4),
        _text("Hmm…", 115, 45, 34, NAVY),
    ])


def _text_box() -> Document:
    return _grouped("Encadré de texte", 380, 150, [
        _shape("Encadré", "rectangle", 0, 0, 380, 150, PANEL, COPPER, 4, corner_radius=18),
        _shape("Filet", "line", 30, 58, 320, 4, None, COPPER, 2),
        _text("Titre de l'encadré", 28, 10, 26, CYAN),
        _text("Votre texte ici", 28, 72, 22, LIGHT),
    ])


def _banner() -> Document:
    return _grouped("Bandeau", 440, 96, [
        _shape("Bandeau", "banner", 0, 0, 440, 96, COPPER, NAVY, 3),
        _text("BANDEAU", 130, 14, 40, NAVY),
    ])


def _label() -> Document:
    return _grouped("Étiquette", 240, 84, [
        _shape("Étiquette", "rectangle", 0, 0, 240, 84, CYAN, NAVY, 3, corner_radius=14),
        _shape("Œillet", "ellipse", 16, 34, 16, 16, NAVY),
        _text("Étiquette", 48, 14, 30, NAVY),
    ])


def _frame() -> Document:
    corners = [_shape(f"Rivet {index + 1}", "ellipse", x, y, 28, 28, COPPER, NAVY, 2)
               for index, (x, y) in enumerate(((-4, -4), (396, -4), (-4, 296), (396, 296)))]
    return _grouped("Cadre décoratif", 420, 320, [
        _shape("Cadre", "rectangle", 0, 0, 420, 320, None, COPPER, 12),
        _shape("Filet intérieur", "rectangle", 18, 18, 384, 284, None, CYAN, 3),
        *corners,
    ])


def _shape_group() -> Document:
    return _grouped("Groupe de formes", 360, 220, [
        _shape("Disque", "ellipse", 0, 40, 140, 140, CYAN, NAVY, 4),
        _shape("Carré", "rectangle", 110, 0, 120, 120, COPPER, NAVY, 4, corner_radius=10),
        _shape("Hexagone", "polygon", 200, 90, 130, 130, PANEL, CYAN, 4),
        _shape("Flèche", "arrow", 40, 190, 180, 28, None, NAVY, 6),
    ])


BUILTIN_TEMPLATES = {
    "builtin-speech": ("Bulle de dialogue", _speech),
    "builtin-thought": ("Bulle de pensée", _thought),
    "builtin-text-box": ("Encadré de texte", _text_box),
    "builtin-banner": ("Bandeau", _banner),
    "builtin-label": ("Étiquette", _label),
    "builtin-frame": ("Cadre décoratif", _frame),
    "builtin-shapes": ("Groupe de formes", _shape_group),
}


def builtin_template(key: str) -> Document:
    """A fresh copy of a bundled template (each call builds new layers)."""
    return BUILTIN_TEMPLATES[key][1]()
