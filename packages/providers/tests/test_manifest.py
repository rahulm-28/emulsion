"""The manifest must keep saying what the deployment actually did.

Every number asserted here came from a live probe on 2026-08-12 (see the YAML's
provenance comments). If someone 'tidies' a value back to what the documentation
claims, these fail.
"""

import pytest
from emulsion_providers import MaskSupport, available_models, cost_usd, load_manifest

# (label, input_tokens, output_tokens, expected_usd) — real usage blocks from the probe run.
COST_SAMPLES = [
    ("1024x640/low", 19, 107, 0.004432),
    ("2048x1152/medium", 16, 1413, 0.056648),
    ("3840x2160/high", 27, 13342, 0.533896),
]


def test_gpt_image_2_is_available():
    assert "gpt-image-2" in available_models()


def test_unknown_model_names_the_alternatives():
    with pytest.raises(KeyError, match="gpt-image-2"):
        load_manifest("no-such-model")


def test_mask_is_soft_not_hard():
    # 93.5% of pixels outside the mask still moved. M5's crop-composite exists because
    # of this; flipping it to HARD would quietly authorise trusting the mask.
    assert load_manifest("gpt-image-2").mask_support is MaskSupport.SOFT


def test_edits_regenerate_the_whole_image():
    assert load_manifest("gpt-image-2").edit_full_regen is True


def test_input_fidelity_is_declared_unsupported():
    assert "input_fidelity" in load_manifest("gpt-image-2").unsupported_params


def test_rate_limit_is_a_bucket_not_two_per_minute():
    rl = load_manifest("gpt-image-2").rate_limit
    assert (rl.requests, rl.window_s) == (2, 11)
    assert rl.approx_rpm == pytest.approx(10.9, abs=0.1)


def test_n_per_request_allows_batching_candidates():
    # M2 ranks K candidates. n=2 came back as 2 images in one request/rate-limit slot.
    assert load_manifest("gpt-image-2").n_per_request >= 2


@pytest.mark.parametrize(("label", "tokens_in", "tokens_out", "expected"), COST_SAMPLES)
def test_cost_matches_measured_usage(label, tokens_in, tokens_out, expected):
    m = load_manifest("gpt-image-2")
    assert cost_usd(m, tokens_in, tokens_out) == pytest.approx(expected, rel=1e-6)


def test_4k_is_two_orders_of_magnitude_dearer_than_the_smallest_size():
    # Tokens scale ~125x from 1024x640 to 4K while pixels scale only ~12.7x. This is the
    # fact that decides whether M2 can afford to rank K candidates at full resolution.
    m = load_manifest("gpt-image-2")
    cheapest = cost_usd(m, 19, 107)
    dearest = cost_usd(m, 27, 13342)
    assert dearest / cheapest > 100
