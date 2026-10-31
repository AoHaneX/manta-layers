"""Image import: accepted formats, EXIF orientation and stored size."""
import io
from unittest import mock

import pytest
from PIL import Image, UnidentifiedImageError

from app import storage
from app.graphics import render_layer_image
from app.model import MAX_ASSET_BYTES, MAX_PIXELS, Document


def encoded(image, fmt, **options):
    output = io.BytesIO()
    image.save(output, format=fmt, **options)
    return output.getvalue()


def stored(doc, layer):
    return Image.open(io.BytesIO(doc.assets[layer.asset]))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP", "GIF"])
def test_supported_formats_are_imported(fmt):
    doc = Document(50, 50)
    layer = doc.add_image_bytes(encoded(Image.new("RGB", (8, 6), (200, 30, 30)), fmt), "img")
    assert stored(doc, layer).size == (8, 6)


@pytest.mark.parametrize("fmt", ["TIFF", "ICO", "PPM"])
def test_other_formats_are_refused_whatever_the_file_name(fmt):
    # Pillow would recognise these from their content alone.
    with pytest.raises(ValueError, match="Format d'image non pris en charge"):
        Document(50, 50).add_image_bytes(encoded(Image.new("RGB", (8, 6)), fmt), "renamed.png")


def test_project_assets_must_be_png():
    jpeg = encoded(Image.new("RGB", (8, 6)), "JPEG")
    with pytest.raises(UnidentifiedImageError):
        render_layer_image(jpeg, {})


def test_exif_orientation_is_applied_to_photos():
    # Left half red, right half blue; orientation 6 means "rotate 90 degrees clockwise".
    photo = Image.new("RGB", (40, 20), (220, 0, 0))
    photo.paste((0, 0, 220), (20, 0, 40, 20))
    exif = Image.Exif()
    exif[0x0112] = 6
    doc = Document(100, 100)
    image = stored(doc, doc.add_image_bytes(encoded(photo, "JPEG", exif=exif.tobytes()), "photo"))
    assert image.size == (20, 40)
    top, bottom = image.getpixel((10, 5)), image.getpixel((10, 35))
    assert top[0] > 150 > top[2]
    assert bottom[2] > 150 > bottom[0]


def test_any_importable_image_fits_in_a_project():
    # A noisy 8192 x 8192 image weighs about 4 bytes per pixel even as PNG:
    # the project reader must accept what the importer accepts.
    assert storage.MAX_ASSET_BYTES == MAX_ASSET_BYTES
    assert MAX_ASSET_BYTES > MAX_PIXELS * 4 * 1.05


def test_an_image_too_heavy_for_a_project_is_refused_on_import():
    noise = Image.effect_noise((64, 64), 100).convert("RGB")
    with mock.patch("app.model.MAX_ASSET_BYTES", 1000):
        with pytest.raises(ValueError, match="trop volumineuse"):
            Document(100, 100).add_image_bytes(encoded(noise, "PNG"), "noise")
