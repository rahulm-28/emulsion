"""Imaging primitives, with the composite invariant as the headline case.

The fixture is a synthetic flat diagram — coloured zones separated by whitespace
gutters — because that is the shape the product is for and the shape the compiler asks
the model to produce.
"""

import numpy as np
import pytest
from emulsion_imaging import (
    CompositeInvariantError,
    Rect,
    align,
    apply_region_edit,
    build_pyramid,
    change_outside,
    choose_best,
    composite,
    context_drift,
    estimate_shift,
    feather_mask,
    flat_runs,
    gutter_fraction,
    normalise,
    outside_difference,
    plan_region_edit,
    rank,
    row_flatness,
    score_candidate,
    seam_discontinuity,
    shift_image,
    to_array,
    to_png,
)
from emulsion_imaging.score import CandidateScore


def diagram(width: int = 512, height: int = 384) -> np.ndarray:
    """Four coloured zones on off-white, with 40px gutters between them.

    The background is 235 rather than 250 deliberately: at 250 a +30 or ×1.06 tone
    shift clips at 255, so the fixture would silently absorb the very drift these
    tests exist to detect.
    """
    canvas = np.full((height, width, 3), 235, dtype=np.uint8)
    zones = [
        ((60, 60, 210, 150), (120, 90, 200)),
        ((280, 60, 450, 150), (90, 170, 120)),
        ((60, 220, 210, 320), (200, 140, 80)),
        ((280, 220, 450, 320), (80, 130, 190)),
    ]
    for (x0, y0, x1, y1), colour in zones:
        canvas[y0:y1, x0:x1] = colour
    return canvas


# -- the invariant --------------------------------------------------------------------


def test_composite_leaves_outside_pixels_byte_identical():
    """The product promise. Not 'visually identical' — byte-identical."""
    parent = diagram()
    rect = Rect(280, 220, 450, 320)
    patch = np.full((rect.height, rect.width, 3), 10, dtype=np.uint8)

    result = composite(parent, patch, rect, feather=0)

    assert outside_difference(parent, result, rect) == 0
    # And prove it directly on the slices, not only via the helper.
    assert np.array_equal(parent[:220, :], result[:220, :])
    assert np.array_equal(parent[320:, :], result[320:, :])
    assert np.array_equal(parent[220:320, :280], result[220:320, :280])
    assert np.array_equal(parent[220:320, 450:], result[220:320, 450:])


def test_composite_actually_changes_the_inside():
    parent = diagram()
    rect = Rect(280, 220, 450, 320)
    patch = np.full((rect.height, rect.width, 3), 10, dtype=np.uint8)
    result = composite(parent, patch, rect, feather=0)
    assert not np.array_equal(
        parent[rect.top : rect.bottom, rect.left : rect.right],
        result[rect.top : rect.bottom, rect.left : rect.right],
    )


def test_feathering_still_holds_the_invariant():
    parent = diagram()
    rect = Rect(100, 100, 300, 250)
    patch = np.zeros((rect.height, rect.width, 3), dtype=np.uint8)
    result = composite(parent, patch, rect, feather=12)
    assert outside_difference(parent, result, rect) == 0


def test_the_invariant_is_enforced_not_merely_documented():
    parent = diagram()
    rect = Rect(10, 10, 40, 40)
    tampered = parent.copy()
    tampered[300, 300] = (0, 0, 0)
    with pytest.raises(CompositeInvariantError, match="outside"):
        from emulsion_imaging import assert_outside_unchanged

        assert_outside_unchanged(parent, tampered, rect)


def test_patch_of_the_wrong_size_is_rejected():
    parent = diagram()
    rect = Rect(0, 0, 50, 50)
    with pytest.raises(ValueError, match="rect expects"):
        composite(parent, np.zeros((10, 10, 3), dtype=np.uint8), rect)


def test_empty_rect_is_a_no_op():
    parent = diagram()
    result = composite(parent, np.zeros((0, 0, 3), np.uint8), Rect(5, 5, 5, 5))
    assert np.array_equal(parent, result)


# -- gutters --------------------------------------------------------------------------


def test_gutter_rows_are_found_between_zones():
    canvas = diagram()
    runs = flat_runs(row_flatness(canvas))
    # The band between the top zones (y<150) and the bottom zones (y>=220) is flat.
    assert any(start <= 160 and end >= 210 for start, end in runs)


def test_snapping_moves_a_boundary_into_the_gutter():
    canvas = diagram()
    # A rect whose top edge cuts through the upper zones.
    rough = Rect(270, 140, 460, 330)
    plan = plan_region_edit(canvas, rough, padding=0, snap_tolerance=60)
    assert plan.snapped
    assert plan.gutter_fraction > 0.5


