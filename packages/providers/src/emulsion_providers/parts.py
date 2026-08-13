"""Typed request parts, and the rule that a dropped part is never a silent one.

A request carries a list of parts, never a prompt string (M0 §4.5). Adapters send
the parts their manifest supports and report the rest — invariant 7. The reporting
half is the point: a model quietly ignoring a reference image looks identical to a
bad prompt from the user's side of the screen.

Nothing here knows which model it is looking at. Support is decided by manifest data.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .manifest import Manifest, MaskSupport


class TextPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    """A source image (the thing being edited) or a reference (style/content guidance)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["image"] = "image"
    role: Literal["source", "reference"]
    blob_id: str


class MaskPart(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["mask"] = "mask"
    blob_id: str


class RegionPart(BaseModel):
    """A rectangle in parent-image coordinates, as (left, top, right, bottom)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["region"] = "region"
    bbox: tuple[int, int, int, int]


AnyPart = Annotated[
    TextPart | ImagePart | MaskPart | RegionPart,
    Field(discriminator="kind"),
]


class Request(BaseModel):
    model_config = ConfigDict(frozen=True)

    parts: list[AnyPart]


class DroppedPart(BaseModel):
    """Why one part did not reach the model. Surfaced to the user, never swallowed."""

    model_config = ConfigDict(frozen=True)

    kind: str
    reason: str


def split_parts(request: Request, manifest: Manifest) -> tuple[list[AnyPart], list[DroppedPart]]:
    """Partition a request into (parts to send, parts dropped with a reason).

    Callers must surface `dropped`. Returning it rather than logging it is deliberate —
    a log line is not a user-visible report.
    """
    kept: list[AnyPart] = []
    dropped: list[DroppedPart] = []
    references_kept = 0

    for part in request.parts:
        match part:
            case TextPart():
                if "text" in manifest.modalities_in:
                    kept.append(part)
                else:
                    dropped.append(
                        DroppedPart(kind="text", reason=f"{manifest.id} accepts no text input")
                    )

            case ImagePart():
                if "image" not in manifest.modalities_in:
                    dropped.append(
                        DroppedPart(kind="image", reason=f"{manifest.id} accepts no image input")
                    )
                elif part.role == "reference" and references_kept >= manifest.multi_reference:
                    dropped.append(
                        DroppedPart(
                            kind="image",
                            reason=(
                                f"{manifest.id} accepts at most {manifest.multi_reference} "
                                f"reference images"
                            ),
                        )
                    )
                else:
                    if part.role == "reference":
                        references_kept += 1
                    kept.append(part)

            case MaskPart():
                if manifest.mask_support is MaskSupport.NONE:
                    dropped.append(
                        DroppedPart(kind="mask", reason=f"{manifest.id} does not accept a mask")
                    )
                else:
                    kept.append(part)

            case RegionPart():
                # A region is an Emulsion concept — it selects what to crop before the
                # call and where to composite after it. No provider takes one.
                dropped.append(
                    DroppedPart(
                        kind="region",
                        reason="region is resolved by the engine and never sent to a provider",
                    )
                )

    return kept, dropped
