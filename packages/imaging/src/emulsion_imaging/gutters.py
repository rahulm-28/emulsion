"""Find the whitespace between zones, and snap crop boundaries onto it.

This is the reason a diagram editor is viable where a photo editor would not be.

SeamEdit's hardest stage is blending a regenerated patch back into its surroundings.
On a photograph every boundary cuts through texture, so the seam must be reconstructed.
A flat diagram has gutters — low-variance bands of background between zones — and if the
crop boundary lands inside one, there is nothing to blend: both sides are the same flat
colour. The seam problem largely evaporates.

The compiler asks the model for those gutters (`STRUCTURAL_RULES`), and this module
finds them again on the way back. That loop is the product.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# A band counts as a gutter when its per-row variance is below this, in 0-255 units.
# Chosen well above sensor/compression noise on a flat fill but far below the variance
# of a row that clips any box edge or text.
DEFAULT_FLATNESS = 4.0


@dataclass(frozen=True)
class Rect:
    """Half-open pixel rectangle: left <= x < right, top <= y < bottom."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def clamp(self, width: int, height: int) -> Rect:
        return Rect(
            left=max(0, min(self.left, width)),
            top=max(0, min(self.top, height)),
            right=max(0, min(self.right, width)),
            bottom=max(0, min(self.bottom, height)),
        )

    def pad(self, pixels: int, width: int, height: int) -> Rect:
        return Rect(
            self.left - pixels, self.top - pixels, self.right + pixels, self.bottom + pixels
        ).clamp(width, height)

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


def _luma(image: np.ndarray) -> np.ndarray:
    """Rec. 601 luma. Variance on luma rather than per-channel keeps a coloured but
    flat fill (a solid blue band) correctly classified as a gutter."""
    if image.ndim == 2:
        return image.astype(np.float32)
    rgb = image[..., :3].astype(np.float32)
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def row_flatness(image: np.ndarray) -> np.ndarray:
    """Per-row variance of luma. Low means the row crosses no content."""
    return _luma(image).var(axis=1)


def column_flatness(image: np.ndarray) -> np.ndarray:
    return _luma(image).var(axis=0)


def flat_runs(flatness: np.ndarray, threshold: float = DEFAULT_FLATNESS) -> list[tuple[int, int]]:
    """Contiguous [start, end) spans whose variance stays under `threshold`."""
    flat = flatness < threshold
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(flat):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flat)))
    return runs


def _snap_edge(edge: int, runs: list[tuple[int, int]], limit: int, *, tolerance: int) -> int:
    """Move `edge` to the centre of the nearest gutter, if one is close enough."""
    best = edge
    best_distance = tolerance + 1
    for start, end in runs:
        centre = (start + end) // 2
        distance = abs(centre - edge)
        if distance < best_distance:
            best, best_distance = centre, distance
    return max(0, min(best, limit))


def snap_to_gutters(
    image: np.ndarray,
    rect: Rect,
    *,
    tolerance: int = 48,
    threshold: float = DEFAULT_FLATNESS,
) -> Rect:
    """Nudge each edge of `rect` onto the nearest gutter within `tolerance` pixels.

    Returns the rect unchanged where no gutter is near — a crop through content is
    still correct, it just makes the compositor work harder.
    """
    height, width = image.shape[:2]
    rows = flat_runs(row_flatness(image), threshold)
    cols = flat_runs(column_flatness(image), threshold)

    return Rect(
        left=_snap_edge(rect.left, cols, width, tolerance=tolerance),
        top=_snap_edge(rect.top, rows, height, tolerance=tolerance),
        right=_snap_edge(rect.right, cols, width, tolerance=tolerance),
        bottom=_snap_edge(rect.bottom, rows, height, tolerance=tolerance),
    ).clamp(width, height)


def expand_to_legal(
    rect: Rect,
    image_width: int,
    image_height: int,
    *,
    multiple_of: int = 16,
    min_pixels: int = 655_360,
    max_pixels: int = 8_294_400,
    max_long_edge: int = 3840,
    aspect: tuple[float, float] = (0.33, 3.0),
) -> Rect | None:
    """Grow `rect` until the provider will accept it as a standalone image.

    Providers impose size rules on every call, and a crop is a call. The alternative —
    resampling the crop up to a legal size and back down — throws away detail on the
    way out and adds ringing on the way in, on exactly the fine text a diagram lives
    or dies by. Growing the rect keeps every pixel native.

    Returns None when the source image is simply too small to yield a legal crop; the
    caller should fall back to a whole-image edit and say so. Limits are passed in
    rather than imported so this package stays free of the provider layer.
    """
    if image_width <= 0 or image_height <= 0:
        return None

    def _round_up(value: int) -> int:
        return ((value + multiple_of - 1) // multiple_of) * multiple_of

    def _round_down(value: int) -> int:
        return (value // multiple_of) * multiple_of

    max_w = min(_round_down(image_width), max_long_edge)
    max_h = min(_round_down(image_height), max_long_edge)
    if max_w <= 0 or max_h <= 0 or max_w * max_h < min_pixels:
        return None

    width = min(max(_round_up(rect.width), multiple_of), max_w)
    height = min(max(_round_up(rect.height), multiple_of), max_h)

    # Grow the shorter side first: it keeps the crop closer to square, which is the
    # cheapest way to satisfy both the pixel floor and the aspect band at once.
    lo, hi = aspect
    for _ in range(256):
        ratio = width / height
        if ratio > hi and height < max_h:
            height = min(_round_up(height + multiple_of), max_h)
            continue
        if ratio < lo and width < max_w:
            width = min(_round_up(width + multiple_of), max_w)
            continue
        if width * height < min_pixels:
            if height <= width and height < max_h:
                height = min(height + multiple_of, max_h)
            elif width < max_w:
                width = min(width + multiple_of, max_w)
            else:
                break
            continue
        break

    if width * height < min_pixels or width * height > max_pixels:
        return None
    if not lo <= width / height <= hi:
        return None

    # Keep the requested region centred in the grown box, then slide it inside bounds.
    centre_x = (rect.left + rect.right) // 2
    centre_y = (rect.top + rect.bottom) // 2
    left = centre_x - width // 2
    top = centre_y - height // 2
    left = max(0, min(left, image_width - width))
    top = max(0, min(top, image_height - height))

    return Rect(left, top, left + width, top + height)


def gutter_fraction(image: np.ndarray, rect: Rect, threshold: float = DEFAULT_FLATNESS) -> float:
    """How much of the rect's border sits on flat pixels, 0..1.

    A high value means the crop boundary is mostly in whitespace, which is the
    condition under which compositing is seam-free. Worth surfacing to the user: it
    predicts whether a region edit will be clean before any money is spent.
    """
    if rect.is_empty():
        return 0.0
    height, width = image.shape[:2]
    rect = rect.clamp(width, height)
    luma = _luma(image)

    edges = []
    if rect.top < rect.bottom:
        edges.append(luma[rect.top, rect.left : rect.right])
        edges.append(luma[rect.bottom - 1, rect.left : rect.right])
    if rect.left < rect.right:
        edges.append(luma[rect.top : rect.bottom, rect.left])
        edges.append(luma[rect.top : rect.bottom, rect.right - 1])

    flat_pixels = 0
    total = 0
    for edge in edges:
        if edge.size < 2:
            continue
        # Local flatness: a border pixel counts as gutter when its neighbourhood along
        # the edge barely changes.
        deltas = np.abs(np.diff(edge))
        flat_pixels += int((deltas < threshold).sum())
        total += deltas.size
    return flat_pixels / total if total else 0.0
