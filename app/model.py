"""Modèle de document indépendant de Qt, volontairement facile à tester."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

PROJECT_VERSION = 1
MAX_DIMENSION = 16384
LEGACY_PROJECT_FORMAT = "Manta" + "Crab"


def new_id() -> str:
    return uuid4().hex


@dataclass
class Layer:
    id: str = field(default_factory=new_id)
    name: str = "Calque"
    kind: str = "image"  # image | text
    asset: str | None = None
    text: str = ""
    font_family: str = "Arial"
    font_size: int = 56
    color: str = "#000000"
    text_background: str | None = None
    text_deformation: str = "curve"
    curve_intensity: float = 0.0
    character_spacing: float = 0.0
    path_alignment: str = "center"
    path_orientation: str = "tangent"
    show_curve_guide: bool = True
    text_warp: dict | None = None
    x: float = 0.0
    y: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    flip_horizontal: bool = False
    flip_vertical: bool = False
    color_replacements: dict[str, str] = field(default_factory=dict)
    color_fills: list[dict] = field(default_factory=list)
    eraser_strokes: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> Layer:
        permitted = {f.name for f in fields(cls)}
        layer = cls(**{k: v for k, v in raw.items() if k in permitted})
        if layer.kind not in ("image", "text"):
            raise ValueError(f"Type de calque non reconnu : {layer.kind}")
        layer.sx = max(0.05, min(float(layer.sx), 50.0))
        layer.sy = max(0.05, min(float(layer.sy), 50.0))
        layer.opacity = max(0.0, min(float(layer.opacity), 1.0))
        if layer.text_background is not None and not QColorName.is_hex(layer.text_background):
            layer.text_background = None
        # Les anciens projets utilisaient un mode + une intensité positive.
        # Ils sont convertis vers l'unique courbure signée sans perdre le sens.
        legacy_deformation = layer.text_deformation
        layer.curve_intensity = float(layer.curve_intensity)
        if legacy_deformation in {"arc_up", "u_inverted", "wave"}:
            layer.curve_intensity = abs(layer.curve_intensity)
        elif legacy_deformation in {"arc_down", "u"}:
            layer.curve_intensity = -abs(layer.curve_intensity)
        elif legacy_deformation == "straight":
            layer.curve_intensity = 0.0
        layer.text_deformation = "curve"
        layer.curve_intensity = max(-100.0, min(100.0, layer.curve_intensity))
        layer.character_spacing = max(-50.0, min(200.0, float(layer.character_spacing)))
        if layer.path_alignment not in {"left", "center", "right"}:
            layer.path_alignment = "center"
        if layer.path_orientation not in {"tangent", "horizontal"}:
            layer.path_orientation = "tangent"
        if not isinstance(layer.text_warp, (dict, type(None))):
            layer.text_warp = None
        if not isinstance(layer.color_replacements, dict):
            layer.color_replacements = {}
        layer.color_replacements = {
            str(source).upper(): str(target).upper()
            for source, target in layer.color_replacements.items()
            if QColorName.is_hex(source) and QColorName.is_hex(target)
        }
        if not isinstance(layer.color_fills, list):
            layer.color_fills = []
        valid_fills = []
        for raw_fill in layer.color_fills:
            if not isinstance(raw_fill, dict):
                continue
            source, target = raw_fill.get("source"), raw_fill.get("target")
            if not QColorName.is_hex(source) or not QColorName.is_hex(target):
                continue
            try:
                tolerance = max(0, min(255, int(raw_fill.get("tolerance", 0))))
                x, y = int(raw_fill.get("x", -1)), int(raw_fill.get("y", -1))
            except (TypeError, ValueError):
                continue
            valid_fills.append({
                "mode": "global" if raw_fill.get("mode") == "global" else "contiguous",
                "source": source.upper(),
                "target": target.upper(),
                "x": x,
                "y": y,
                "tolerance": tolerance,
                "preserve_shading": bool(raw_fill.get("preserve_shading", False)),
            })
        layer.color_fills = valid_fills
        if not isinstance(layer.eraser_strokes, list):
            layer.eraser_strokes = []
        valid_strokes = []
        for raw_stroke in layer.eraser_strokes:
            if not isinstance(raw_stroke, dict) or not isinstance(raw_stroke.get("points"), list):
                continue
            try:
                points = [[float(point[0]), float(point[1])] for point in raw_stroke["points"]
                          if isinstance(point, (list, tuple)) and len(point) == 2]
                size = max(1, min(2048, int(raw_stroke.get("size", 1))))
                hardness = max(0, min(100, int(raw_stroke.get("hardness", 100))))
                opacity = max(1, min(100, int(raw_stroke.get("opacity", 100))))
            except (TypeError, ValueError):
                continue
            if not points:
                continue
            valid_strokes.append({
                "points": points,
                "size": size,
                "shape": "square" if raw_stroke.get("shape") == "square" else "circle",
                "pixel_art": bool(raw_stroke.get("pixel_art", True)),
                "hardness": hardness,
                "opacity": opacity,
            })
        layer.eraser_strokes = valid_strokes
        return layer


class QColorName:
    @staticmethod
    def is_hex(value) -> bool:
        if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
            return False
        try:
            int(value[1:], 16)
            return True
        except ValueError:
            return False


@dataclass
class Document:
    width: int = 1280
    height: int = 720
    background: str | None = None
    layers: list[Layer] = field(default_factory=list)  # bas -> haut
    assets: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (1 <= int(self.width) <= MAX_DIMENSION and 1 <= int(self.height) <= MAX_DIMENSION):
            raise ValueError("Dimensions du document hors limites")
        self.width, self.height = int(self.width), int(self.height)

    def clone(self) -> Document:
        return Document(self.width, self.height, self.background, deepcopy(self.layers), self.assets.copy())

    def layer(self, layer_id: str | None) -> Layer | None:
        return next((lay for lay in self.layers if lay.id == layer_id), None)

    def add_image_bytes(self, contents: bytes, name: str, center: bool = True) -> Layer:
        with Image.open(BytesIO(contents)) as source:
            source.load()
            if source.width > MAX_DIMENSION or source.height > MAX_DIMENSION:
                raise ValueError("Image trop grande (maximum 16 384 px par dimension)")
            rgba = source.convert("RGBA")
        output = BytesIO()
        rgba.save(output, format="PNG")
        layer = Layer(name=name, kind="image", asset=new_id())
        if center:
            layer.x = float((self.width - rgba.width) / 2)
            layer.y = float((self.height - rgba.height) / 2)
        self.assets[layer.asset] = output.getvalue()
        self.layers.append(layer)
        return layer

    def add_image_file(self, path: str | Path) -> Layer:
        p = Path(path)
        return self.add_image_bytes(p.read_bytes(), p.stem)

    def add_text(self, text: str) -> Layer:
        layer = Layer(name=f"Texte : {text[:28]}", kind="text", text=text,
                      x=self.width * 0.2, y=self.height * 0.42)
        self.layers.append(layer)
        return layer

    def duplicate_layer(self, layer_id: str) -> Layer:
        src = self.layer(layer_id)
        if src is None:
            raise ValueError("Calque introuvable")
        target = deepcopy(src)
        target.id = new_id()
        target.name += " (copie)"
        target.x += 25
        target.y += 25
        idx = self.layers.index(src)
        self.layers.insert(idx + 1, target)
        return target

    def reorder_layer(self, layer_id: str, delta: int) -> bool:
        target = self.layer(layer_id)
        if target is None:
            return False
        index = self.layers.index(target)
        new_index = index + delta
        if not (0 <= new_index < len(self.layers)):
            return False
        self.layers[index], self.layers[new_index] = self.layers[new_index], self.layers[index]
        return True

    def manifest(self) -> dict:
        return {"format": "MantaLayers", "version": PROJECT_VERSION,
                "width": self.width, "height": self.height, "background": self.background,
                "layers": [asdict(lay) for lay in self.layers]}

    @classmethod
    def from_manifest(cls, manifest: dict, assets: dict[str, bytes]) -> Document:
        # L'ancien identifiant reste accepté pour ne pas casser les projets existants.
        if manifest.get("format") not in ("MantaLayers", LEGACY_PROJECT_FORMAT) or manifest.get("version") != PROJECT_VERSION:
            raise ValueError("Format ou version de projet non pris en charge")
        doc = cls(width=manifest["width"], height=manifest["height"],
                  background=manifest.get("background"),
                  layers=[Layer.from_dict(item) for item in manifest["layers"]], assets=assets)
        for layer in doc.layers:
            if layer.kind == "image" and layer.asset not in assets:
                raise ValueError(f"Image manquante pour le calque « {layer.name} »")
        if len({l.id for l in doc.layers}) != len(doc.layers):
            raise ValueError("Identifiants de calques dupliqués")
        return doc
