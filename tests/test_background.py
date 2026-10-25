"""Local background removal, tested with synthetic images and fake models only."""
import io

import pytest
from PIL import Image, ImageDraw

from app import background as B


def disc_on_flat_background(hole=False):
    image = Image.new("RGBA", (60, 40), (240, 240, 240, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((15, 5, 45, 35), fill=(200, 30, 30, 255))
    if hole:  # background-coloured area enclosed in the object must be kept
        draw.rectangle((27, 17, 33, 23), fill=(240, 240, 240, 255))
    return image


def test_border_colour_removes_the_flat_background_only():
    mask = B.border_colour_mask(disc_on_flat_background())
    assert mask.getpixel((2, 2)) == 0 and mask.getpixel((30, 20)) == 255
    assert mask.getbbox() == (15, 5, 46, 36)


def test_enclosed_areas_of_background_colour_are_kept():
    mask = B.border_colour_mask(disc_on_flat_background(hole=True))
    assert mask.getpixel((30, 20)) == 255


def test_tolerance_absorbs_noise_in_the_background():
    image = disc_on_flat_background()
    image.putpixel((0, 39), (230, 236, 244, 255))
    assert B.border_colour_mask(image, tolerance=2).getpixel((0, 39)) == 255
    assert B.border_colour_mask(image, tolerance=15).getpixel((0, 39)) == 0


def test_already_transparent_background_keeps_the_opaque_subject():
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    image.paste((10, 200, 10, 255), (3, 3, 7, 7))
    mask = B.border_colour_mask(image)
    assert mask.getbbox() == (3, 3, 7, 7)
    assert B.dominant_border_colour(image) == (0, 0, 0, 0)


def test_tiny_images_and_feathering():
    assert B.border_colour_mask(Image.new("RGBA", (1, 1), (5, 5, 5, 255))).getpixel((0, 0)) == 0
    soft = B.border_colour_mask(disc_on_flat_background(), feather=2)
    assert any(0 < soft.getpixel((x, 20)) < 255 for x in range(10, 20))


def test_refine_and_preview_keep_existing_transparency():
    mask = Image.new("L", (2, 1))
    mask.putdata([200, 60])
    refined = B.refine(mask, True, 0)
    assert (refined.getpixel((0, 0)), refined.getpixel((1, 0))) == (255, 0)
    image = Image.new("RGBA", (2, 1), (9, 9, 9, 100))
    assert B.preview(image, Image.new("L", (2, 1), 255)).getpixel((0, 0))[3] == 100


def test_model_specs_and_installed_models(tmp_path):
    assert B.spec_for(tmp_path / "u2netp.onnx").input_size == 320
    assert B.spec_for(tmp_path / "isnet-anime.onnx").input_size == 1024
    assert B.spec_for(tmp_path / "custom.onnx").mean == (0.485, 0.456, 0.406)
    assert B.installed_models(tmp_path / "missing") == []
    (tmp_path / "b.onnx").write_bytes(b"x")
    (tmp_path / "a.onnx").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    assert [path.name for path in B.installed_models(tmp_path)] == ["a.onnx", "b.onnx"]


class FakeSession:
    """Mimics onnxruntime.InferenceSession: predicts a disc in the centre."""

    def __init__(self, path, ndim=4):
        self.ndim = ndim

    def get_inputs(self):
        return [type("Input", (), {"name": "input.1"})()]

    def run(self, _outputs, feeds):
        np = pytest.importorskip("numpy")
        tensor = feeds["input.1"]
        assert tensor.shape == (1, 3, 320, 320) and tensor.dtype == np.float32
        y, x = np.mgrid[:320, :320]
        disc = ((x - 160) ** 2 + (y - 160) ** 2 < 80 ** 2).astype(np.float32) * 0.9 + 0.05
        return [disc.reshape((1,) * (self.ndim - 2) + disc.shape)]


def test_onnx_pipeline_with_a_fake_session(tmp_path):
    pytest.importorskip("numpy")
    model = tmp_path / "u2netp.onnx"
    model.write_bytes(b"fake")
    steps = []
    mask = B.onnx_mask(Image.new("RGB", (100, 50)), model, lambda _m, p: steps.append(p),
                       session_factory=FakeSession)
    assert mask.size == (100, 50) and mask.mode == "L"
    assert mask.getpixel((50, 25)) == 255 and mask.getpixel((2, 2)) == 0
    assert steps == [10, 30, 50, 90, 100]


def test_onnx_errors_are_reported_to_the_user(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    with pytest.raises(B.BackgroundRemovalError, match="introuvable"):
        B.onnx_mask(Image.new("RGB", (4, 4)), tmp_path / "absent.onnx")
    model = tmp_path / "model.onnx"
    model.write_bytes(b"fake")
    with pytest.raises(B.BackgroundRemovalError, match="inattendue"):
        B.onnx_mask(Image.new("RGB", (4, 4)), model, session_factory=lambda path: _BrokenShape())
    monkeypatch.setattr(B, "onnx_runtime_available", lambda: False)
    with pytest.raises(B.BackgroundRemovalError, match="requirements-ai"):
        B.onnx_mask(Image.new("RGB", (4, 4)), model)


class _BrokenShape(FakeSession):
    def __init__(self):
        super().__init__(None)

    def run(self, _outputs, _feeds):
        np = pytest.importorskip("numpy")
        return [np.zeros((1, 3, 8, 8), dtype=np.float32)]


class FakeResponse(io.BytesIO):
    def __init__(self, data, announced=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if announced is None else announced)}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def test_download_writes_the_model_atomically(tmp_path):
    seen = []
    path = B.download_model("u2netp", tmp_path, lambda _m, p: seen.append(p),
                            opener=lambda url, timeout: (seen.append(url), FakeResponse(b"onnx" * 1000))[1])
    assert path.read_bytes() == b"onnx" * 1000
    assert seen[0].endswith("/u2netp.onnx") and seen[-1] == 100
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("announced, cancelled, message", [(9999, False, "incomplet"), (None, True, "annulé")])
def test_failed_downloads_leave_no_file(tmp_path, announced, cancelled, message):
    with pytest.raises(B.BackgroundRemovalError, match=message):
        B.download_model("u2netp", tmp_path, cancelled=lambda: cancelled,
                         opener=lambda url, timeout: FakeResponse(b"x" * 10, announced))
    assert list(tmp_path.iterdir()) == []


def test_unknown_models_are_never_downloaded(tmp_path):
    with pytest.raises(B.BackgroundRemovalError):
        B.download_model("../../etc", tmp_path, opener=lambda *a, **k: pytest.fail("network used"))
