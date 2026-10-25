"""Selection masks (pure Pillow): shapes, magic wand, alpha and combinations."""
import pytest
from PIL import Image

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
