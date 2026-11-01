"""Tests purs Python : fonctionnent sans PySide6 ni interface graphique."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

from PIL import Image

from app.model import Document, Layer
from app.storage import open_project, save_project


def image_bytes():
    image = Image.new("RGBA", (11, 7), (15, 200, 240, 128))
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


class ModelTests(unittest.TestCase):
    def test_image_layer_asset_and_alpha(self):
        doc = Document(200, 100)
        layer = doc.add_image_bytes(image_bytes(), "image alpha")
        self.assertEqual((layer.x, layer.y), (94.5, 46.5))
        self.assertEqual(layer.kind, "image")
        image = Image.open(io.BytesIO(doc.assets[layer.asset]))
        self.assertEqual(image.getpixel((0,0))[3], 128)

    def test_clone_independence(self):
        doc = Document(640,480)
        lay = doc.add_text("Manta")
        copy = doc.clone()
        copy.layer(lay.id).x = 99
        self.assertNotEqual(doc.layer(lay.id).x, copy.layer(lay.id).x)

    def test_duplicate_and_reorder(self):
        doc = Document()
        first = doc.add_text("Premier")
        second = doc.duplicate_layer(first.id)
        self.assertNotEqual(first.id, second.id)
        self.assertFalse(doc.reorder_layer(second.id, 1))
        self.assertTrue(doc.reorder_layer(second.id, -1))
        self.assertEqual(doc.layers[0].id, second.id)

    def test_project_roundtrip(self):
        doc = Document(1024,768,background="#00AAFF")
        im = doc.add_image_bytes(image_bytes(), "alpha")
        im.rotation = 30.0
        im.sx = 0.45
        im.eraser_strokes.append({
            "points": [[1.0, 2.0], [4.0, 2.0]], "size": 4,
            "shape": "square", "pixel_art": True, "hardness": 100, "opacity": 100, "pixel_centered": True,
        })
        text = doc.add_text("Bonjour la manta")
        text.font_family = "Verdana"
        text.color = "#F0E1D2"
        text.opacity = 0.3
        text.text_deformation = "arc"
        text.curve_intensity = 72.0
        text.character_spacing = 2.5
        text.path_alignment = "right"
        text.path_orientation = "horizontal"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "test.manta"
            save_project(doc,dest)
            loaded = open_project(dest)
            self.assertEqual(loaded.manifest(),doc.manifest())
            self.assertEqual(loaded.assets,doc.assets)
            with ZipFile(dest) as z:
                self.assertIn("manifest.json",z.namelist())
                self.assertIn(f"assets/{im.asset}.png",z.namelist())

    def test_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/"bad.manta"
            with ZipFile(dest,"w") as z:
                z.writestr("manifest.json", json.dumps({"format":"Unknown","version":1,"width":5,"height":5,"layers":[]}))
            with self.assertRaises(ValueError):
                open_project(dest)

    def test_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            Document(0,42)
        with self.assertRaises(ValueError):
            Document(20000,42)

    def test_oversized_image_is_rejected_before_decoding(self):
        with mock.patch("app.model.MAX_PIXELS", 50):
            with self.assertRaises(ValueError):
                Document().add_image_bytes(image_bytes(), "trop grande")

    def test_corrupted_layer_values_fall_back_to_defaults(self):
        layer = Layer.from_dict({
            "id": "abc", "kind": "text", "font_size": "énorme", "color": "rouge",
            "x": "nan", "rotation": None, "visible": "oui", "name": 42,
            "path_alignment": ["left"], "text_deformation": {"mode": "arc"},
            "color_fills": [{"source": "#000000", "target": "#FFFFFF", "after_strokes": "x"}],
        })
        self.assertEqual((layer.font_size, layer.color, layer.x, layer.rotation),
                         (56, "#000000", 0.0, 0.0))
        self.assertTrue(layer.visible)
        self.assertEqual(layer.name, "Calque")
        self.assertEqual(layer.path_alignment, "center")
        self.assertEqual(layer.color_fills, [])

    def test_malformed_manifest_is_reported_as_invalid_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            for manifest in ([], {"format": "MantaLayers", "version": 1,
                                  "width": 5, "height": 5, "layers": "aucun"}):
                dest = Path(tmp) / "bad.manta"
                with ZipFile(dest, "w") as z:
                    z.writestr("manifest.json", json.dumps(manifest))
                with self.assertRaises(ValueError):
                    open_project(dest)


if __name__ == '__main__':
    unittest.main()
