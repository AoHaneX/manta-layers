"""Modèle de document indépendant de Qt, volontairement facile à tester."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from io import BytesIO
from math import isfinite
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .textpath import DEFAULT_CONTROLS, normalize_controls, normalize_shape

# Version 2 adds text path shapes, Bézier controls and layer masks.
# Version 3 adds layer folders and shape layers. A project that uses neither is
# still written as version 2, so that older Manta Layers releases keep opening it.
# Version 1 projects still open: their fields are converted on load.
PROJECT_VERSION = 3
COMPATIBLE_VERSION = 2
SUPPORTED_VERSIONS = (1, 2, 3)
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
LAYER_KINDS = ("image", "text", "shape")
# Speech and thought bubbles and banners are used by the bundled templates.
SHAPE_TYPES = ("rectangle", "ellipse", "line", "arrow", "polygon", "speech", "thought", "banner")
MIN_SHAPE_SIZE = 1.0
MAX_STROKE_WIDTH = 500.0


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
    # Folder containing the layer (see Folder), None at the top level.
    folder: str | None = None
    # Vector shape layers: geometry in item coordinates, drawn in a
    # shape_width × shape_height box whose top-left corner is the layer position.
    shape_type: str = "rectangle"
    shape_width: float = 200.0
    shape_height: float = 120.0
    fill_color: str | None = None
    stroke_color: str | None = "#000000"
    stroke_width: float = 0.0
    corner_radius: float = 0.0
    polygon_sides: int = 6

    @classmethod
    def from_dict(cls, raw: dict) -> Layer:
        if not isinstance(raw, dict):
            raise ValueError("Calque invalide dans le projet")
        permitted = {f.name for f in fields(cls)}
        layer = cls(**{k: v for k, v in raw.items() if k in permitted})
        defaults = cls()
        if layer.kind not in LAYER_KINDS:
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
        if layer.folder is not None and (not isinstance(layer.folder, str) or not layer.folder):
            layer.folder = None
        layer.normalize_shape_fields()
        return layer

    def normalize_shape_fields(self) -> None:
        """Clamp the shape properties to valid values (corrupted files, edits)."""
        if self.shape_type not in SHAPE_TYPES:
            self.shape_type = "rectangle"
        self.shape_width = _number(self.shape_width, 200.0, MIN_SHAPE_SIZE, MAX_DIMENSION * 2)
        self.shape_height = _number(self.shape_height, 120.0, MIN_SHAPE_SIZE, MAX_DIMENSION * 2)
        if self.fill_color is not None and not is_hex_color(self.fill_color):
            self.fill_color = None
        if self.stroke_color is not None and not is_hex_color(self.stroke_color):
            self.stroke_color = None
        self.stroke_width = _number(self.stroke_width, 0.0, 0.0, MAX_STROKE_WIDTH)
        self.corner_radius = _number(self.corner_radius, 0.0, 0.0, MAX_DIMENSION)
        self.polygon_sides = int(_number(self.polygon_sides, 6, 3, 24))


@dataclass
class Folder:
    """Named group of layers. Its layers stay separate and editable.

    Members are the layers whose ``folder`` is this id; they always form a
    contiguous block in the stacking order (see Document.normalize_folders).
    """

    id: str = field(default_factory=new_id)
    name: str = "Dossier"
    visible: bool = True
    collapsed: bool = False

    @classmethod
    def from_dict(cls, raw) -> Folder:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise ValueError("Dossier de calques invalide")
        name, visible, collapsed = raw.get("name"), raw.get("visible"), raw.get("collapsed")
        return cls(
            id=raw["id"],
            name=name if isinstance(name, str) and name.strip() else "Dossier",
            visible=visible if isinstance(visible, bool) else True,
            collapsed=collapsed if isinstance(collapsed, bool) else False,
        )


@dataclass
class Document:
    width: int = 1280
    height: int = 720
    background: str | None = None
    layers: list[Layer] = field(default_factory=list)  # bas -> haut
    assets: dict[str, bytes] = field(default_factory=dict)
    folders: list[Folder] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            width, height = int(self.width), int(self.height)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Dimensions du document invalides") from exc
        if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
            raise ValueError("Dimensions du document hors limites")
        self.width, self.height = width, height

    def clone(self) -> Document:
        return Document(self.width, self.height, self.background, deepcopy(self.layers), self.assets.copy(),
                        deepcopy(self.folders))

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
        """Move a layer one step up (+1) or down (-1) in the stack.

        A layer at the edge of its folder leaves it; a top-level layer steps
        over a whole neighbouring folder instead of entering it.
        """
        target = self.layer(layer_id)
        if target is None:
            return False
        index = self.layers.index(target)
        new_index = index + delta
        if not (0 <= new_index < len(self.layers)):
            return False
        neighbour = self.layers[new_index]
        if target.folder is not None and neighbour.folder != target.folder:
            target.folder = None
        elif target.folder is None and neighbour.folder is not None:
            block = self.folder_members(neighbour.folder)
            edge = block[-1] if delta > 0 else block[0]
            self.layers.remove(target)
            self.layers.insert(self.layers.index(edge) + (1 if delta > 0 else 0), target)
        else:
            self.layers[index], self.layers[new_index] = neighbour, target
        self.normalize_folders()
        return True

    # --- Folders -----------------------------------------------------------------------

    def folder(self, folder_id: str | None) -> Folder | None:
        return next((item for item in self.folders if item.id == folder_id), None)

    def folder_members(self, folder_id: str | None) -> list[Layer]:
        """Layers of a folder, bottom to top."""
        return [layer for layer in self.layers if folder_id is not None and layer.folder == folder_id]

    def is_visible(self, layer: Layer) -> bool:
        """Effective visibility: the layer and its folder must both be shown."""
        folder = self.folder(layer.folder)
        return layer.visible and (folder is None or folder.visible)

    def normalize_folders(self) -> None:
        """Keep the folder structure valid after any change.

        Unknown folder references are dropped, the members of each folder are
        regrouped into one contiguous block at the place of their topmost layer,
        and folders left without layers are removed.
        """
        known = {item.id for item in self.folders}
        for layer in self.layers:
            if layer.folder not in known:
                layer.folder = None
        for item in self.folders:
            indices = [index for index, layer in enumerate(self.layers) if layer.folder == item.id]
            if not indices or indices[-1] - indices[0] + 1 == len(indices):
                continue
            members = [self.layers[index] for index in indices]
            others = [layer for layer in self.layers if layer.folder != item.id]
            position = sum(1 for layer in self.layers[:indices[-1]] if layer.folder != item.id)
            self.layers = others[:position] + members + others[position:]
        used = {layer.folder for layer in self.layers}
        self.folders = [item for item in self.folders if item.id in used]

    def create_folder(self, layer_ids, name: str) -> Folder:
        """Group layers into a new folder placed where the topmost of them was."""
        wanted = set(layer_ids)
        members = [layer for layer in self.layers if layer.id in wanted]
        if not members:
            raise ValueError("Aucun calque à regrouper")
        clean_name = " ".join(str(name).split()) or "Dossier"
        top = max(self.layers.index(layer) for layer in members)
        others = [layer for layer in self.layers if layer.id not in wanted]
        position = sum(1 for layer in self.layers[:top] if layer.id not in wanted)
        folder = Folder(name=clean_name)
        self.folders.append(folder)
        for layer in members:
            layer.folder = folder.id
        self.layers = others[:position] + members + others[position:]
        self.normalize_folders()
        return folder

    def dissolve_folder(self, folder_id: str) -> None:
        """Remove a folder but keep its layers, in place, at the top level."""
        for layer in self.folder_members(folder_id):
            layer.folder = None
        self.normalize_folders()

    def remove_layers(self, layer_ids) -> int:
        wanted = set(layer_ids)
        before = len(self.layers)
        self.layers = [layer for layer in self.layers if layer.id not in wanted]
        self.normalize_folders()
        return before - len(self.layers)

    def move_layer(self, layer_id: str, anchor_id: str | None, above: bool, folder_id: str | None) -> bool:
        """Move a layer next to ``anchor_id`` (or to an end of the stack), into ``folder_id``."""
        layer = self.layer(layer_id)
        anchor = self.layer(anchor_id) if anchor_id is not None else None
        if layer is None or (anchor_id is not None and anchor is None):
            return False
        if anchor is layer:
            if layer.folder == folder_id:
                return False
            layer.folder = folder_id
            self.normalize_folders()
            return True
        self.layers.remove(layer)
        if anchor is None:
            index = len(self.layers) if above else 0
        else:
            index = self.layers.index(anchor) + (1 if above else 0)
        self.layers.insert(index, layer)
        layer.folder = folder_id if self.folder(folder_id) is not None else None
        self.normalize_folders()
        return True

    def move_folder(self, folder_id: str, anchor_id: str | None, above: bool) -> bool:
        """Move a whole folder above or below a layer (outside any other folder)."""
        members = self.folder_members(folder_id)
        anchor = self.layer(anchor_id) if anchor_id is not None else None
        if not members or (anchor_id is not None and anchor is None) or anchor in members:
            return False
        if anchor is not None and anchor.folder is not None:
            block = self.folder_members(anchor.folder)
            anchor = block[-1] if above else block[0]
        others = [layer for layer in self.layers if layer.folder != folder_id]
        if anchor is None:
            index = len(others) if above else 0
        else:
            index = others.index(anchor) + (1 if above else 0)
        self.layers = others[:index] + members + others[index:]
        self.normalize_folders()
        return True

    def uses_version_3(self) -> bool:
        return bool(self.folders) or any(layer.kind == "shape" for layer in self.layers)

    def manifest(self) -> dict:
        manifest = {"format": "MantaLayers",
                    "version": PROJECT_VERSION if self.uses_version_3() else COMPATIBLE_VERSION,
                    "width": self.width, "height": self.height, "background": self.background,
                    "layers": [asdict(lay) for lay in self.layers]}
        if self.folders:
            manifest["folders"] = [asdict(item) for item in self.folders]
        return manifest

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
        if len({layer.id for layer in doc.layers}) != len(doc.layers):
            raise ValueError("Identifiants de calques dupliqués")
        raw_folders = manifest.get("folders", [])
        if not isinstance(raw_folders, list):
            raise ValueError("Liste de dossiers invalide")
        folders = [Folder.from_dict(item) for item in raw_folders]
        if len({item.id for item in folders}) != len(folders):
            raise ValueError("Identifiants de dossiers dupliqués")
        doc.folders = folders
        doc.normalize_folders()
        return doc
