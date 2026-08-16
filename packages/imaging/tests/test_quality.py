"""Reference-free diagram scoring — the judgement a plain generation has no basis for."""

import numpy as np
from emulsion_imaging import (
    background_score,
    contrast_score,
    gutter_score,
    ink_fraction,
    ink_score,
    rank_diagrams,
    score_diagram,
    separator_count,
)


def four_zones(gap: int = 24) -> np.ndarray:
    """A flat diagram: four dark zones with whitespace channels between them."""
    image = np.full((256, 256, 3), 250, dtype=np.uint8)
    size = (256 - gap * 3) // 2
    for top in (gap, gap * 2 + size):
        for left in (gap, gap * 2 + size):
            image[top : top + size, left : left + size] = 40
    return image


def test_a_diagram_beats_noise():
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (256, 256, 3), dtype=np.uint8)
    assert score_diagram(four_zones()).total > score_diagram(noise).total


def test_a_diagram_beats_an_empty_frame():
    blank = np.full((256, 256, 3), 250, dtype=np.uint8)
    assert score_diagram(four_zones()).total > score_diagram(blank).total


def test_outer_margins_are_not_gutters():
    """A blank frame is all flat rows, but has no separator *between* anything."""
    blank = np.full((256, 256, 3), 250, dtype=np.uint8)
    assert separator_count(blank) == 0
    assert gutter_score(blank) == 0.0


def test_zones_produce_interior_separators():
    assert separator_count(four_zones()) >= 2


def test_ink_penalises_both_extremes():
    """Empty and wall-to-wall are both failures, and neither may score 1.0."""
    blank = np.full((256, 256, 3), 250, dtype=np.uint8)
    solid = np.zeros((256, 256, 3), dtype=np.uint8)
    solid[0, 0] = 255  # one off pixel, so the modal background is still detectable
    assert ink_score(blank) < 1.0
    assert ink_score(solid) < 1.0
    assert ink_score(four_zones()) > ink_score(blank)


def test_ink_does_not_collapse_to_zero_for_dense_diagrams():
    """Regression: scaling the high side by `low` zeroed every realistic diagram.

    When that happens the ink term is constant across candidates, and ranking quietly
    reduces to whichever other term still varies.
    """
    dense = np.full((256, 256, 3), 250, dtype=np.uint8)
    dense[20:236, 20:236] = 40
    assert ink_fraction(dense) > 0.45
    assert ink_score(dense) > 0.3


def test_contrast_prefers_a_crisp_image():
    crisp = four_zones()
    washed = np.full((256, 256, 3), 250, dtype=np.uint8)
    washed[24:120, 24:120] = 220
    assert contrast_score(crisp) > contrast_score(washed)


def test_background_prefers_a_flat_border():
    rng = np.random.default_rng(1)
    noisy = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    assert background_score(four_zones()) > background_score(noisy)


def test_ranking_is_best_first_and_stable():
    a = score_diagram(four_zones())
    b = score_diagram(np.full((256, 256, 3), 250, dtype=np.uint8))
    assert rank_diagrams([b, a]) == [1, 0]
    # Equal scores keep generation order, so a rerun does not reshuffle for no reason.
    assert rank_diagrams([a, a, a]) == [0, 1, 2]


def test_greyscale_input_is_accepted():
    """Derivatives and masks are single channel; scoring must not assume RGB."""
    grey = np.full((128, 128), 250, dtype=np.uint8)
    grey[20:50, 20:50] = 30
    assert 0.0 <= score_diagram(grey).total <= 1.0
