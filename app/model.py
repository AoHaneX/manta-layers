"""Modèle de document indépendant de Qt, volontairement facile à tester."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from io import BytesIO
from math import isfinite
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .textpath import DEFAULT_CONTROLS, normalize_controls, normalize_shape

# Version 2 adds text path shapes, Bézier controls and layer masks.
# Version 1 projects still open: their fields are converted on load.
PROJECT_VERSION = 2
SUPPORTED_VERSIONS = (1, 2)
MAX_DIMENSION = 16384
# Au-delà, le décodage et l'affichage d'un calque deviennent trop coûteux en mémoire
# (une image RGBA de 8192 × 8192 occupe déjà 256 Mo une fois décodée).
MAX_PIXELS = 8192 * 8192
# Worst case of a MAX_PIXELS RGBA image stored as PNG (incompressible noise),
# with a margin: any image accepted on import can be saved and reopened.
MAX_ASSET_BYTES = 300 * 1024 * 1024
# Only these decoders ever see user files: Pillow would otherwise pick any
# plugin from the file content, whatever its extension.
IMPORT_FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "GIF")
# Project assets and masks are always written as PNG.
ASSET_FORMATS = ("PNG",)
# Ancien nom du logiciel : les projets .mcrab portent encore cet identifiant.
LEGACY_PROJECT_FORMAT = "MantaCrab"


def new_id() -> str:
    return uuid4().hex


def is_hex_color(value) -> bool:
    """Vrai pour une couleur « #RRGGBB »."""
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


