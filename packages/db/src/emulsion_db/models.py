"""The data model. Jobs, their progress events, images, and lineage.

Every model call is an async job (invariant 1), so `Job` is the centre of the system:
the API only ever creates one and reports on it. Nothing here imports web machinery.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    TERMINAL = frozenset({SUCCEEDED, FAILED})


class User(Base):
    """One account. `subject` is whatever the identity provider calls this person."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    subject: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")

    # ponytail: billing stub. Every account is on `free` and no quota is enforced —
    # `plan` and `monthly_cost_cap_usd` exist so M8 is a metering implementation rather
    # than a migration. See `quota.py` for the check that currently always passes.
    plan: Mapped[str] = mapped_column(String(32), default="free")
    monthly_cost_cap_usd: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HouseStyle(Base):
    """A named, reusable set of diagram defaults.

    JSON columns because the shape is a small bag of user-authored strings that is read
    whole and never queried by its contents — a normalised legend table would be three
    joins to reconstruct one dictionary.
    """

    __tablename__ = "house_styles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    legend_json: Mapped[str] = mapped_column(Text, default="{}")
    rules_json: Mapped[str] = mapped_column(Text, default="[]")
    style_words_json: Mapped[str] = mapped_column(Text, default="[]")
    layout: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Session(Base):
    """A conversation. Jobs belong to one, which is what makes history navigable."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Untitled")
    model_id: Mapped[str] = mapped_column(String(64), default="gpt-image-2")
    style_id: Mapped[str | None] = mapped_column(ForeignKey("house_styles.id", ondelete="SET NULL"))
    # Off by default: linking every diagram to the previous one is right for a deck and
    # wrong for a scratch session, and the user knows which this is.
    link_consistency: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    jobs: Mapped[list[Job]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Job.created_at",
    )


class Job(Base):
    """One unit of model work. Created by the API, executed by the worker."""

    __tablename__ = "jobs"
    __table_args__ = (
        # Scoped per owner: two users choosing the same key is a coincidence, not a
        # conflict, and a global unique index hands a 500 to whoever submits second.
        UniqueConstraint("owner_id", "idempotency_key", name="uq_jobs_owner_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Invariant 8. A double-submitted retry on a paid tier is a double charge, so the
    # uniqueness is enforced by the database rather than by a check-then-insert race.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), index=True)

    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="generate")

    model_id: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    size: Mapped[str] = mapped_column(String(32))
    n: Mapped[int] = mapped_column(Integer, default=1)

    # Set when the job derives from an existing image — the lineage edge (M0 §4.6).
    parent_image_id: Mapped[str | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    # "left,top,right,bottom" in parent-image pixels, when this job edits a region.
    # Stored flat rather than as JSON because it is four integers that are always
    # present together, and a region is queried by "is there one" far more than by value.
    region: Mapped[str | None] = mapped_column(String(64))

    error: Mapped[str | None] = mapped_column(Text)
    # Parts the adapter could not send, as JSON. Surfaced to the user (invariant 7).
    dropped_parts: Mapped[str | None] = mapped_column(Text)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[Session | None] = relationship(back_populates="jobs")
    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.seq"
    )
    images: Mapped[list[Image]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        foreign_keys="Image.job_id",
    )
    specification: Mapped[JobSpecification | None] = relationship(
        cascade="all, delete-orphan",
        single_parent=True,
    )


class JobSpecification(Base):
    """An immutable diagram snapshot. Additive so existing local databases still open."""

    __tablename__ = "job_specifications"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    diagram_json: Mapped[str] = mapped_column(Text)


class JobEvent(Base):
    """Append-only progress log. The SSE stream is a tail of this table."""

    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_seq", "job_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="events")


class Image(Base):
    """A stored result. `parent_id` is the lineage edge; every version is retained."""

    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"))

    blob_key: Mapped[str] = mapped_column(String(300))
    # Derivative pyramid. Archival stays in blob_key; these two are what the UI loads,
    # because serving a 13 MB PNG to a thumbnail grid is how the bandwidth bill goes.
    viewer_key: Mapped[str | None] = mapped_column(String(300))
    gallery_key: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(64), default="image/png")
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)

    # Lineage records the model, so "regenerate v3 with a different model" is possible.
    model_id: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    job: Mapped[Job | None] = relationship(back_populates="images", foreign_keys=[job_id])


class QueueMessage(Base):
    """Rows backing the `Queue` protocol.

    ponytail: a table, polled. M0's production choice is Azure Storage Queue; this keeps
    local dev free of Azurite while exercising the same `Queue` protocol. Swap the
    implementation, not the callers. Postgres would use SELECT ... FOR UPDATE SKIP
    LOCKED here; SQLite serialises writes anyway, so the simple UPDATE is safe.
    """

    __tablename__ = "queue_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    body: Mapped[str] = mapped_column(Text)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImageUpload(Base):
    """An expiring, owner-bound staging object. One completed upload creates one job."""

    __tablename__ = "image_uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
