"""Size rules, checked against the real gpt-image-2 manifest."""

import pytest
from emulsion_providers import SIZE_PRESETS, load_manifest, resolve_size, validate_size

PIXELS = load_manifest("gpt-image-2").pixels


@pytest.mark.parametrize("preset", sorted(SIZE_PRESETS))
def test_every_preset_is_legal(preset):
    # A preset that violates the manifest is a 400 the user cannot avoid.
    assert resolve_size(preset, PIXELS) == SIZE_PRESETS[preset]


def test_raw_wxh_is_accepted():
    assert resolve_size("2048x1152", PIXELS) == (2048, 1152)


@pytest.mark.parametrize("spec", ["", "big", "1024", "1024x", "axb", "1024x1024x1024"])
def test_unparseable_specs_are_rejected(spec):
    with pytest.raises(ValueError, match="Invalid size"):
        resolve_size(spec, PIXELS)


@pytest.mark.parametrize(("w", "h"), [(1020, 640), (1024, 644)])
def test_edges_must_be_multiples_of_16(w, h):
    with pytest.raises(ValueError, match="multiple of 16"):
        validate_size(w, h, PIXELS)


def test_long_edge_ceiling():
    with pytest.raises(ValueError, match="exceeds max 3840"):
        validate_size(4096, 2160, PIXELS)


def test_below_minimum_pixel_count():
    with pytest.raises(ValueError, match="below min"):
        validate_size(512, 512, PIXELS)


def test_above_maximum_pixel_count():
    with pytest.raises(ValueError, match="exceeds max"):
        validate_size(3840, 3840, PIXELS)


@pytest.mark.parametrize(("w", "h"), [(3840, 1024), (1024, 3840)])
def test_aspect_ratio_is_bounded_in_both_orientations(w, h):
    with pytest.raises(ValueError, match="aspect ratio"):
        validate_size(w, h, PIXELS)


def test_smallest_legal_size_is_accepted():
    # 1024x640 is exactly the 655,360-pixel floor — the size probes and, probably,
    # M2's candidate ranking will use.
    validate_size(1024, 640, PIXELS)


def test_non_positive_dimensions():
    with pytest.raises(ValueError, match="must be positive"):
        validate_size(0, 640, PIXELS)
