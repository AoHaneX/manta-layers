"""Selection masks (pure Pillow): shapes, magic wand, alpha and combinations."""
import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app import selection as S

SIZE = (20, 10)


def selected_count(mask):
    return mask.histogram()[255]


def values(mask):
    return {value for value, count in enumerate(mask.histogram()) if count}


def test_pixel_perfect_rectangle_is_exact_and_corner_order_free():
    mask = S.rectangle(SIZE, (12, 8, 2, 3))
    assert mask.getbbox() == (2, 3, 12, 8)
    assert selected_count(mask) == 10 * 5
    assert values(mask) == {0, 255}


@pytest.mark.parametrize("box", [(5, 5, 5, 9), (3, 3, 3.2, 3.2), (-10, -10, -2, -2)])
def test_degenerate_or_outside_rectangles_select_nothing(box):
    assert S.is_empty(S.rectangle(SIZE, box))


def test_rectangle_is_clipped_to_the_document():
    assert S.rectangle(SIZE, (-5, -5, 4, 4)).getbbox() == (0, 0, 4, 4)


def test_pixel_perfect_ellipse_has_hard_edges_and_antialiased_one_is_soft():
    hard = S.ellipse((40, 40), (4, 4, 36, 30))
    soft = S.ellipse((40, 40), (4, 4, 36, 30), antialias=True)
    assert values(hard) == {0, 255}
    assert any(0 < value < 255 for value in values(soft))
    assert hard.getpixel((20, 17)) == 255 and hard.getpixel((5, 5)) == 0


def stripes():
    """Red | almost red | blue | red, plus one transparent red column."""
    image = Image.new("RGBA", (5, 1))
    image.putdata([(200, 0, 0, 255), (210, 5, 0, 255), (0, 0, 255, 255),
                   (200, 0, 0, 255), (200, 0, 0, 0)])
    return image


def test_magic_wand_contiguous_stops_at_other_colours():
    mask = S.magic_wand(stripes(), (0, 0), 10)
    assert [mask.getpixel((x, 0)) for x in range(5)] == [255, 255, 0, 0, 0]


def test_magic_wand_global_selects_every_similar_colour_but_not_transparent_pixels():
    mask = S.magic_wand(stripes(), (0, 0), 10, contiguous=False)
    assert [mask.getpixel((x, 0)) for x in range(5)] == [255, 255, 0, 255, 0]


def test_magic_wand_tolerance_boundary_is_inclusive():
    assert S.magic_wand(stripes(), (0, 0), 9).getpixel((1, 0)) == 0
    assert S.magic_wand(stripes(), (0, 0), 10).getpixel((1, 0)) == 255


def test_magic_wand_on_transparent_pixel_selects_transparency_only():
    mask = S.magic_wand(stripes(), (4, 0), 0, contiguous=False)
    assert [mask.getpixel((x, 0)) for x in range(5)] == [0, 0, 0, 0, 255]


def test_magic_wand_compares_alpha_of_semi_transparent_pixels():
    image = Image.new("RGBA", (2, 1))
    image.putdata([(50, 50, 50, 255), (50, 50, 50, 120)])
    assert S.magic_wand(image, (0, 0), 100).getpixel((1, 0)) == 0
    assert S.magic_wand(image, (0, 0), 135).getpixel((1, 0)) == 255


def test_magic_wand_on_tiny_images_and_outside_seed():
    one = Image.new("RGBA", (1, 1), (1, 2, 3, 255))
    assert S.magic_wand(one, (0, 0), 0).getpixel((0, 0)) == 255
    assert S.is_empty(S.magic_wand(one, (3, 0), 0))


def test_combination_modes():
    left = S.rectangle(SIZE, (0, 0, 10, 10))
    middle = S.rectangle(SIZE, (5, 0, 15, 10))
    assert S.combine(left, middle, "replace").getbbox() == (5, 0, 15, 10)
    assert S.combine(left, middle, "add").getbbox() == (0, 0, 15, 10)
    assert S.combine(left, middle, "subtract").getbbox() == (0, 0, 5, 10)
    assert S.combine(left, middle, "intersect").getbbox() == (5, 0, 10, 10)
    assert S.combine(None, middle, "subtract").getbbox() == (5, 0, 15, 10)
    with pytest.raises(ValueError):
        S.combine(left, middle, "xor")


