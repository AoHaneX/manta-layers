"""Pure geometry of text paths (no Qt)."""
import pytest

from app.model import Layer
from app.textpath import DEFAULT_CONTROLS, drag_handle, handle_points, normalize_controls, normalize_shape, sample_path

WIDTH, ARC = 400.0, 112.0


def test_straight_path_is_flat_and_spans_the_width():
    points = sample_path("straight", 80, None, WIDTH, ARC, 16)
    assert points[0] == (0.0, 0.0)
    assert points[-1][0] == pytest.approx(WIDTH)
    assert all(dy == 0 for _x, dy in points)


@pytest.mark.parametrize("intensity", [65.0, -40.0])
def test_arc_apex_matches_intensity_and_sign(intensity):
    points = sample_path("arc", intensity, None, WIDTH, ARC, 64)
    middle = points[32]
    assert middle[0] == pytest.approx(WIDTH / 2)
    assert middle[1] == pytest.approx(-ARC * intensity / 100)
    assert points[0][1] == pytest.approx(0) and points[-1][1] == pytest.approx(0)


def test_u_shapes_are_half_ellipses_on_opposite_sides():
    u = sample_path("u", 100, None, WIDTH, ARC, 64)
    inverted = sample_path("u_inverted", 100, None, WIDTH, ARC, 64)
    assert max(dy for _x, dy in u) == pytest.approx(WIDTH / 2)
    assert all(dy >= -1e-9 for _x, dy in u)
    assert all(dy <= 1e-9 for _x, dy in inverted)
    assert u[0][0] == pytest.approx(0) and u[-1][0] == pytest.approx(WIDTH)
    # Steep ends: the first sample already rises much more than it advances.
    assert u[1][1] > u[1][0]


def test_u_ignores_the_sign_of_the_intensity():
    assert sample_path("u", -50, None, WIDTH, ARC) == sample_path("u", 50, None, WIDTH, ARC)


def test_custom_bezier_starts_and_ends_on_the_baseline():
    controls = [[0.2, -0.5], [0.8, 0.5]]
    points = sample_path("custom", 0, controls, WIDTH, ARC, 50)
    assert points[0] == pytest.approx((0, 0))
    assert points[-1] == pytest.approx((WIDTH, 0))
    assert min(dy for _x, dy in points) < 0 < max(dy for _x, dy in points)


@pytest.mark.parametrize("raw, intensity, expected", [
    ("curve", 0, ("straight", 0.0)),
    ("curve", -30, ("arc", -30.0)),
    ("arc_up", -30, ("arc", 30.0)),
    ("arc_down", 30, ("arc", -30.0)),
    ("u", -45, ("u", 45.0)),
    ("u_inverted", 45, ("u_inverted", 45.0)),
    ("wave", 20, ("custom", 20.0)),
    ("straight", 10, ("straight", 10.0)),
    ("inconnu", 10, ("arc", 10.0)),
    (None, 500, ("arc", 100.0)),
])
def test_legacy_and_current_names_are_normalized(raw, intensity, expected):
    assert normalize_shape(raw, intensity) == expected


@pytest.mark.parametrize("raw", [None, "abc", [[1, 2]], [[0.1, "x"], [0.2, 0.3]], [[float("nan"), 0], [1, 1]]])
def test_invalid_controls_fall_back_to_default(raw):
    assert normalize_controls(raw) == [list(point) for point in DEFAULT_CONTROLS]


def test_controls_are_clamped():
    assert normalize_controls([[-1, 5], [2, -5]]) == [[0.0, 1.0], [1.0, -1.0]]


@pytest.mark.parametrize("shape, intensity", [("arc", 35.0), ("arc", -80.0), ("u", 60.0), ("u_inverted", 25.0)])
def test_dragging_a_handle_to_its_own_position_keeps_the_shape(shape, intensity):
    (x, dy), = handle_points(shape, intensity, None, WIDTH, ARC)
    assert drag_handle(shape, 0, x, dy, WIDTH, ARC, intensity, None)[:2] == pytest.approx((shape, intensity))


def test_dragging_a_straight_text_turns_it_into_an_arc():
    shape, intensity, _controls = drag_handle("straight", 0, WIDTH / 2, -ARC / 2, WIDTH, ARC, 0, None)
    assert (shape, intensity) == ("arc", pytest.approx(50.0))


def test_u_drag_is_clamped_to_its_side():
    assert drag_handle("u", 0, WIDTH / 2, -100, WIDTH, ARC, 50, None)[1] == 0.0
    assert drag_handle("u", 0, WIDTH / 2, 10_000, WIDTH, ARC, 50, None)[1] == 100.0


def test_dragging_a_custom_control_point_moves_only_that_point():
    shape, _intensity, controls = drag_handle("custom", 1, WIDTH * 0.6, WIDTH * 0.3, WIDTH, ARC, 0,
                                              [[0.1, 0.1], [0.9, 0.9]])
    assert shape == "custom"
    assert controls == [[0.1, 0.1], pytest.approx([0.6, 0.3])]


def test_layer_from_dict_restores_text_shape_and_controls():
    layer = Layer.from_dict({"id": "t", "kind": "text", "text": "Manta",
                             "text_deformation": "custom", "path_controls": [[0.3, -0.4], [0.7, 0.4]],
                             "path_orientation": "horizontal"})
    assert (layer.text_deformation, layer.path_controls, layer.path_orientation) == \
        ("custom", [[0.3, -0.4], [0.7, 0.4]], "horizontal")