def test_gutter_fraction_is_high_on_whitespace_and_low_through_content():
    canvas = diagram()
    clean = gutter_fraction(canvas, Rect(240, 170, 470, 340))
    through = gutter_fraction(canvas, Rect(100, 100, 300, 200))
    assert clean > through


def test_plan_reports_whether_the_edit_will_be_clean():
    canvas = diagram()
    plan = plan_region_edit(canvas, Rect(285, 225, 445, 315), padding=30)
    assert plan.is_clean()
    assert plan.crop.shape[:2] == (plan.rect.height, plan.rect.width)


# -- alignment ------------------------------------------------------------------------


@pytest.mark.parametrize(("dy", "dx"), [(0, 0), (3, 0), (0, -4), (5, 7), (-6, -2)])
def test_shift_is_recovered(dy, dx):
    canvas = diagram(256, 256)
    moved = shift_image(canvas, dy, dx)
    assert estimate_shift(canvas, moved) == (-dy, -dx)


def test_shift_does_not_wrap_content_around_the_edge():
    canvas = diagram(128, 128)
    moved = shift_image(canvas, 10, 0)
    # np.roll would place bottom rows at the top; edge replication must not.
    assert not np.array_equal(moved[0], canvas[-10])


def test_align_restores_a_shifted_crop():
    canvas = diagram(256, 256)
    moved = shift_image(canvas, 4, -3)
    restored, shift = align(canvas, moved)
    assert shift == (-4, 3)
    assert np.abs(restored.astype(int) - canvas.astype(int)).mean() < 6


# -- colour ---------------------------------------------------------------------------


def test_tone_drift_is_corrected_from_the_border_ring():
    # The crop's ring must itself cross a zone edge, otherwise the ring is flat, gain
    # is genuinely unidentifiable, and only an offset can be fitted — a real case,
    # covered separately below. Zone 1 spans x 60-210, y 60-150; this crop puts that
    # boundary inside the outer 10px.
    canvas = diagram()[55:145, 55:205]
    drifted = np.clip(canvas.astype(np.float32) * 1.06 + 4, 0, 255).astype(np.uint8)
    corrected, (gains, _) = normalise(canvas, drifted, border=10)

    before = np.abs(canvas.astype(int) - drifted.astype(int)).mean()
    after = np.abs(canvas.astype(int) - corrected.astype(int)).mean()
    assert after < before / 2
    assert np.all(gains < 1.0)  # the inverse of the gain that was applied


def test_a_flat_ring_yields_offset_only():
    """Common on diagrams: the padding is solid background, so gain is not
    identifiable and only the offset can honestly be fitted."""
    flat = np.full((80, 80, 3), 200, dtype=np.uint8)
    shifted = np.full((80, 80, 3), 212, dtype=np.uint8)
    _, (gains, offsets) = normalise(flat, shifted, border=8)
    assert np.allclose(gains, 1.0)
    assert np.allclose(offsets, -12.0)


def test_correction_is_clamped_so_a_rewritten_context_cannot_smear():
    canvas = diagram(120, 120)
    wild = np.clip(canvas.astype(np.float32) * 4.0, 0, 255).astype(np.uint8)
    _, (gains, offsets) = normalise(canvas, wild, border=8)
    assert np.all(gains >= 0.8)
    # Regression: the flat-ring branch used to skip this clamp entirely, which is
    # exactly the branch a diagram takes.
    assert np.all(np.abs(offsets) <= 40.0)


# -- scoring --------------------------------------------------------------------------


def test_seam_is_near_zero_when_the_boundary_sits_in_a_gutter():
    canvas = diagram()
    assert seam_discontinuity(canvas, Rect(240, 170, 470, 340)) < 2.0


def test_seam_is_large_across_a_hard_edge():
    canvas = diagram()
    spoiled = canvas.copy()
    rect = Rect(240, 170, 470, 340)
    spoiled[rect.top : rect.bottom, rect.left : rect.right] = 0
    assert seam_discontinuity(spoiled, rect) > 20.0


def test_change_outside_measures_only_outside_the_region():
    """The full-image (mask) path signal."""
    canvas = diagram()
    rect = Rect(280, 220, 450, 320)
    inside_only = canvas.copy()
    inside_only[rect.top : rect.bottom, rect.left : rect.right] = 0
    assert change_outside(canvas, inside_only, rect) == 0.0

    everywhere = np.clip(canvas.astype(int) - 30, 0, 255).astype(np.uint8)
    assert change_outside(canvas, everywhere, rect) > 20.0


