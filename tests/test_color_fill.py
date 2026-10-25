"""Cas ciblés du pot de peinture ; à exécuter avec la suite à la demande."""
import io
import unittest

from PIL import Image

from app.graphics import _apply_color_fill, apply_eraser_strokes, render_layer_image


class ColorFillTests(unittest.TestCase):
    def test_global_tolerance_and_transparency(self):
        image = Image.new("RGBA", (4, 1))
        image.putdata([
            (100, 100, 100, 255),
            (112, 108, 95, 255),
            (116, 100, 100, 255),
            (100, 100, 100, 0),
        ])
        result = _apply_color_fill(
            image, (100, 100, 100), (10, 20, 30), 15, "global", None, False
        )
        self.assertEqual(result.getpixel((0, 0)), (10, 20, 30, 255))
        self.assertEqual(result.getpixel((1, 0)), (10, 20, 30, 255))
        self.assertEqual(result.getpixel((2, 0)), (116, 100, 100, 255))
        self.assertEqual(result.getpixel((3, 0)), (100, 100, 100, 0))

    def test_contiguous_fill_leaves_separate_zone_unchanged(self):
        image = Image.new("RGBA", (5, 1))
        image.putdata([
            (100, 100, 100, 255),
            (110, 105, 100, 255),
            (220, 220, 220, 255),
            (105, 100, 100, 255),
            (100, 100, 100, 255),
        ])
        result = _apply_color_fill(
            image, (100, 100, 100), (0, 80, 160), 15, "contiguous", (0, 0), False
        )
        self.assertEqual(result.getpixel((1, 0))[:3], (0, 80, 160))
        self.assertEqual(result.getpixel((3, 0))[:3], (105, 100, 100))

    def test_smart_recolor_preserves_lightness_difference(self):
        image = Image.new("RGBA", (2, 1))
        image.putdata([(100, 100, 100, 255), (110, 110, 110, 128)])
        result = _apply_color_fill(
            image, (100, 100, 100), (20, 80, 140), 15, "global", None, True
        )
        self.assertEqual(result.getpixel((0, 0)), (20, 80, 140, 255))
        self.assertEqual(result.getpixel((1, 0)), (30, 90, 150, 128))

    def test_pixel_eraser_sizes_are_exact_and_keep_rgb(self):
        for size in (1, 4, 8):
            with self.subTest(size=size):
                image = Image.new("RGBA", (20, 20), (12, 34, 56, 255))
                result = apply_eraser_strokes(image, [{
                    "points": [[10, 10]], "size": size, "shape": "square",
                    "pixel_art": True, "hardness": 100, "opacity": 100,
                }])
                transparent = result.getchannel("A").histogram()[0]
                self.assertEqual(transparent, size * size)
                self.assertEqual(result.getpixel((10, 10))[:3], (12, 34, 56))

    def test_eraser_opacity_is_progressive(self):
        image = Image.new("RGBA", (3, 3), (10, 20, 30, 200))
        result = apply_eraser_strokes(image, [{
            "points": [[1, 1]], "size": 1, "shape": "square",
            "pixel_art": True, "hardness": 100, "opacity": 50,
        }])
        self.assertIn(result.getpixel((1, 1))[3], (99, 100))
        self.assertEqual(result.getpixel((0, 0))[3], 200)

    def test_eraser_opacity_does_not_accumulate_along_a_stroke(self):
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 255))
        result = apply_eraser_strokes(image, [{
            "points": [[5, 20], [35, 20]], "size": 8, "shape": "square",
            "pixel_art": True, "hardness": 100, "opacity": 25,
        }])
        self.assertAlmostEqual(result.getpixel((20, 20))[3], 191, delta=1)

    def test_contiguous_fill_respects_earlier_erasure(self):
        source = Image.new("RGBA", (5, 1), (100, 100, 100, 255))
        output = io.BytesIO()
        source.save(output, format="PNG")
        stroke = {"points": [[2, 0]], "size": 1, "shape": "square",
                  "pixel_art": True, "hardness": 100, "opacity": 100}
        fill = {"mode": "contiguous", "source": "#646464", "target": "#FF0000",
                "x": 0, "y": 0, "tolerance": 0, "preserve_shading": False}
        # Remplissage fait après le trait : la zone gommée sépare les deux côtés.
        after = render_layer_image(output.getvalue(), {}, [{**fill, "after_strokes": 1}], [stroke])
        self.assertEqual(after.getpixel((1, 0))[:3], (255, 0, 0))
        self.assertEqual(after.getpixel((4, 0))[:3], (100, 100, 100))
        # Ancien projet ou remplissage antérieur au trait : comportement inchangé.
        before = render_layer_image(output.getvalue(), {}, [fill], [stroke])
        self.assertEqual(before.getpixel((4, 0))[:3], (255, 0, 0))
        self.assertEqual(before.getpixel((2, 0))[3], 0)


if __name__ == "__main__":
    unittest.main()
