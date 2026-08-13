"""Match an edited crop's tone to the parent it will be pasted into.

The model returns a crop that is close but not identical in tone — a percent or two of
gain and a small offset, enough that a pasted patch reads as a rectangle even when the
content is right.

The correction is fitted on the **border ring only**: that ring is context the model was
given and was not asked to change, so any difference across it is the model's tone drift
rather than the edit. Fitting on the whole patch would drag the correction toward the
edit itself and undo the thing the user asked for.
"""

from __future__ import annotations

import numpy as np

# Corrections beyond this are not tone drift — they mean the model rewrote the context,
# and applying a large gain would smear that error across the whole patch.
MAX_GAIN = 1.25
MIN_GAIN = 0.8
MAX_OFFSET = 40.0


def _border_mask(shape: tuple[int, int], border: int) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    if height <= 2 * border or width <= 2 * border:
        mask[...] = True
        return mask
    mask[...] = True
    mask[border : height - border, border : width - border] = False
    return mask


def fit_gain_offset(
    reference: np.ndarray, candidate: np.ndarray, border: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel (gain, offset) mapping `candidate` onto `reference` on the ring.

    Least squares per channel: reference ≈ gain * candidate + offset.
    """
    if reference.shape != candidate.shape:
        raise ValueError(f"shape mismatch: {reference.shape} vs {candidate.shape}")

    ref = reference[..., :3].astype(np.float64)
    cand = candidate[..., :3].astype(np.float64)
    mask = _border_mask(ref.shape[:2], border)

    gains = np.ones(3, dtype=np.float64)
    offsets = np.zeros(3, dtype=np.float64)

    for channel in range(3):
        x = cand[..., channel][mask]
        y = ref[..., channel][mask]
        if x.size < 8:
            continue
        variance = x.var()
        if variance < 1e-6:
            # A flat ring carries no gain information — only the offset is identifiable.
            # Clamped like the fitted branch: a flat ring is the common case on a
            # diagram, so skipping the limit here would mean the guard almost never
            # applies where it matters most.
            offsets[channel] = float(np.clip(y.mean() - x.mean(), -MAX_OFFSET, MAX_OFFSET))
            continue
        gain = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
        gain = float(np.clip(gain, MIN_GAIN, MAX_GAIN))
        offset = float(y.mean() - gain * x.mean())
        gains[channel] = gain
        offsets[channel] = float(np.clip(offset, -MAX_OFFSET, MAX_OFFSET))

    return gains, offsets


def apply_gain_offset(image: np.ndarray, gains: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    """Apply a per-channel correction, preserving dtype and any alpha channel."""
    out = image.astype(np.float64).copy()
    for channel in range(min(3, out.shape[-1])):
        out[..., channel] = out[..., channel] * gains[channel] + offsets[channel]
    return np.clip(out, 0, 255).astype(image.dtype)


def normalise(
    reference: np.ndarray, candidate: np.ndarray, border: int = 8
) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
    """Colour-match `candidate` to `reference`. Returns (corrected, (gains, offsets))."""
    gains, offsets = fit_gain_offset(reference, candidate, border)
    return apply_gain_offset(candidate, gains, offsets), (gains, offsets)