def _number(value, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    """Nombre fini borné ; une valeur corrompue reprend la valeur par défaut."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not isfinite(number):
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


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
    # Path shape: straight | arc | u | u_inverted | custom (see app/textpath.py).
    text_deformation: str = "straight"
    curve_intensity: float = 0.0
    # Bézier control points of the custom shape, as fractions of the path width.
    path_controls: list[list[float]] = field(
        default_factory=lambda: [list(point) for point in DEFAULT_CONTROLS]
    )
    character_spacing: float = 0.0
    path_alignment: str = "center"
    path_orientation: str = "tangent"
    show_curve_guide: bool = True
    # Réservés : futur moteur Warp et rôles des calques de modèle. Ils sont
    # conservés tels quels dans les projets mais pas encore exploités.
    text_warp: dict | None = None
    template_role: str = "fixed"
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
    # Optional non-destructive layer mask: asset id of an 8-bit PNG the size of
    # the source image (255 visible, 0 hidden). Used by selections and background removal.
    mask: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> Layer:
        if not isinstance(raw, dict):
            raise ValueError("Calque invalide dans le projet")
        permitted = {f.name for f in fields(cls)}
        layer = cls(**{k: v for k, v in raw.items() if k in permitted})
        defaults = cls()
        if layer.kind not in ("image", "text"):
            raise ValueError(f"Type de calque non reconnu : {layer.kind}")
        if not isinstance(layer.id, str) or not layer.id:
            raise ValueError("Identifiant de calque invalide")
        if layer.asset is not None and not isinstance(layer.asset, str):
            raise ValueError("Référence d'image invalide")
        if layer.mask is not None and (not isinstance(layer.mask, str) or layer.kind != "image"):
            layer.mask = None
        for name in ("name", "text", "font_family"):
            if not isinstance(getattr(layer, name), str):
                setattr(layer, name, getattr(defaults, name))
        for name in ("visible", "locked", "flip_horizontal", "flip_vertical", "show_curve_guide"):
            if not isinstance(getattr(layer, name), bool):
                setattr(layer, name, getattr(defaults, name))
        layer.x = _number(layer.x, 0.0)
        layer.y = _number(layer.y, 0.0)
        layer.rotation = _number(layer.rotation, 0.0)
        layer.sx = _number(layer.sx, 1.0, 0.05, 50.0)
        layer.sy = _number(layer.sy, 1.0, 0.05, 50.0)
        layer.opacity = _number(layer.opacity, 1.0, 0.0, 1.0)
        layer.font_size = int(_number(layer.font_size, defaults.font_size, 8, 300))
        if not is_hex_color(layer.color):
            layer.color = defaults.color
        if layer.text_background is not None and not is_hex_color(layer.text_background):
            layer.text_background = None
        # Legacy deformation names (signed "curve", directional modes) map to a shape.
        layer.text_deformation, layer.curve_intensity = normalize_shape(
            layer.text_deformation, _number(layer.curve_intensity, 0.0)
        )
        layer.path_controls = normalize_controls(layer.path_controls)
        layer.character_spacing = _number(layer.character_spacing, 0.0, -50.0, 200.0)
        if layer.path_alignment not in ("left", "center", "right"):
            layer.path_alignment = "center"
        if layer.path_orientation not in ("tangent", "horizontal"):
            layer.path_orientation = "tangent"
        if not isinstance(layer.text_warp, (dict, type(None))):
            layer.text_warp = None
        if layer.template_role not in ("fixed", "replaceable_text", "replaceable_image"):
            layer.template_role = "fixed"
        if not isinstance(layer.color_replacements, dict):
            layer.color_replacements = {}
        layer.color_replacements = {
            str(source).upper(): str(target).upper()
            for source, target in layer.color_replacements.items()
            if is_hex_color(source) and is_hex_color(target)
        }
        if not isinstance(layer.color_fills, list):
            layer.color_fills = []
        valid_fills = []
        for raw_fill in layer.color_fills:
            if not isinstance(raw_fill, dict):
                continue
            source, target = raw_fill.get("source"), raw_fill.get("target")
            if not is_hex_color(source) or not is_hex_color(target):
                continue
            try:
                tolerance = max(0, min(255, int(raw_fill.get("tolerance", 0))))
                x, y = int(raw_fill.get("x", -1)), int(raw_fill.get("y", -1))
                after_strokes = max(0, int(raw_fill.get("after_strokes", 0)))
            except (TypeError, ValueError, OverflowError):
                continue
            valid_fills.append({
                "mode": "global" if raw_fill.get("mode") == "global" else "contiguous",
                "source": source.upper(),
                "target": target.upper(),
                "x": x,
                "y": y,
                "tolerance": tolerance,
                "preserve_shading": bool(raw_fill.get("preserve_shading", False)),
                # Nombre de traits de gomme déjà présents lors du remplissage :
                # le rendu rejoue ainsi gomme et remplissages dans leur ordre réel.
                "after_strokes": after_strokes,
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
            except (TypeError, ValueError, OverflowError):
                continue
            points = [point for point in points if isfinite(point[0]) and isfinite(point[1])]
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


@dataclass
class Document:
    width: int = 1280
    height: int = 720
    background: str | None = None
    layers: list[Layer] = field(default_factory=list)  # bas -> haut
    assets: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            width, height = int(self.width), int(self.height)
        except (TypeError, ValueError) as exc:
            raise ValueError("Dimensions du document invalides") from exc
        if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
            raise ValueError("Dimensions du document hors limites")
        self.width, self.height = width, height

    def clone(self) -> Document:
        return Document(self.width, self.height, self.background, deepcopy(self.layers), self.assets.copy())

    def layer(self, layer_id: str | None) -> Layer | None:
        return next((lay for lay in self.layers if lay.id == layer_id), None)

    def add_image_bytes(self, contents: bytes, name: str, center: bool = True) -> Layer:
        try:
            source = Image.open(BytesIO(contents), formats=IMPORT_FORMATS)
        except UnidentifiedImageError as exc:
            raise ValueError("Format d'image non pris en charge (PNG, JPEG, WebP, BMP ou GIF)") from exc
        with source:
            if source.width > MAX_DIMENSION or source.height > MAX_DIMENSION:
                raise ValueError("Image trop grande (maximum 16 384 px par dimension)")
            if source.width * source.height > MAX_PIXELS:
                raise ValueError(
                    f"Image trop grande ({source.width} × {source.height} px) : "
                    "maximum 67 mégapixels, soit 8192 × 8192 px"
                )
            source.load()
            # Phone photos store their rotation in EXIF instead of in the pixels.
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
        output = BytesIO()
        rgba.save(output, format="PNG")
        if output.tell() > MAX_ASSET_BYTES:
            raise ValueError("Image trop volumineuse une fois enregistrée dans le projet")
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
        first_line = text.split("\n", 1)[0]
        layer = Layer(name=f"Texte : {first_line[:28]}", kind="text", text=text,
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
        if not isinstance(manifest, dict):
            raise ValueError("Manifeste de projet invalide")
        # L'ancien identifiant reste accepté pour ne pas casser les projets existants.
        if manifest.get("format") not in ("MantaLayers", LEGACY_PROJECT_FORMAT):
            raise ValueError("Format de projet non pris en charge")
        version = manifest.get("version")
        if isinstance(version, int) and not isinstance(version, bool) and version > PROJECT_VERSION:
            raise ValueError(
                f"Ce projet utilise le format {version}, créé par une version plus récente de Manta Layers"
            )
        if version not in SUPPORTED_VERSIONS:
            raise ValueError("Version de projet non prise en charge")
        raw_layers = manifest.get("layers")
        if not isinstance(raw_layers, list):
            raise ValueError("Liste de calques invalide")
        background = manifest.get("background")
        doc = cls(width=manifest.get("width"), height=manifest.get("height"),
                  background=background if is_hex_color(background) else None,
                  layers=[Layer.from_dict(item) for item in raw_layers], assets=assets)
        for layer in doc.layers:
            if layer.kind == "image" and layer.asset not in assets:
                raise ValueError(f"Image manquante pour le calque « {layer.name} »")
            if layer.mask is not None and layer.mask not in assets:
                # A lost mask only hides less: keep the layer, drop the mask.
                layer.mask = None
        if len({l.id for l in doc.layers}) != len(doc.layers):
            raise ValueError("Identifiants de calques dupliqués")
        return doc
