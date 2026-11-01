"""Local background removal, tested with synthetic images and fake models only."""
import dataclasses
import hashlib
import http.client
import io
import re

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
    def __init__(self, data, announced=None, final_url=None, length_header=True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if announced is None else announced)}             if length_header else {}
        if final_url is not None:
            self.geturl = lambda: final_url

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


FAKE_MODEL = b"onnx" * 1000


@pytest.fixture
def fake_digest(monkeypatch):
    """Pin u2netp to the digest of the fake model served by the tests."""
    spec = dataclasses.replace(B.KNOWN_MODELS["u2netp"], digest="md5:" + hashlib.md5(FAKE_MODEL).hexdigest())
    monkeypatch.setitem(B.KNOWN_MODELS, "u2netp", spec)
    return spec


def test_known_models_pin_a_digest():
    for spec in B.KNOWN_MODELS.values():
        assert re.fullmatch(r"md5:[0-9a-f]{32}", spec.digest)


def test_download_writes_the_model_atomically(tmp_path, fake_digest):
    seen = []
    path = B.download_model("u2netp", tmp_path, lambda _m, p: seen.append(p),
                            opener=lambda url, timeout: (seen.append(url), FakeResponse(FAKE_MODEL))[1])
    assert path.read_bytes() == FAKE_MODEL
    assert seen[0].endswith("/u2netp.onnx") and seen[-1] == 100
    assert not list(tmp_path.glob("*.part"))


def test_download_with_another_digest_is_refused(tmp_path):
    # The real u2netp digest cannot match the fake model.
    with pytest.raises(B.BackgroundRemovalError, match="empreinte"):
        B.download_model("u2netp", tmp_path, opener=lambda url, timeout: FakeResponse(FAKE_MODEL))
    assert list(tmp_path.iterdir()) == []


def test_download_without_digest_skips_the_check(tmp_path, monkeypatch):
    monkeypatch.setitem(B.KNOWN_MODELS, "u2netp", dataclasses.replace(B.KNOWN_MODELS["u2netp"], digest=None))
    path = B.download_model("u2netp", tmp_path, opener=lambda url, timeout: FakeResponse(b"other"))
    assert path.read_bytes() == b"other"


def test_redirect_to_https_is_accepted(tmp_path, fake_digest):
    final = "https://objects.githubusercontent.com/github-production-release-asset/u2netp.onnx"
    path = B.download_model("u2netp", tmp_path,
                            opener=lambda url, timeout: FakeResponse(FAKE_MODEL, final_url=final))
    assert path.read_bytes() == FAKE_MODEL


@pytest.mark.parametrize("final", ["http://example.com/u2netp.onnx", "ftp://example.com/u2netp.onnx"])
def test_final_address_must_be_https(tmp_path, fake_digest, final):
    with pytest.raises(B.BackgroundRemovalError, match="non sécurisée"):
        B.download_model("u2netp", tmp_path, opener=lambda url, timeout: FakeResponse(FAKE_MODEL, final_url=final))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("length_header", [True, False])
def test_oversized_downloads_are_refused(tmp_path, monkeypatch, length_header):
    # 0.001 MB x 1.2 allows 1258 bytes: the 4000-byte stream is too long,
    # whether announced or not.
    spec = dataclasses.replace(B.KNOWN_MODELS["u2netp"], download_size_mb=0.001, digest=None)
    monkeypatch.setitem(B.KNOWN_MODELS, "u2netp", spec)
    with pytest.raises(B.BackgroundRemovalError, match="plus gros que prévu"):
        B.download_model("u2netp", tmp_path,
                         opener=lambda url, timeout: FakeResponse(FAKE_MODEL, length_header=length_header))
    assert list(tmp_path.iterdir()) == []


def test_download_within_the_size_margin_is_accepted(tmp_path, monkeypatch):
    spec = dataclasses.replace(B.KNOWN_MODELS["u2netp"], download_size_mb=4000 / 1_048_576 / 1.15, digest=None)
    monkeypatch.setitem(B.KNOWN_MODELS, "u2netp", spec)
    path = B.download_model("u2netp", tmp_path,
                            opener=lambda url, timeout: FakeResponse(FAKE_MODEL, length_header=False))
    assert path.stat().st_size == 4000


def test_failing_progress_callback_leaves_no_partial_file(tmp_path, fake_digest):
    def broken_progress(_message, _percent):
        raise RuntimeError("interface closed")

    with pytest.raises(RuntimeError):
        B.download_model("u2netp", tmp_path, broken_progress,
                         opener=lambda url, timeout: FakeResponse(FAKE_MODEL))
    assert list(tmp_path.iterdir()) == []


class TruncatedResponse(FakeResponse):
    def read(self, size=-1):
        raise http.client.IncompleteRead(b"x")  # an HTTPException, not an OSError


@pytest.mark.parametrize("response", [
    lambda: FakeResponse(b"x" * 10, announced="dix"),  # malformed Content-Length
    lambda: TruncatedResponse(b"x" * 10),
])
def test_protocol_errors_are_reported_and_leave_no_file(tmp_path, response):
    with pytest.raises(B.BackgroundRemovalError, match="Téléchargement impossible"):
        B.download_model("u2netp", tmp_path, opener=lambda url, timeout: response())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("announced, cancelled, message", [(9999, False, "incomplet"), (None, True, "annulé")])
def test_failed_downloads_leave_no_file(tmp_path, announced, cancelled, message):
    with pytest.raises(B.BackgroundRemovalError, match=message):
        B.download_model("u2netp", tmp_path, cancelled=lambda: cancelled,
                         opener=lambda url, timeout: FakeResponse(b"x" * 10, announced))
    assert list(tmp_path.iterdir()) == []


def test_unknown_models_are_never_downloaded(tmp_path):
    with pytest.raises(B.BackgroundRemovalError):
        B.download_model("../../etc", tmp_path, opener=lambda *a, **k: pytest.fail("network used"))
