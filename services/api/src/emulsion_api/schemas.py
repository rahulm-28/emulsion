"""Wire types. Separate from the ORM so the database can change without breaking clients."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=32_000)
    model_id: str = "gpt-image-2"
    size: str = "1k"
    n: int = Field(default=1, ge=1, le=8)
    # Set to rerun or edit an existing image; becomes the lineage parent.
    parent_image_id: str | None = None
    # Omit to start a new conversation; the title is derived from the prompt.
    session_id: str | None = None


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
    url: str
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
