"""Wire types. Separate from the ORM so the database can change without breaking clients."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)


class TimestampedOut(BaseModel):
    @field_serializer("created_at", "updated_at", "started_at", "finished_at", check_fields=False)
    def _utc_timestamp(self, value: datetime | None) -> str | None:
        # SQLite drops timezone metadata. Stored timestamps are UTC, not browser local time.
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ComponentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    layer: ShortText = ""
    role: ShortText = ""
    items: list[ShortText] = Field(default_factory=list, max_length=30)
    note: ShortText = ""
    emphasis: Literal["dominant", "normal", "aside"] = "normal"


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Name
    target: Name
    label: ShortText = ""
    bidirectional: bool = False
    weight: Literal["primary", "secondary"] = "primary"


class CalloutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: Name
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class DiagramIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    key_message: ShortText = ""
    layout: ShortText = ""
    legend: dict[Name, ShortText] = Field(default_factory=dict, max_length=30)
    components: list[ComponentIn] = Field(default_factory=list, max_length=40)
    connections: list[ConnectionIn] = Field(default_factory=list, max_length=80)
    callouts: list[CalloutIn] = Field(default_factory=list, max_length=30)
    consistency_with: ShortText = ""

    @model_validator(mode="after")
    def _references_exist(self) -> DiagramIn:
        names = [component.name for component in self.components]
        if len(set(names)) != len(names):
            raise ValueError("Each component needs a unique name.")
        if any(link.source not in names or link.target not in names for link in self.connections):
            raise ValueError("Every connection must join two components in this diagram.")
        if any(note.anchor not in names for note in self.callouts):
            raise ValueError("Each annotation must point to a component in this diagram.")
        return self


class DiagramPreviewRequest(BaseModel):
    diagram: DiagramIn
    prompt: str = Field(default="", max_length=32_000)
    model_id: str = "gpt-image-2"
    style_id: str | None = None


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
    diagram: DiagramIn | None = None
    mode: Literal["auto", "generate", "edit"] = "auto"
    style_id: str | None = None
    link_consistency: bool | None = None
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
        if self.mode == "generate" and self.parent_image_id:
            raise ValueError("New image mode cannot also have an edit source.")
        return self


class StyleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    legend: dict[str, str] = Field(default_factory=dict)
    rules: list[str] = Field(default_factory=list)
    style_words: list[str] = Field(default_factory=list)
    layout: str = ""


class StyleOut(StyleIn, TimestampedOut):
    id: str
    created_at: datetime
    updated_at: datetime


class SuggestionOut(BaseModel):
    """A constraint the user keeps typing, with the evidence for it."""

    text: str
    occurrences: int
    examples: list[str]


class ExportRequest(BaseModel):
    format: Literal["png", "webp", "jpeg"] = "png"
    transparent: bool = False
    scale: float = Field(default=1.0, ge=0.25, le=4.0)
    quality: int = Field(default=90, ge=40, le=100)


class ExportOut(BaseModel):
    url: str
    # False when the source had no uniform background, so transparency was skipped.
    background_uniform: bool = True
    width: int
    height: int
    content_type: str
    has_alpha: bool
    size_bytes: int


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    style_id: str | None = None
    link_consistency: bool | None = None


class SessionOut(TimestampedOut):
    id: str
    title: str
    model_id: str
    style_id: str | None
    link_consistency: bool
    job_count: int
    image_count: int
    cost_usd: float
    thumbnail_url: str | None
    created_at: datetime
    updated_at: datetime


class DroppedPartOut(BaseModel):
    kind: str
    reason: str


class ImageOut(TimestampedOut):
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


class JobEventOut(TimestampedOut):
    seq: int
    kind: str
    message: str
    created_at: datetime


class JobOut(TimestampedOut):
    id: str
    kind: str = "generate"
    diagram: DiagramIn | None = None
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
