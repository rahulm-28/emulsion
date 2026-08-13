"""Rank candidate edits so the best one is chosen without a human looking at K images.

Three signals, chosen because they fail independently:

  * **seam** — luma discontinuity across the rect boundary on the finished image.
    What a viewer notices first, and what says "this was pasted".
  * **drift** — how much the model changed the *context ring* it was given but not
    asked to edit. This is the measured failure mode: on a real masked call, 93.5% of
    pixels outside the mask moved. A candidate that rewrote its own context will
    rewrite the picture.
  * **misalignment** — how far the return had to be shifted to register. A large shift
    means the model reframed rather than edited, which correlates with worse content.

Lower is better for all three, combined with explicit weights rather than a learned
model so a bad ranking can be explained and corrected by hand.

`change_outside` is kept separate: it is the right measurement for a **full-image**
edit (the mask path, where the model returns the whole picture), and meaningless on the
crop path where anything outside the crop is the parent by construction. Conflating the
two is how a scoring signal ends up reading zero forever.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .gutters import Rect

# Seam dominates because it is the visible artefact. Drift is next because it silently
# corrupts parts of the picture nobody asked to change. Misalignment is a weak prior.
WEIGHTS = {"seam": 1.0, "drift": 0.6, "misalignment": 0.15}


@dataclass(frozen=True)
class CandidateScore:
    seam: float
    drift: float
    misalignment: float
    total: float

    def explain(self) -> str:
        return (
            f"seam {self.seam:.2f} · drift {self.drift:.2f} · "
            f"shift {self.misalignment:.1f}px → {self.total:.2f}"
        )


def _luma(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.astype(np.float32)
    return image[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _ring(plane: np.ndarray, border: int) -> np.ndarray:
    height, width = plane.shape[:2]
    if border <= 0 or height <= 2 * border or width <= 2 * border:
        return plane.ravel()
    mask = np.ones((height, width), dtype=bool)
    mask[border : height - border, border : width - border] = False
    return plane[mask]


def seam_discontinuity(image: np.ndarray, rect: Rect) -> float:
    """Mean absolute luma step across the rect boundary, in 0-255 units.

    Compares the last row/column inside the rect against the first one outside. On a
    crop snapped to a gutter both are flat background and this is ~0.
    """
    height, width = image.shape[:2]
    rect = rect.clamp(width, height)
    if rect.is_empty():
        return 0.0
    plane = _luma(image)

    steps: list[np.ndarray] = []
    if rect.top - 1 >= 0:
        steps.append(
            np.abs(
                plane[rect.top, rect.left : rect.right]
                - plane[rect.top - 1, rect.left : rect.right]
            )
        )
    if rect.bottom < height:
        steps.append(
            np.abs(
                plane[rect.bottom - 1, rect.left : rect.right]
                - plane[rect.bottom, rect.left : rect.right]
            )
        )
    if rect.left - 1 >= 0:
        steps.append(
            np.abs(
                plane[rect.top : rect.bottom, rect.left]
                - plane[rect.top : rect.bottom, rect.left - 1]
            )
        )
    if rect.right < width:
        steps.append(
            np.abs(
                plane[rect.top : rect.bottom, rect.right - 1]
                - plane[rect.top : rect.bottom, rect.right]
            )
        )

    values = [s for s in steps if s.size]
    return float(np.concatenate(values).mean()) if values else 0.0


def context_drift(reference_crop: np.ndarray, candidate_crop: np.ndarray, border: int = 8) -> float:
    """Mean absolute luma change over the crop's context ring, in 0-255 units.

    The ring is padding the model was given so it could see the surroundings. It was
    not asked to change it, so anything here is the model overreaching.
    """
    if reference_crop.shape[:2] != candidate_crop.shape[:2]:
        raise ValueError(
            f"shape mismatch: {reference_crop.shape[:2]} vs {candidate_crop.shape[:2]}"
        )
    ref = _ring(_luma(reference_crop), border)
    cand = _ring(_luma(candidate_crop), border)
    if ref.size == 0:
        return 0.0
    return float(np.abs(ref - cand).mean())


def change_outside(before: np.ndarray, after: np.ndarray, rect: Rect) -> float:
    """Mean absolute luma change outside `rect`, in 0-255 units.

    For the **full-image** edit path: the model returns the whole picture and this
    measures how much of it drifted. On the crop path use `context_drift` instead —
    here the answer is zero by construction and tells you nothing.
    """
    if before.shape[:2] != after.shape[:2]:
        raise ValueError(f"shape mismatch: {before.shape[:2]} vs {after.shape[:2]}")
    height, width = before.shape[:2]
    rect = rect.clamp(width, height)

    diff = np.abs(_luma(before) - _luma(after))
    mask = np.ones((height, width), dtype=bool)
    mask[rect.top : rect.bottom, rect.left : rect.right] = False
    return float(diff[mask].mean()) if mask.any() else 0.0


def score_candidate(
    reference_crop: np.ndarray,
    candidate_crop: np.ndarray,
    composited: np.ndarray,
    rect: Rect,
    *,
    shift: tuple[int, int] = (0, 0),
    border: int = 8,
) -> CandidateScore:
    """Score one candidate on the crop-composite path.

    `reference_crop` is what was sent, `candidate_crop` is the aligned and colour-
    corrected return, `composited` is the finished full-size image.
    """
    seam = seam_discontinuity(composited, rect)
    drift = context_drift(reference_crop, candidate_crop, border=border)
    misalignment = math.hypot(shift[0], shift[1])
    total = (
        WEIGHTS["seam"] * seam + WEIGHTS["drift"] * drift + WEIGHTS["misalignment"] * misalignment
    )
    return CandidateScore(seam=seam, drift=drift, misalignment=misalignment, total=total)


def rank(scores: list[CandidateScore]) -> list[int]:
    """Indices best first. Stable, so equal scores keep generation order."""
    return sorted(range(len(scores)), key=lambda i: scores[i].total)
