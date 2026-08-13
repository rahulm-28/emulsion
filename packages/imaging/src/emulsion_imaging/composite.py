"""Paste an edited patch into a copy of the parent, and prove nothing else moved.

This module carries the product promise. For any region edit, pixels outside the padded
rect are byte-identical to the parent — not "visually identical", not "close enough".
That is asserted here on every composite, and there is a test for it. It is not a
comment.

The guarantee is structural rather than clever: the output starts as a copy of the
parent and only the slice inside the rect is ever written. It is cheap to hold, which is
exactly why it should be held.
"""

from __future__ import annotations

import numpy as np

from .gutters import Rect


class CompositeInvariantError(AssertionError):
    """Raised when a composite would alter pixels outside the edited region."""


def feather_mask(shape: tuple[int, int], feather: int) -> np.ndarray:
    """A 0..1 alpha ramp, 1 in the interior and falling to 0 at the rect edge.

    Feathering hides the last pixel of tone mismatch. When the crop was snapped onto a
    gutter there is nothing to hide, so a small feather costs nothing and rescues the
    case where snapping found no gutter.
    """
    height, width = shape
    alpha = np.ones((height, width), dtype=np.float32)
    if feather <= 0:
        return alpha

    ramp_h = min(feather, height // 2)
    ramp_w = min(feather, width // 2)

    if ramp_h > 0:
        ramp = np.linspace(0.0, 1.0, ramp_h + 2, dtype=np.float32)[1:-1]
        alpha[:ramp_h, :] *= ramp[:, None]
        alpha[height - ramp_h :, :] *= ramp[::-1][:, None]
    if ramp_w > 0:
        ramp = np.linspace(0.0, 1.0, ramp_w + 2, dtype=np.float32)[1:-1]
        alpha[:, :ramp_w] *= ramp[None, :]
        alpha[:, width - ramp_w :] *= ramp[::-1][None, :]
    return alpha


def composite(
    parent: np.ndarray,
    patch: np.ndarray,
    rect: Rect,
    *,
    feather: int = 6,
    verify: bool = True,
) -> np.ndarray:
    """Composite `patch` into a copy of `parent` at `rect`.

    `verify` re-reads the result and refuses to return an image that broke the
    invariant. It is on by default because a silent violation is the one failure mode
    that would destroy trust in the whole product.
    """
    height, width = parent.shape[:2]
    rect = rect.clamp(width, height)
    if rect.is_empty():
        return parent.copy()

    expected = (rect.height, rect.width)
    if patch.shape[:2] != expected:
        raise ValueError(f"patch is {patch.shape[:2]}, rect expects {expected}")
    if patch.shape[-1] != parent.shape[-1]:
        raise ValueError(
            f"channel mismatch: parent has {parent.shape[-1]}, patch has {patch.shape[-1]}"
        )

    out = parent.copy()
    window = out[rect.top : rect.bottom, rect.left : rect.right]

    alpha = feather_mask(expected, feather)[..., None]
    blended = alpha * patch.astype(np.float32) + (1.0 - alpha) * window.astype(np.float32)
    out[rect.top : rect.bottom, rect.left : rect.right] = np.clip(blended, 0, 255).astype(
        parent.dtype
    )

    if verify:
        assert_outside_unchanged(parent, out, rect)
    return out


def outside_difference(before: np.ndarray, after: np.ndarray, rect: Rect) -> int:
    """Count of pixels outside `rect` that differ. Zero is the contract."""
    if before.shape != after.shape:
        raise ValueError(f"shape mismatch: {before.shape} vs {after.shape}")
    differing = np.any(before != after, axis=-1) if before.ndim == 3 else before != after
    differing[rect.top : rect.bottom, rect.left : rect.right] = False
    return int(differing.sum())


def assert_outside_unchanged(before: np.ndarray, after: np.ndarray, rect: Rect) -> None:
    changed = outside_difference(before, after, rect)
    if changed:
        raise CompositeInvariantError(
            f"{changed} pixel(s) outside {rect.as_tuple()} changed; the composite "
            f"invariant is the product promise and must hold exactly"
        )