def test_context_drift_catches_a_model_rewriting_its_padding():
    """The crop path signal. `change_outside` reads zero here by construction, which
    is why the two are separate functions."""
    crop = diagram(200, 160)
    faithful = crop.copy()
    faithful[60:100, 60:140] = (10, 10, 10)  # edits the middle only
    assert context_drift(crop, faithful, border=12) == 0.0

    overreaching = np.clip(crop.astype(int) - 25, 0, 255).astype(np.uint8)
    assert context_drift(crop, overreaching, border=12) > 20.0


def test_ranking_prefers_the_lower_total_and_is_stable():
    scores = [
        CandidateScore(1, 1, 1, 3.0),
        CandidateScore(0, 0, 0, 1.0),
        CandidateScore(1, 1, 1, 3.0),
    ]
    assert rank(scores) == [1, 0, 2]


def test_scoring_separates_a_faithful_candidate_from_an_overreaching_one():
    parent = diagram()
    plan = plan_region_edit(parent, Rect(285, 225, 445, 315), padding=30)
    rect = plan.rect

    faithful = plan.crop.copy()
    faithful[40:-40, 40:-40] = (200, 70, 70)
    overreaching = np.clip(faithful.astype(int) - 25, 0, 255).astype(np.uint8)

    good = score_candidate(plan.crop, faithful, parent, rect)
    bad = score_candidate(plan.crop, overreaching, parent, rect, shift=(9, 6))
    assert good.total < bad.total
    assert good.drift == 0.0
    assert bad.drift > 0.0
    assert bad.misalignment > 0.0


# -- the whole round trip -------------------------------------------------------------


def test_region_edit_round_trip_holds_the_invariant():
    parent = diagram()
    plan = plan_region_edit(parent, Rect(285, 225, 445, 315), padding=30)

    # A returned crop that is shifted, tone-drifted, and has the zone recoloured —
    # all three of the failure modes the pipeline exists to undo.
    edited = plan.crop.copy()
    edited[30:-30, 30:-30] = (220, 60, 60)
    edited = shift_image(edited, 3, -2)
    edited = np.clip(edited.astype(np.float32) * 1.05 + 5, 0, 255).astype(np.uint8)

    result = apply_region_edit(parent, plan, edited)

    assert outside_difference(parent, result.image, plan.rect) == 0
    assert result.shift != (0, 0)
    assert result.score.total >= 0
    # The edit landed.
    inside = result.image[plan.rect.top : plan.rect.bottom, plan.rect.left : plan.rect.right]
    assert not np.array_equal(inside, plan.crop)


def test_choose_best_picks_the_cleanest_candidate():
    parent = diagram()
    plan = plan_region_edit(parent, Rect(285, 225, 445, 315), padding=30)

    faithful = plan.crop.copy()
    faithful[35:-35, 35:-35] = (210, 70, 70)

    sloppy = faithful.copy()
    sloppy = np.clip(sloppy.astype(np.float32) * 1.4 + 30, 0, 255).astype(np.uint8)
    sloppy = shift_image(sloppy, 11, 9)

    winner, results = choose_best(parent, plan, [sloppy, faithful])
    assert winner is results[1]
    assert results[1].score.total < results[0].score.total
    for result in results:
        assert outside_difference(parent, result.image, plan.rect) == 0


def test_choose_best_rejects_an_empty_candidate_list():
    parent = diagram()
    plan = plan_region_edit(parent, Rect(10, 10, 60, 60))
    with pytest.raises(ValueError, match="no candidates"):
        choose_best(parent, plan, [])


# -- derivatives ----------------------------------------------------------------------


def test_pyramid_produces_archival_viewer_and_gallery():
    original = to_png(diagram(3000, 2000))
    pyramid = build_pyramid(original)

    names = [d.name for d in pyramid]
    assert names == ["archival", "viewer", "gallery"]

    archival, viewer, gallery = pyramid
    assert archival.data == original  # untouched bytes
    assert max(viewer.width, viewer.height) == 2048
    assert max(gallery.width, gallery.height) == 512
    assert viewer.content_type == "image/webp"


def test_derivatives_are_dramatically_smaller_than_the_archival_png():
    original = to_png(diagram(3000, 2000))
    archival, viewer, gallery = build_pyramid(original)
    assert len(viewer.data) < len(archival.data)
    assert len(gallery.data) < len(viewer.data)


def test_small_images_are_not_upscaled():
    original = to_png(diagram(300, 200))
    _, viewer, _ = build_pyramid(original)
    assert (viewer.width, viewer.height) == (300, 200)


def test_png_round_trip_is_lossless():
    canvas = diagram(64, 48)
    assert np.array_equal(to_array(to_png(canvas)), canvas)


def test_feather_mask_is_one_in_the_middle_and_zero_at_the_edge():
    mask = feather_mask((40, 40), feather=8)
    assert mask[20, 20] == pytest.approx(1.0)
    assert mask[0, 20] < 0.2
    assert mask[20, 0] < 0.2
