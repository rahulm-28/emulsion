"""Transparency, format conversion and upscale."""

import io

import numpy as np
import pytest
from emulsion_imaging import (
    background_mask,
    background_spread,
    encode,
    export,
    has_flat_background,
    make_transparent,
    to_png,
    upscale,
)
from PIL import Image


def diagram(width: int = 200, height: int = 160) -> np.ndarray:
    """A coloured box and a white box, both on a white background.

    The white inner box is the trap: a plain colour threshold would knock it out too.
    """
    canvas = np.full((height, width, 3), 250, dtype=np.uint8)
    canvas[30:70, 30:90] = (90, 120, 200)
    # An outlined box whose fill is the same colour as the background. Only the border
    # can reach the outside, so this interior must survive.
    canvas[94:131, 29:91] = (40, 40, 40)
    canvas[95:130, 30:90] = 250
    return canvas


def test_border_connected_background_is_knocked_out():
    rgba = make_transparent(diagram())
    assert rgba.shape[2] == 4
    assert rgba[0, 0, 3] == 0  # corner is background
    assert rgba[50, 60, 3] == 255  # inside the coloured box


def test_an_enclosed_region_of_the_same_colour_survives():
    """Connectivity, not colour. A white box inside the diagram must stay opaque."""
    mask = background_mask(diagram())
    assert mask[0, 0]  # border background reached
    assert not mask[110, 60]  # enclosed white box not reached


def test_a_looser_tolerance_never_removes_less():
    canvas = diagram()
    canvas[0:40, 0:40] = 238  # a slightly off-white corner wash
    tight = background_mask(canvas, tolerance=2.0).sum()
    loose = background_mask(canvas, tolerance=25.0).sum()
    assert loose >= tight


def test_png_export_keeps_alpha():
    result = export(to_png(diagram()), fmt="png", transparent=True)
    assert result.has_alpha
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.mode == "RGBA"


def test_jpeg_export_composites_alpha_onto_white_rather_than_black():
    """Dropping the alpha channel turns transparent pixels black, which looks like a
    bug to everyone who sees it."""
    result = export(to_png(diagram()), fmt="jpeg", transparent=True)
    assert not result.has_alpha
    with Image.open(io.BytesIO(result.data)) as image:
        corner = np.array(image.convert("RGB"))[0, 0]
    assert corner.min() > 200


def test_webp_export_round_trips():
    result = export(to_png(diagram()), fmt="webp")
    assert result.content_type == "image/webp"
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == "WEBP"


def test_unsupported_format_is_rejected():
    with pytest.raises(ValueError, match="unsupported format"):
        encode(diagram(), "tiff")


def test_upscale_changes_size_and_keeps_dtype():
    bigger = upscale(diagram(100, 80), 2.0)
    assert bigger.shape[:2] == (160, 200)
    assert bigger.dtype == np.uint8


def test_upscale_rejects_a_non_positive_factor():
    with pytest.raises(ValueError, match="must be positive"):
        upscale(diagram(20, 20), 0)


def test_export_scales_and_converts_together():
    result = export(to_png(diagram(100, 80)), fmt="webp", scale=2.0)
    assert (result.width, result.height) == (200, 160)


def test_transparency_runs_before_scaling():
    """Scaling first would interpolate background pixels away from their colour and
    leave the flood fill nothing clean to match."""
    result = export(to_png(diagram()), fmt="png", transparent=True, scale=2.0)
    with Image.open(io.BytesIO(result.data)) as image:
        assert np.array(image)[0, 0, 3] == 0


# -- the guard that stops transparency running on the wrong kind of image --------------


def gradient(width: int = 120, height: int = 120) -> np.ndarray:
    """A vertical gradient — no single background colour anywhere in it."""
    ramp = np.linspace(40, 240, height, dtype=np.uint8)
    return np.repeat(np.repeat(ramp[:, None], width, axis=1)[..., None], 3, axis=2)


def test_a_flat_diagram_is_recognised_as_flat():
    assert has_flat_background(diagram())
    assert background_spread(diagram()) < 5


def test_a_gradient_is_not_treated_as_having_a_background():
    """Median-of-corners on a gradient lands mid-image, so the flood fill would eat the
    subject and leave the edges. Caught by real data, not by imagination."""
    assert not has_flat_background(gradient())
    assert background_spread(gradient()) > 24


def test_transparency_is_skipped_and_reported_on_a_gradient():
    result = export(to_png(gradient()), fmt="png", transparent=True)
    assert result.background_uniform is False
    assert result.has_alpha is False  # untouched rather than wrongly masked


def test_transparency_still_applies_to_a_flat_diagram():
    result = export(to_png(diagram()), fmt="png", transparent=True)
    assert result.background_uniform is True
    assert result.has_alpha is True