def test_feather_softens_edges_and_zero_radius_is_identity():
    mask = S.rectangle((30, 30), (10, 10, 20, 20))
    assert S.feather(mask, 0) is mask
    soft = S.feather(mask, 3)
    assert 0 < soft.getpixel((9, 15)) < 255


def test_invert_translate_and_resize_canvas():
    mask = S.rectangle(SIZE, (0, 0, 4, 4))
    assert S.invert(mask).getpixel((0, 0)) == 0
    assert S.translate(mask, 3, 2).getbbox() == (3, 2, 7, 6)
    assert S.translate(mask, -10, 0).getbbox() is None
    assert S.resize_canvas(mask, (6, 6)).size == (6, 6)


def test_layer_mask_hide_and_reveal():
    area = S.rectangle((4, 4), (0, 0, 2, 4))
    hidden = S.hide(None, area)
    assert (hidden.getpixel((0, 0)), hidden.getpixel((3, 0))) == (0, 255)
    assert S.reveal(hidden, area).getextrema() == (255, 255)


def test_apply_alpha_keeps_colours_and_multiplies_transparency():
    image = Image.new("RGBA", (2, 1), (10, 20, 30, 200))
    mask = Image.new("L", (2, 1))
    mask.putdata([255, 128])
    result = S.apply_alpha(image, mask)
    assert result.getpixel((0, 0)) == (10, 20, 30, 200)
    assert result.getpixel((1, 0))[:3] == (10, 20, 30) and result.getpixel((1, 0))[3] == 100


def test_encode_decode_roundtrip():
    mask = S.ellipse((17, 9), (1, 1, 16, 8), antialias=True)
    assert S.decode(S.encode(mask)).tobytes() == mask.tobytes()


@pytest.mark.parametrize("side, expected", [(1, 1), (2, 4)])
def test_tiny_ellipses_still_select_their_pixels(side, expected):
    assert selected_count(S.ellipse((5, 5), (0, 0, side, side))) == expected


# --- Bounded supersampling ------------------------------------------------------


def reference_polygon(size, points, antialias=False):
    """Former implementation (uncapped x4 supersampling), kept to check equivalence."""
    mask = S.empty(size)
    vertices = [(float(x), float(y)) for x, y in points]
    if len(set(vertices)) < 3:
        return mask
    xs, ys = [x for x, _ in vertices], [y for _, y in vertices]
    area = (max(0, int(min(xs)) - 1), max(0, int(min(ys)) - 1),
            min(size[0], int(max(xs)) + 2), min(size[1], int(max(ys)) + 2))
    if area[2] <= area[0] or area[3] <= area[1]:
        return mask
    big = Image.new("L", ((area[2] - area[0]) * 4, (area[3] - area[1]) * 4), 0)
    ImageDraw.Draw(big).polygon([((x - area[0]) * 4 - 0.5, (y - area[1]) * 4 - 0.5)
                                 for x, y in vertices], fill=255)
    mask.paste(big.resize((area[2] - area[0], area[3] - area[1]), Image.Resampling.BOX), area[:2])
    return mask if antialias else mask.point([0] * 128 + [255] * 128)


def reference_shape(size, box, draw_ellipse):
    """Former antialiased rectangle / ellipse."""
    mask = S.empty(size)
    x0, y0, x1, y1 = box
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    if right - left < 0.5 or bottom - top < 0.5:
        return mask
    area = (max(0, int(left) - 1), max(0, int(top) - 1),
            min(size[0], int(right) + 2), min(size[1], int(bottom) + 2))
    if area[2] <= area[0] or area[3] <= area[1]:
        return mask
    big = Image.new("L", ((area[2] - area[0]) * 4, (area[3] - area[1]) * 4), 0)
    shape = ((left - area[0]) * 4, (top - area[1]) * 4, (right - area[0]) * 4 - 1, (bottom - area[1]) * 4 - 1)
    draw = ImageDraw.Draw(big)
    (draw.ellipse if draw_ellipse else draw.rectangle)(shape, fill=255)
    mask.paste(big.resize((area[2] - area[0], area[3] - area[1]), Image.Resampling.BOX), area[:2])
    return mask


