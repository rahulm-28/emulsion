"""The region-edit path: crop, send, align, colour-match, composite.

Kept apart from `runner.py` because it is the one place where the imaging pipeline,
the provider layer and the manifest's size rules all meet, and because it is the path
that carries the product promise.

The ordering is SeamEdit's, and each step exists because of a measured failure:

  1. grow the rect to a legal size — a crop is a call, and calls have size rules
  2. snap onto gutters — low-variance bands mean nothing to blend at the seam
  3. send only the crop — a masked full-image call moved 93.5% of outside pixels
  4. align — the return comes back shifted
  5. colour-match on the border ring — the return comes back off-tone
  6. rank candidates — pick the cleanest without a human looking at K images
  7. composite into a copy — pixels outside the rect stay byte-identical
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from emulsion_imaging import (
    Rect,
    RegionResult,
    choose_best,
    expand_to_legal,
    plan_region_edit,
    snap_to_gutters,
    to_array,
    to_png,
)
from emulsion_providers import Manifest

log = logging.getLogger("emulsion.worker.regions")

# The synthetic blob id the crop travels under. The adapter only needs bytes; nothing
# is written to storage for it.
CROP_BLOB_ID = "__region_crop__"


class RegionTooSmall(ValueError):
    """The parent cannot yield a crop the provider would accept."""


@dataclass(frozen=True)
class RegionRequest:
    """A prepared region edit, ready to hand to an adapter."""

    crop_png: bytes
    rect: Rect
    width: int
    height: int
    gutter_fraction: float
    snapped: bool
    grew: bool

    def describe(self) -> str:
        parts = [f"region {self.width}x{self.height} at {self.rect.as_tuple()}"]
        if self.grew:
            parts.append("grown to a legal size")
        if self.snapped:
            parts.append("snapped to gutters")
        parts.append(f"{self.gutter_fraction:.0%} of the boundary is whitespace")
        return "; ".join(parts)


def prepare(parent_png: bytes, rect: Rect, manifest: Manifest, *, padding: int = 64):
    """Plan the crop for `rect`, honouring the model's size rules.

    Returns (RegionRequest, parent_array). The array is returned so the caller does not
    decode a 13 MB PNG twice.
    """
    parent = to_array(parent_png)
    height, width = parent.shape[:2]
    pixels = manifest.pixels

    def legalise(candidate: Rect) -> Rect | None:
        return expand_to_legal(
            candidate,
            width,
            height,
            multiple_of=pixels.multiple_of,
            min_pixels=pixels.min,
            max_pixels=pixels.max,
            max_long_edge=pixels.long_edge,
            aspect=pixels.aspect,
        )

    # Order matters, and getting it wrong is silent: snapping moves edges by a few
    # pixels, which knocks the size off the multiple-of-16 grid. So snap first, let the
    # gutters inform the rect, then legalise once — and build the final plan with
    # snapping disabled so nothing moves after the size is settled.
    padded = rect.pad(padding, width, height)
    snapped = snap_to_gutters(parent, padded)
    legal = legalise(snapped) or legalise(padded)
    if legal is None:
        raise RegionTooSmall(
            f"a {width}x{height} image cannot yield a crop {manifest.id} accepts "
            f"(needs at least {pixels.min:,} pixels); edit the whole image instead"
        )

    plan = plan_region_edit(parent, legal, padding=0, snap_tolerance=0)

    request = RegionRequest(
        crop_png=to_png(plan.crop),
        rect=plan.rect,
        width=plan.rect.width,
        height=plan.rect.height,
        gutter_fraction=plan.gutter_fraction,
        snapped=snapped.as_tuple() != padded.as_tuple(),
        grew=plan.rect.as_tuple() != rect.as_tuple(),
    )
    return request, parent, plan


def finish(parent, plan, returned_pngs: list[bytes]) -> tuple[RegionResult, list[RegionResult]]:
    """Align, colour-match, composite and rank every returned crop."""
    candidates = [to_array(data) for data in returned_pngs]
    mismatched = [c.shape[:2] for c in candidates if c.shape[:2] != plan.crop.shape[:2]]
    if mismatched:
        raise ValueError(f"provider returned crops of {mismatched}, expected {plan.crop.shape[:2]}")
    return choose_best(parent, plan, candidates)


def parse_region(raw: str | None) -> Rect | None:
    """Parse the stored "left,top,right,bottom" form."""
    if not raw:
        return None
    try:
        left, top, right, bottom = (int(v) for v in raw.split(","))
    except ValueError as exc:
        raise ValueError(f"malformed region {raw!r}; expected 'left,top,right,bottom'") from exc
    return Rect(left, top, right, bottom)


def format_region(rect: Rect) -> str:
    return f"{rect.left},{rect.top},{rect.right},{rect.bottom}"
