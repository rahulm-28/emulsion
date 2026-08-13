"""Re-align an edited crop back onto the coordinates it was cut from.

`gpt-image-*` returns an edited crop shifted by a few pixels. Compositing without
correcting that shift doubles every line at the seam, which is more visible than the
edit itself.

ponytail: translation only, via phase correlation. The crop is requested at the same
size it was sent, so scale is ~1 and rotation is ~0 in practice; solving for translation
alone is a numpy FFT and no dependency. If a provider ever returns a rotated or rescaled
crop, this silently under-corrects — the upgrade is cv2.estimateAffinePartial2D plus
warpAffine behind this same function signature, and `residual()` is the check that tells
you it is needed.
"""

from __future__ import annotations

import numpy as np


def _luma(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.astype(np.float32)
    return image[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _hann(shape: tuple[int, int]) -> np.ndarray:
    """Window the patches before the FFT; without it the image borders dominate the
    correlation and the estimate locks onto the frame rather than the content."""
    rows = np.hanning(shape[0])[:, None] if shape[0] > 1 else np.ones((1, 1))
    cols = np.hanning(shape[1])[None, :] if shape[1] > 1 else np.ones((1, 1))
    return (rows * cols).astype(np.float32)


def estimate_shift(reference: np.ndarray, moved: np.ndarray) -> tuple[int, int]:
    """Integer (dy, dx) that best maps `moved` back onto `reference`."""
    if reference.shape[:2] != moved.shape[:2]:
        raise ValueError(
            f"shape mismatch: reference {reference.shape[:2]} vs moved {moved.shape[:2]}"
        )
    height, width = reference.shape[:2]
    if height < 2 or width < 2:
        return (0, 0)

    window = _hann((height, width))
    a = _luma(reference) * window
    b = _luma(moved) * window
    a -= a.mean()
    b -= b.mean()

    spectrum = np.fft.rfft2(a) * np.conj(np.fft.rfft2(b))
    magnitude = np.abs(spectrum)
    # Cross-power spectrum: normalising discards magnitude so the peak depends on
    # alignment rather than on which patch is brighter.
    with np.errstate(invalid="ignore", divide="ignore"):
        spectrum = np.where(magnitude > 1e-8, spectrum / magnitude, 0)
    correlation = np.fft.irfft2(spectrum, s=(height, width))

    peak = int(np.argmax(correlation))
    dy, dx = divmod(peak, width)
    if dy > height // 2:
        dy -= height
    if dx > width // 2:
        dx -= width
    return (int(dy), int(dx))


def shift_image(image: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Translate by whole pixels, holding edge values rather than wrapping.

    np.roll would wrap content from one edge to the other, which puts a strip of the
    opposite side of the picture into the seam.
    """
    if dy == 0 and dx == 0:
        return image.copy()
    out = np.empty_like(image)
    height, width = image.shape[:2]

    src_y0, dst_y0 = (0, dy) if dy >= 0 else (-dy, 0)
    src_x0, dst_x0 = (0, dx) if dx >= 0 else (-dx, 0)
    copy_h = height - abs(dy)
    copy_w = width - abs(dx)

    if copy_h <= 0 or copy_w <= 0:
        out[...] = image
        return out

    # Start from edge-replicated content so the vacated strip is filled plausibly.
    out[...] = image
    out[dst_y0 : dst_y0 + copy_h, dst_x0 : dst_x0 + copy_w] = image[
        src_y0 : src_y0 + copy_h, src_x0 : src_x0 + copy_w
    ]
    return out


def align(reference: np.ndarray, moved: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    """Return (`moved` shifted onto `reference`, the shift applied)."""
    dy, dx = estimate_shift(reference, moved)
    return shift_image(moved, dy, dx), (dy, dx)


def residual(reference: np.ndarray, candidate: np.ndarray, border: int = 8) -> float:
    """Mean absolute difference on the border ring only, in 0-255 units.

    The ring is the part that should not have changed, so a high residual after
    alignment means the alignment failed — or the model rewrote the context it was
    given, which is the same problem from the user's side.
    """
    if border <= 0:
        return float(np.abs(_luma(reference) - _luma(candidate)).mean())
    ring_ref = _border_ring(_luma(reference), border)
    ring_cand = _border_ring(_luma(candidate), border)
    if ring_ref.size == 0:
        return 0.0
    return float(np.abs(ring_ref - ring_cand).mean())


def _border_ring(plane: np.ndarray, border: int) -> np.ndarray:
    height, width = plane.shape[:2]
    if height <= 2 * border or width <= 2 * border:
        return plane.ravel()
    mask = np.ones((height, width), dtype=bool)
    mask[border : height - border, border : width - border] = False
    return plane[mask]