def random_shapes(seed, count):
    rnd = random.Random(seed)
    for _ in range(count):
        size = (rnd.randint(1, 80), rnd.randint(1, 80))
        points = [(rnd.uniform(-20, 100), rnd.uniform(-20, 100)) for _ in range(rnd.randint(3, 9))]
        if rnd.random() < 0.3:
            points = [(round(x), round(y)) for x, y in points]
        yield size, points, tuple(rnd.uniform(-20, 100) for _ in range(4))


@pytest.mark.parametrize("seed", range(4))
def test_supersampled_shapes_are_unchanged_up_to_4096(seed):
    for size, points, box in random_shapes(seed, 150):
        for antialias in (False, True):
            assert S.polygon(size, points, antialias).tobytes() == \
                reference_polygon(size, points, antialias).tobytes()
        assert S.ellipse(size, box, True).tobytes() == reference_shape(size, box, True).tobytes()
        assert S.rectangle(size, box, True).tobytes() == reference_shape(size, box, False).tobytes()


def test_full_document_lasso_at_4096_is_unchanged():
    side = 4096
    points = [(0.3, 0), (side, 0.7), (side * 0.71, side * 0.93), (0, side)]
    assert S._supersampling_scale((0, 0, side, side)) == 4
    assert S.polygon((side, side), points, True).tobytes() == \
        reference_polygon((side, side), points, True).tobytes()


@pytest.mark.parametrize("side, scale", [(1, 4), (4096, 4), (4097, 3), (8192, 2), (16384, 1)])
def test_supersampling_factor_drops_on_huge_areas(side, scale):
    assert S._supersampling_scale((0, 0, side, side)) == scale


@pytest.mark.parametrize("seed", range(3))
def test_bands_join_without_seams(monkeypatch, seed):
    # A low side limit forces the reduced factor (and banding) on small images.
    monkeypatch.setattr(S, "SUPERSAMPLED_SIDE_LIMIT", 60)
    rnd = random.Random(seed)
    for size, points, box in random_shapes(seed, 60):
        monkeypatch.setattr(S, "SUPERSAMPLED_BAND_PIXELS", 1 << 25)
        whole = [S.polygon(size, points, True), S.polygon(size, points), S.ellipse(size, box, True),
                 S.rectangle(size, box, True)]
        monkeypatch.setattr(S, "SUPERSAMPLED_BAND_PIXELS", rnd.randint(1, 2000))
        banded = [S.polygon(size, points, True), S.polygon(size, points), S.ellipse(size, box, True),
                  S.rectangle(size, box, True)]
        assert [mask.tobytes() for mask in whole] == [mask.tobytes() for mask in banded]


def test_thin_shapes_without_supersampling_do_not_fail(monkeypatch):
    monkeypatch.setattr(S, "SUPERSAMPLED_SIDE_LIMIT", 10)  # factor 1 on a 20 px area
    assert S.ellipse((30, 30), (2.2, 2, 2.8, 22), True).size == (30, 30)
    assert S.rectangle((30, 30), (2, 2.2, 22, 2.8), True).size == (30, 30)


PEAK_MEMORY_SCRIPT = r"""
import sys, time
from app import selection

def peak():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged", "nonpaged",
                    "pagefile", "peak_pagefile")]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not ctypes.windll.kernel32.K32GetProcessMemoryInfo(
                wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo")
        return counters.peak_pagefile  # peak committed memory
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage if sys.platform == "darwin" else usage * 1024

side = 8192
before = peak()
started = time.perf_counter()
mask = selection.polygon((side, side), [(0, 0), (side, 0), (side, side), (0, side)], antialias=True)
elapsed = time.perf_counter() - started
assert mask.getextrema() == (255, 255)
print((peak() - before) / 2**20, elapsed)
"""


def test_full_document_lasso_at_8192_has_bounded_memory():
    # Pillow allocates image buffers in C, outside tracemalloc's view: the peak
    # memory of a separate process is measured instead (about 1.4 GB before the
    # cap, 112 MB with it).
    if sys.platform not in ("win32", "linux", "darwin"):
        pytest.skip("peak memory measurement not available")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", PEAK_MEMORY_SCRIPT], cwd=root, capture_output=True,
                            text=True, timeout=120, check=True)
    peak_mib, elapsed = map(float, result.stdout.split())
    assert peak_mib < 300
    assert elapsed < 2
