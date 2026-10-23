"""Cas ciblés du pot de peinture ; à exécuter avec la suite à la demande."""
import unittest

from PIL import Image

from app.graphics import _apply_color_fill, apply_eraser_strokes


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


if __name__ == "__main__":
    unittest.main()
