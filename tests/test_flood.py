"""Span flood fill: same result as Pillow's ImageDraw.floodfill, much faster."""
import random
import time

import pytest
from PIL import Image, ImageDraw

from app import background as B
from app import selection as S


def reference(mask, seed):
    """Former implementation: Pillow's (4-connected) floodfill on a binary mask."""
    binary = mask.point([0] + [255] * 255)
    x, y = seed
    if not (0 <= x < mask.width and 0 <= y < mask.height) or binary.getpixel(seed) == 0:
        return Image.new("L", mask.size, 0)
    ImageDraw.floodfill(binary, seed, 128, thresh=0)
    return binary.point([255 if value == 128 else 0 for value in range(256)])


def from_rows(*rows):
    mask = Image.new("L", (len(rows[0]), len(rows)))
    mask.putdata([255 if char == "#" else 0 for row in rows for char in row])
    return mask


def selected(mask):
    return ["".join("#" if mask.getpixel((x, y)) else "." for x in range(mask.width))
            for y in range(mask.height)]


def test_diagonal_neighbours_are_not_connected():
    mask = from_rows("#..",
                     ".#.",
                     "..#")
    assert selected(S.flood_region(mask, (1, 1))) == ["...", ".#.", "..."]
    assert S.flood_region(mask, (1, 1)).tobytes() == reference(mask, (1, 1)).tobytes()


def test_spans_turn_around_obstacles_and_skip_holes():
    mask = from_rows("#####.#",
                     "#...#.#",
                     "#.#.#.#",
                     "#.#...#",
                     "###.###")
    region = S.flood_region(mask, (0, 0))
    assert selected(region) == ["#####..",
                                "#...#..",
                                "#.#.#..",
                                "#.#....",
                                "###...."]
    assert region.tobytes() == reference(mask, (0, 0)).tobytes()
    # The far column joins through the bottom row only from its own side.
    assert selected(S.flood_region(mask, (6, 0)))[4] == "....###"


@pytest.mark.parametrize("seed", [(-1, 0), (0, -1), (3, 0), (0, 2), (10**6, 10**6)])
def test_seed_outside_the_image_selects_nothing(seed):
    assert S.flood_region(Image.new("L", (3, 2), 255), seed).getbbox() is None


def test_seed_on_a_zero_pixel_selects_nothing():
    mask = from_rows("#.#")
    assert S.flood_region(mask, (1, 0)).getbbox() is None


def test_one_pixel_and_empty_images():
    assert S.flood_region(Image.new("L", (1, 1), 7), (0, 0)).getpixel((0, 0)) == 255
    assert S.flood_region(Image.new("L", (1, 1), 0), (0, 0)).getpixel((0, 0)) == 0
    empty = S.flood_region(Image.new("L", (0, 0)), (0, 0))
    assert empty.size == (0, 0) and empty.mode == "L"


def test_any_non_zero_value_is_fillable_and_result_is_binary():
    mask = Image.new("L", (4, 1))
    mask.putdata([1, 128, 255, 0])
    region = S.flood_region(mask, (0, 0))
    assert region.tobytes() == bytes([255, 255, 255, 0]) and region.mode == "L"


def test_other_modes_are_converted():
    assert S.flood_region(Image.new("1", (3, 3), 1), (1, 1)).getextrema() == (255, 255)


@pytest.mark.parametrize("seed_value", range(12))
def test_equivalent_to_pillow_floodfill_on_random_masks(seed_value):
    rnd = random.Random(seed_value)
    for _ in range(60):
        width, height = rnd.randint(1, 48), rnd.randint(1, 48)
        density = rnd.choice((0.3, 0.5, 0.6, 0.75, 0.95))
        data = bytes(rnd.randint(1, 255) if rnd.random() < density else 0 for _ in range(width * height))
        mask = Image.frombytes("L", (width, height), data)
        seed = (rnd.randint(-1, width), rnd.randint(-1, height))
        assert S.flood_region(mask, seed).tobytes() == reference(mask, seed).tobytes()


def test_equivalent_on_mazes_and_combs():
    comb = Image.new("L", (41, 30))
    draw = ImageDraw.Draw(comb)
    for x in range(0, 41, 2):
        draw.line((x, 0 if x % 4 else 1, x, 29 if x % 4 else 28), fill=255)
    draw.line((0, 0, 40, 0), fill=200)
    draw.line((0, 29, 40, 29), fill=90)
    spiral = Image.new("L", (31, 31))
    draw = ImageDraw.Draw(spiral)
    for step in range(0, 15, 2):
        draw.rectangle((step, step, 30 - step, 30 - step), outline=255)
        draw.point((step + 1, step), fill=0)
    for mask in (comb, spiral):
        for seed in ((0, 0), (2, 5), (15, 15), (40, 29)):
            assert S.flood_region(mask, seed).tobytes() == reference(mask, seed).tobytes()


def test_magic_wand_and_background_use_the_fast_fill_at_2048():
    image = Image.new("RGBA", (2048, 2048), (240, 240, 240, 255))
    ImageDraw.Draw(image).ellipse((512, 512, 1535, 1535), fill=(200, 30, 30, 255))
    started = time.perf_counter()
    wand = S.magic_wand(image, (0, 0), 0)
    keep = B.border_colour_mask(image)
    elapsed = time.perf_counter() - started
    assert wand.getpixel((0, 0)) == 255 and wand.getpixel((1024, 1024)) == 0
    assert keep.getbbox() == (512, 512, 1536, 1536)
    assert elapsed < 1.0  # about 7 s with ImageDraw.floodfill


def test_uniform_region_at_2048_is_fast():
    started = time.perf_counter()
    region = S.flood_region(Image.new("L", (2048, 2048), 255), (1000, 1000))
    assert time.perf_counter() - started < 1.0
    assert region.getextrema() == (255, 255)
