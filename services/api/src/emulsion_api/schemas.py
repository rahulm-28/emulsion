"""Wire types. Separate from the ORM so the database can change without breaking clients."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class RegionIn(BaseModel):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    right: int = Field(ge=0)
    bottom: int = Field(ge=0)

    @model_validator(mode="after")
    def _non_empty(self) -> RegionIn:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("region must have positive width and height")
        return self


class CreateJobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32_000)
    model_id: str = "gpt-image-2"
    size: str = "1k"
    n: int = Field(default=1, ge=1, le=8)
    # Set to rerun or edit an existing image; becomes the lineage parent.
    parent_image_id: str | None = None
    # Omit to start a new conversation; the title is derived from the prompt.
    session_id: str | None = None
    # Edit only this rectangle of the parent, in parent-image pixels. The engine grows
    # it to a size the model accepts and snaps it onto whitespace before sending.
    region: RegionIn | None = None

    @model_validator(mode="after")
    def _region_needs_a_parent(self) -> CreateJobRequest:
        if self.region is not None and not self.parent_image_id:
            raise ValueError("region requires parent_image_id")
        return self


class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    id: str
    title: str
    model_id: str
    job_count: int
    image_count: int
    cost_usd: float
    thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime


class DroppedPartOut(BaseModel):
    kind: str
    reason: str


class ImageOut(BaseModel):
    id: str
    job_id: str | None
    parent_id: str | None
    # Archival original. Prefer viewer_url for display and gallery_url for thumbnails —
    # the original can be 13 MB.
    url: str
    viewer_url: str
    gallery_url: str
    width: int
    height: int
    size_bytes: int
    model_id: str
    prompt: str
    created_at: datetime


class JobEventOut(BaseModel):
    seq: int
    kind: str
    message: str
    created_at: datetime


class JobOut(BaseModel):
    id: str
    session_id: str | None
    status: str
    model_id: str
    prompt: str
    size: str
    n: int
    parent_image_id: str | None
    region: RegionIn | None
    error: str | None
    dropped_parts: list[DroppedPartOut] = []
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    images: list[ImageOut] = []
    events: list[JobEventOut] = []


class ModelOut(BaseModel):
    id: str
    provider: str
    sizes: list[str]
    max_n_per_request: int
    mask_support: str
    edit_full_regen: bool
    unsupported_params: list[str]
    approx_rpm: float
