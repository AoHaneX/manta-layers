"""Writing images without Qt: formats, extensions and transparency."""
from pathlib import Path

import pytest
from PIL import Image

from app.export import save_image, with_image_suffix


@pytest.mark.parametrize("name, chosen_filter, expected", [
    ("rendu.png", "", "rendu.png"),
    ("rendu.JPEG", "", "rendu.JPEG"),
    ("rendu", "JPEG (*.jpg)", "rendu.jpg"),
    ("rendu", "WebP (*.webp)", "rendu.webp"),
    ("rendu", "", "rendu.png"),
    # The extension is added, never substituted: "carte.png" may be another file.
    ("carte.final", "PNG (*.png)", "carte.final.png"),
])
def test_image_suffix(name, chosen_filter, expected):
    assert with_image_suffix(Path(name), chosen_filter).name == expected


def test_png_keeps_transparency(tmp_path):
    image = Image.new("RGBA", (4, 3), (10, 20, 30, 40))
    save_image(image, tmp_path / "a.png")
    with Image.open(tmp_path / "a.png") as saved:
        assert saved.mode == "RGBA" and saved.getpixel((1, 1)) == (10, 20, 30, 40)


def test_jpeg_is_flattened_on_white(tmp_path):
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    save_image(image, tmp_path / "a.jpg")
    with Image.open(tmp_path / "a.jpg") as saved:
        assert saved.mode == "RGB" and min(saved.getpixel((4, 4))) > 245


def test_webp_and_other_modes(tmp_path):
    save_image(Image.new("RGB", (5, 5), (255, 0, 0)), tmp_path / "a.webp")
    with Image.open(tmp_path / "a.webp") as saved:
        assert saved.size == (5, 5)


def test_unknown_extension_is_refused(tmp_path):
    with pytest.raises(ValueError):
        save_image(Image.new("RGBA", (2, 2)), tmp_path / "a.tiff")
    assert not (tmp_path / "a.tiff").exists()


def test_the_caller_image_is_left_unchanged(tmp_path):
    image = Image.new("RGBA", (3, 3), (1, 2, 3, 4))
    save_image(image, tmp_path / "a.jpg")
    assert image.mode == "RGBA" and image.getpixel((0, 0)) == (1, 2, 3, 4)
