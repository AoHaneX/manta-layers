"""Tests de sérialisation de la bibliothèque locale de modèles."""
import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from app.model import Document
from app.storage import open_project
from app.templates import (
    delete_template,
    duplicate_template,
    instantiate_template,
    list_templates,
    read_template_info,
    rename_template,
    save_template,
)


def image_bytes():
    image = Image.new("RGBA", (8, 6), (20, 80, 160, 180))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class TemplateTests(unittest.TestCase):
    def test_template_roundtrip_preserves_document_and_thumbnail(self):
        document = Document(900, 500, "#123456")
        image = document.add_image_bytes(image_bytes(), "Décor")
        image.rotation = 17
        text = document.add_text("Titre")
        text.font_family = "Verdana"
        text.path_alignment = "right"
        text.curve_intensity = -35
        with tempfile.TemporaryDirectory() as tmp:
            path = save_template(document, "Bannière", b"preview", tmp)
            info = read_template_info(path)
            restored = open_project(path)
            self.assertEqual((info.name, info.width, info.height), ("Bannière", 900, 500))
            self.assertEqual(info.thumbnail, b"preview")
            self.assertEqual(restored.manifest(), document.manifest())
            self.assertEqual(restored.assets, document.assets)

    def test_instantiation_locks_layers_without_modifying_template(self):
        document = Document()
        document.add_image_bytes(image_bytes(), "Image")
        document.add_text("Texte")
        with tempfile.TemporaryDirectory() as tmp:
            path = save_template(document, "Carte", None, tmp)
            instance = instantiate_template(path)
            self.assertTrue(all(layer.locked for layer in instance.layers))
            instance.layers[0].name = "Modifié"
            original = open_project(path)
            self.assertTrue(all(not layer.locked for layer in original.layers))
            self.assertNotEqual(instance.layers[0].name, original.layers[0].name)

    def test_library_rename_duplicate_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_template(Document(320, 200), "Premier", None, tmp)
            rename_template(path, "Renommé")
            copy = duplicate_template(path, tmp)
            self.assertEqual([item.name for item in list_templates(tmp)],
                             ["Renommé", "Renommé (copie)"])
            delete_template(copy)
            self.assertEqual([item.name for item in list_templates(tmp)], ["Renommé"])

    def test_a_damaged_template_is_skipped_by_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_template(Document(320, 200), "Valide", None, tmp)
            # JSON reads 1e400 as infinity, which used to break the whole gallery.
            with ZipFile(Path(tmp) / "infini.manta", "w") as archive:
                archive.writestr("manifest.json", '{"format": "MantaLayers", "version": 2, '
                                                  '"width": 1e400, "height": 10, "layers": []}')
            (Path(tmp) / "illisible.manta").write_bytes(b"pas un zip")
            with self.assertRaises(ValueError):
                read_template_info(Path(tmp) / "infini.manta")
            self.assertEqual([item.name for item in list_templates(tmp)], ["Valide"])


if __name__ == "__main__":
    unittest.main()
