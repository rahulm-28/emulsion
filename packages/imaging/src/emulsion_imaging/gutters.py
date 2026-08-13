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
