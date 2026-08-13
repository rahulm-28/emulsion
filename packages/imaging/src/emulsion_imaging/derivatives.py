"""The derivative pyramid, and the region round-trip built on it.

Real 4K outputs run 1.4-13.4 MB and lineage retains every version, so serving the
archival PNG to a gallery is how the storage bill and the page weight both get away from
you. Written once, on ingest:

    archival   the bytes the model returned, untouched, Cool tier
    viewer     ~2048px WebP — what the editor and diff overlays work on, Hot
    gallery    ~512px WebP — thumbnails and the session list, Hot

Only the final composite touches 4K. Everything interactive happens on the viewer
derivative, which is ~40x cheaper to move.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .align import align
from .colour import normalise
from .composite import composite
from .gutters import Rect, gutter_fraction, snap_to_gutters
from .score import CandidateScore, score_candidate

VIEWER_EDGE = 2048
GALLERY_EDGE = 512
WEBP_QUALITY = 82


@dataclass(frozen=True)
class Derivative:
    name: str
    data: bytes
    width: int
    height: int
    content_type: str


def to_array(data: bytes) -> np.ndarray:
    """Decode to RGB uint8. Alpha is dropped — gpt-image-2 has no transparency, and
    carrying a constant alpha channel through every array doubles the work for nothing."""
    with Image.open(io.BytesIO(data)) as image:
        return np.array(image.convert("RGB"), dtype=np.uint8)


def to_png(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _resized_webp(array: np.ndarray, long_edge: int) -> Derivative | None:
    height, width = array.shape[:2]
    longest = max(height, width)
    # Never upscale: a 512px source has no more detail to give a 2048px derivative.
    scale = 1.0 if longest <= long_edge else long_edge / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))

    image = Image.fromarray(array)
    if scale != 1.0:
        image = image.resize(new_size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=4)
    return Derivative(
        name="",
        data=buffer.getvalue(),
        width=image.width,
        height=image.height,
        content_type="image/webp",
    )


def build_pyramid(original: bytes) -> list[Derivative]:
    """Archival original plus viewer and gallery derivatives."""
    array = to_array(original)
    height, width = array.shape[:2]

    out = [
        Derivative(
            name="archival",
            data=original,
            width=width,
            height=height,
            content_type="image/png",
        )
    ]
    for name, edge in (("viewer", VIEWER_EDGE), ("gallery", GALLERY_EDGE)):
        derivative = _resized_webp(array, edge)
        if derivative is not None:
            out.append(
                Derivative(
                    name=name,
                    data=derivative.data,
                    width=derivative.width,
                    height=derivative.height,
                    content_type=derivative.content_type,
                )
            )
    return out


# --------------------------------------------------------------------------------------
# The region edit round-trip
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionPlan:
    """What to send to the model, and where the answer goes back."""

    crop: np.ndarray
    rect: Rect
    snapped: bool
    gutter_fraction: float

    def is_clean(self, threshold: float = 0.75) -> bool:
        """Whether the boundary sits mostly in whitespace.

        Worth surfacing before spending money: a low value predicts a visible seam,
        and the user can move the region rather than pay to discover it.
        """
        return self.gutter_fraction >= threshold


def plan_region_edit(
    parent: np.ndarray, rect: Rect, *, padding: int = 64, snap_tolerance: int = 48
) -> RegionPlan:
    """Crop the region plus context, snapping the boundary onto gutters where possible.

    The padding is context for the model — it edits better when it can see what
    surrounds the region — and it is also the ring the colour fit is measured on.
    """
    height, width = parent.shape[:2]
    padded = rect.pad(padding, width, height)
    snapped = snap_to_gutters(parent, padded, tolerance=snap_tolerance)
    if snapped.is_empty():
        snapped = padded

    return RegionPlan(
        crop=parent[snapped.top : snapped.bottom, snapped.left : snapped.right].copy(),
        rect=snapped,
        snapped=snapped.as_tuple() != padded.as_tuple(),
        gutter_fraction=gutter_fraction(parent, snapped),
    )


@dataclass(frozen=True)
class RegionResult:
    image: np.ndarray
    score: CandidateScore
    shift: tuple[int, int]
    gains: tuple[float, float, float]


def apply_region_edit(
    parent: np.ndarray,
    plan: RegionPlan,
    returned_crop: np.ndarray,
    *,
    feather: int = 6,
) -> RegionResult:
    """Align, colour-match, composite and score one returned crop.

    The full SeamEdit ordering: register first, because a colour fit on a misaligned
    ring measures the misalignment; then correct tone; then composite.
    """
    aligned, shift = align(plan.crop, returned_crop)
    corrected, (gains, _) = normalise(plan.crop, aligned)
    result = composite(parent, corrected, plan.rect, feather=feather)

    # Scored against the crop that was sent, not against the parent: outside the rect
    # the result is the parent by construction, so any measurement there reads zero
    # regardless of how bad the candidate is.
    score = score_candidate(plan.crop, corrected, result, plan.rect, shift=shift)
    return RegionResult(
        image=result,
        score=score,
        shift=shift,
        gains=(float(gains[0]), float(gains[1]), float(gains[2])),
    )


def choose_best(
    parent: np.ndarray, plan: RegionPlan, candidates: list[np.ndarray], *, feather: int = 6
) -> tuple[RegionResult, list[RegionResult]]:
    """Apply every candidate and return (winner, all results in generation order)."""
    if not candidates:
        raise ValueError("no candidates to choose from")
    results = [apply_region_edit(parent, plan, c, feather=feather) for c in candidates]
    winner = min(results, key=lambda r: r.score.total)
    return winner, results
