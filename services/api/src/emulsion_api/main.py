"""The HTTP surface. It creates jobs and reports on them. It never calls a model.

Invariant 1 is the shape of this whole file: POST /v1/jobs returns a job id
immediately, a worker does the work, and progress arrives over SSE. There is no
endpoint here that waits for a model, and adding one would be a rewrite later.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from collections.abc import AsyncIterator
from datetime import UTC, timedelta
from typing import Annotated

from emulsion_db import HouseStyle as HouseStyleRow
from emulsion_db import (
    Image,
    ImageUpload,
    Job,
    JobEvent,
    JobSpecification,
    JobStatus,
    QueueMessage,
    User,
    get_sessionmaker,
    utcnow,
)
from emulsion_db import Session as DbSession
from emulsion_engine import HouseStyle, classify, compile_prompt, extract_recurring
from emulsion_engine.spec import diagram_from_dict
from emulsion_imaging import export as imaging_export
from emulsion_imaging.ingest import MAX_UPLOAD_BYTES
from emulsion_platform import AuthError, Principal, identity_provider
from emulsion_providers import SIZE_PRESETS, available_models, load_manifest
from emulsion_worker import blob_store, bootstrap, queue, run_forever, settings
from emulsion_worker.imports import staging_path
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import quota
from .schemas import (
    CreateJobRequest,
    DiagramIn,
    DiagramPreviewRequest,
    DroppedPartOut,
    ExportOut,
    ExportRequest,
    ImageOut,
    JobEventOut,
    JobOut,
    ModelOut,
    RegionIn,
    SessionOut,
    StyleIn,
    StyleOut,
    SuggestionOut,
    UpdateSessionRequest,
)

log = logging.getLogger("emulsion.api")

# A 4K generation runs 40–300s, so the stream has to outlive that comfortably; the cap
# only exists so an abandoned connection cannot be held open forever.
STREAM_MAX_SECONDS = 900.0
POLL_INTERVAL_S = 0.4

_stop_worker = threading.Event()


def get_session() -> Session:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]

_identity = identity_provider()


def current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
    session_cookie: Annotated[str | None, Cookie(alias="__session")] = None,
) -> User:
    """Resolve the caller, creating their row on first sight.

    Every list, read and write below filters on the row this returns. Ownership is
    denormalised onto jobs and images so that filter is one indexed comparison rather
    than a join back through the session — a scoping bug here shows another user their
    pictures, so the query has to be impossible to get subtly wrong.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif session_cookie:
        # EventSource cannot set an Authorization header, so the SSE endpoint would be
        # unauthenticatable on a header-only scheme. Clerk sets `__session` on the same
        # origin, and Front Door makes the API same-origin in production, so the cookie
        # is available exactly where the header is not.
        token = session_cookie
    try:
        principal: Principal = _identity.authenticate(token)
    except AuthError as exc:
        raise HTTPException(401, "not authenticated") from exc

    user = session.execute(
        select(User).where(User.subject == principal.subject)
    ).scalar_one_or_none()
    if user is None:
        user = User(
            subject=principal.subject,
            email=principal.email,
            display_name=principal.display_name,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    elif (principal.email and principal.email != user.email) or (
        principal.display_name and principal.display_name != user.display_name
    ):
        # The identity provider is the source of truth for both, and either can change
        # after the row exists — a new claim configured on the token, or the person
        # editing their profile. Writing only on insert would pin whatever happened to
        # be in the very first token forever.
        user.email = principal.email or user.email
        user.display_name = principal.display_name or user.display_name
        session.commit()
        session.refresh(user)
    return user


UserDep = Annotated[User, Depends(current_user)]


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    thread: threading.Thread | None = None
    if settings().inline_worker:
        # Convenience for local development only. In production the worker is its own
        # Container Apps Job with its own scaling and its own failure domain (M0 §3.2).
        thread = threading.Thread(
            target=run_forever, args=(_stop_worker,), name="emulsion-inline-worker", daemon=True
        )
        thread.start()
        log.info("inline worker started (set EMULSION_INLINE_WORKER=0 to disable)")
    try:
        yield
    finally:
        _stop_worker.set()
        if thread is not None:
            thread.join(timeout=5)


app = FastAPI(title="Emulsion API", version="0.1.0", lifespan=lifespan)

# Front Door path-routing means one origin in production, so CORS is a local-dev
# concern only — the web app runs on :3000 and the API on :8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ponytail: local blob serving. Invariant 4 says image bytes never pass through Python —
# in production the client fetches blob storage directly from a signed URL and this mount
# does not exist. It is here so `docker compose` and a cloud account are optional.
blob_store()  # creates the directory StaticFiles is about to require
app.mount("/_blobs", StaticFiles(directory=str(settings().blob_dir)), name="blobs")


# -- serialisation ---------------------------------------------------------------


def _image_out(image: Image) -> ImageOut:
    return ImageOut(
        id=image.id,
        job_id=image.job_id,
        parent_id=image.parent_id,
        url=blob_store().signed_url(image.blob_key),
        # Fall back to the archival key when a derivative is absent — images written
        # before the pyramid existed still have to render.
        viewer_url=blob_store().signed_url(image.viewer_key or image.blob_key),
        gallery_url=blob_store().signed_url(
            image.gallery_key or image.viewer_key or image.blob_key
        ),
        width=image.width,
        height=image.height,
        size_bytes=image.size_bytes,
        model_id=image.model_id,
        prompt=image.prompt,
        created_at=image.created_at,
    )


def _latest_image_in(session: Session, chat_id: str, owner_id: str) -> Image | None:
    """The most recent image in this conversation, or None.

    Scoped by owner as well as conversation: the conversation is already the caller's,
    but every query that reaches images repeats the ownership filter rather than
    trusting an earlier check to have happened.
    """
    return session.execute(
        select(Image)
        .join(Job, Image.job_id == Job.id)
        .where(Job.session_id == chat_id, Image.owner_id == owner_id)
        .order_by(Image.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        diagram=(
            DiagramIn.model_validate_json(job.specification.diagram_json)
            if job.specification
            else None
        ),
        session_id=job.session_id,
        status=job.status,
        model_id=job.model_id,
        prompt=job.prompt,
        size=job.size,
        n=job.n,
        parent_image_id=job.parent_image_id,
        region=_region_out(job.region),
        error=job.error,
        dropped_parts=[DroppedPartOut(**d) for d in json.loads(job.dropped_parts or "[]")],
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        cost_usd=job.cost_usd,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        images=[_image_out(i) for i in job.images],
        events=[
            JobEventOut(seq=e.seq, kind=e.kind, message=e.message, created_at=e.created_at)
            for e in job.events
        ],
    )


def _session_out(session: DbSession) -> SessionOut:
    images = [image for job in session.jobs for image in job.images]
    return SessionOut(
        id=session.id,
        title=session.title,
        model_id=session.model_id,
        style_id=session.style_id,
        link_consistency=session.link_consistency,
        job_count=sum(job.kind != "upload" for job in session.jobs),
        image_count=len(images),
        cost_usd=round(sum(job.cost_usd or 0.0 for job in session.jobs), 6),
        thumbnail_url=(
            # The gallery derivative — a sidebar of 13 MB PNGs is not a sidebar.
            blob_store().signed_url(images[-1].gallery_key or images[-1].blob_key)
            if images
            else None
        ),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _style_out(row: HouseStyleRow) -> StyleOut:
    return StyleOut(
        id=row.id,
        name=row.name,
        legend=json.loads(row.legend_json or "{}"),
        rules=json.loads(row.rules_json or "[]"),
        style_words=json.loads(row.style_words_json or "[]"),
        layout=row.layout or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _region_out(raw: str | None) -> RegionIn | None:
    if not raw:
        return None
    try:
        left, top, right, bottom = (int(v) for v in raw.split(","))
    except ValueError:
        return None
    return RegionIn(left=left, top=top, right=right, bottom=bottom)


def _title_from(prompt: str, limit: int = 48) -> str:
    """First clause of the prompt, trimmed on a word boundary."""
    flat = " ".join(prompt.split())
    if len(flat) <= limit:
        return flat or "Untitled"
    return flat[:limit].rsplit(" ", 1)[0] + "…"


# -- routes ----------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "adapter": settings().adapter, "queue_depth": queue().depth()}


@app.get("/v1/models", response_model=list[ModelOut])
def list_models() -> list[ModelOut]:
    out = []
    for model_id in available_models():
        m = load_manifest(model_id)
        out.append(
            ModelOut(
                id=m.id,
                provider=m.provider,
                sizes=list(SIZE_PRESETS),
                max_n_per_request=m.n_per_request,
                mask_support=m.mask_support.value,
                edit_full_regen=m.edit_full_regen,
                unsupported_params=m.unsupported_params,
                approx_rpm=round(m.rate_limit.approx_rpm, 1),
            )
        )
    return out


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    session_id: str | None = None


def _owned_upload(upload_id: str, session: Session, user: User) -> ImageUpload:
    upload = session.get(ImageUpload, upload_id)
    if upload is None or upload.owner_id != user.id:
        raise HTTPException(404, "Upload not found.")
    return upload


def _check_upload_expiry(upload: ImageUpload) -> None:
    expires = upload.expires_at.replace(tzinfo=UTC)
    if expires <= utcnow():
        raise HTTPException(410, "This upload expired. Please attach the image again.")


@app.post("/v1/uploads", status_code=201)
def create_upload(body: UploadRequest, session: SessionDep, user: UserDep) -> dict:
    if body.session_id:
        chat = session.get(DbSession, body.session_id)
        if chat is None or chat.owner_id != user.id:
            raise HTTPException(404, "Conversation not found.")
    upload = ImageUpload(
        owner_id=user.id,
        session_id=body.session_id,
        filename=body.filename,
        size_bytes=body.size_bytes,
        expires_at=utcnow() + timedelta(minutes=15),
    )
    session.add(upload)
    session.commit()
    session.refresh(upload)
    # Local-only storage shim. Cloud storage must supply a direct signed PUT URL.
    return {"id": upload.id, "upload_url": f"/_uploads/{upload.id}"}


@app.put("/_uploads/{upload_id}", status_code=204)
async def put_local_upload(
    upload_id: str,
    request: Request,
    session: SessionDep,
    user: UserDep,
) -> None:
    """Local storage emulation, like /_blobs. Not a production byte-proxy route."""
    from .upload_storage import receive

    upload = _owned_upload(upload_id, session, user)
    _check_upload_expiry(upload)
    if upload.received or upload.job_id:
        raise HTTPException(409, "This upload has already been received.")
    await receive(request, staging_path(upload.id), upload.size_bytes)
    upload.received = True
    session.commit()


@app.post("/v1/uploads/{upload_id}/complete", response_model=JobOut, status_code=202)
def complete_upload(upload_id: str, session: SessionDep, user: UserDep) -> JobOut:
    upload = _owned_upload(upload_id, session, user)
    if upload.job_id:
        return _job_out(session.get(Job, upload.job_id))
    _check_upload_expiry(upload)
    if not upload.received:
        raise HTTPException(409, "The image has not finished uploading.")
    chat = session.get(DbSession, upload.session_id) if upload.session_id else None
    if upload.session_id and (chat is None or chat.owner_id != user.id):
        raise HTTPException(404, "Conversation not found.")
    if chat is None:
        chat = DbSession(owner_id=user.id, title=_title_from(upload.filename))
        session.add(chat)
        session.flush()
    chat.updated_at = utcnow()
    job = Job(
        owner_id=user.id,
        session_id=chat.id,
        kind="upload",
        model_id="upload",
        prompt=upload.filename,
        size="original",
        n=1,
    )
    session.add(job)
    session.flush()
    claimed = session.execute(
        update(ImageUpload)
        .where(ImageUpload.id == upload.id, ImageUpload.job_id.is_(None))
        .values(job_id=job.id)
    )
    if claimed.rowcount != 1:
        session.rollback()
        upload = _owned_upload(upload_id, session, user)
        return _job_out(session.get(Job, upload.job_id))
    # Atomic with the job: completion cannot leave an accepted import unqueued.
    session.add(QueueMessage(body=json.dumps({"job_id": job.id})))
    session.commit()
    session.refresh(job)
    return _job_out(job)


@app.post("/v1/jobs", response_model=JobOut, status_code=202)
def create_job(
    body: CreateJobRequest,
    session: SessionDep,
    user: UserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobOut:
    """Accept work and return immediately. The model is never called on this thread."""
    if body.model_id not in available_models():
        raise HTTPException(404, f"unknown model {body.model_id!r}")
    try:
        # Validate the size against the model before queueing, so a bad request fails
        # here rather than 40 seconds later inside a worker.
        from emulsion_providers import resolve_size

        resolve_size(body.size, load_manifest(body.model_id).pixels)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if body.parent_image_id:
        parent = session.get(Image, body.parent_image_id)
        if parent is None or parent.owner_id != user.id:
            raise HTTPException(404, f"unknown parent image {body.parent_image_id!r}")

    if idempotency_key:
        existing = session.execute(
            select(Job).where(Job.idempotency_key == idempotency_key, Job.owner_id == user.id)
        ).scalar_one_or_none()
        if existing is not None:
            return _job_out(existing)
    if body.style_id:
        _owned_style(body.style_id, session, user)

    # ponytail: the quota check runs and currently always passes. It is here so M8 is a
    # policy change rather than a hunt for every place a job is created.
    decision = quota.check(user)
    if not decision.allowed:
        raise HTTPException(402, decision.reason)

    chat = session.get(DbSession, body.session_id) if body.session_id else None
    if body.session_id and (chat is None or chat.owner_id != user.id):
        raise HTTPException(404, f"unknown session {body.session_id!r}")
    if chat is None:
        # A first prompt creates its own conversation, so nothing has to exist first.
        chat = DbSession(owner_id=user.id, title=_title_from(body.prompt), model_id=body.model_id)
        session.add(chat)
        session.flush()
    else:
        chat.updated_at = utcnow()
        chat.model_id = body.model_id
    if "style_id" in body.model_fields_set:
        chat.style_id = body.style_id or None
    if body.link_consistency is not None:
        chat.link_consistency = body.link_consistency

    # Conversational edit: "make the title bigger" with a picture already on screen is
    # a change to that picture, not a new one. Only inferred when the caller did not
    # say — an explicit parent_image_id or a drawn region is a decision already made.
    routing: str | None = None
    parent_image_id = body.parent_image_id
    if parent_image_id is None and body.region is None and body.mode != "generate":
        previous = _latest_image_in(session, chat.id, user.id)
        if previous is not None:
            intent = classify(body.prompt, has_previous_image=True)
            if body.mode == "edit" or intent.is_edit:
                parent_image_id = previous.id
                routing = f"editing your previous image — {intent.reason}"
        elif body.mode == "edit":
            raise HTTPException(422, "Attach or generate an image before choosing Edit latest.")

    diagram = body.diagram
    if diagram is None and parent_image_id:
        parent = session.get(Image, parent_image_id)
        if parent.job and parent.job.specification:
            diagram = DiagramIn.model_validate_json(parent.job.specification.diagram_json)

    job = Job(
        idempotency_key=idempotency_key,
        owner_id=user.id,
        session_id=chat.id,
        region=(
            f"{body.region.left},{body.region.top},{body.region.right},{body.region.bottom}"
            if body.region
            else None
        ),
        status=JobStatus.QUEUED,
        kind="edit" if parent_image_id else "generate",
        model_id=body.model_id,
        prompt=body.prompt,
        size=body.size,
        n=body.n,
        parent_image_id=parent_image_id,
    )
    session.add(job)
    if diagram is not None:
        job.specification = JobSpecification(diagram_json=diagram.model_dump_json())
    try:
        session.flush()
        if routing is not None:
            session.add(JobEvent(job_id=job.id, seq=0, kind="status", message=routing))
        session.add(QueueMessage(body=json.dumps({"job_id": job.id})))
        session.commit()
    except IntegrityError:
        # Invariant 8: the unique index is the real guard. Two concurrent submits with
        # the same key race here, and the loser returns the winner's job rather than
        # creating a second one — a double charge on a paid tier otherwise.
        session.rollback()
        existing = session.execute(
            select(Job).where(Job.idempotency_key == idempotency_key, Job.owner_id == user.id)
        ).scalar_one_or_none()
        if existing is None:
            raise
        return _job_out(existing)

    session.refresh(job)
    return _job_out(job)


def _owned_style(style_id: str, session: Session, user: User) -> HouseStyleRow:
    row = session.get(HouseStyleRow, style_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "Style not found.")
    return row


@app.post("/v1/diagrams/preview")
def preview_diagram(body: DiagramPreviewRequest, session: SessionDep, user: UserDep) -> dict:
    """Deterministic compilation only. Previewing never enqueues work or calls a model."""
    if body.model_id not in available_models():
        raise HTTPException(404, "Model not found.")
    style = None
    if body.style_id:
        row = _owned_style(body.style_id, session, user)
        style = HouseStyle(
            name=row.name,
            legend=json.loads(row.legend_json),
            rules=tuple(json.loads(row.rules_json)),
            layout=row.layout,
            style_words=tuple(json.loads(row.style_words_json)),
        )
    compiled = compile_prompt(
        body.prompt,
        load_manifest(body.model_id),
        spec=diagram_from_dict(body.diagram.model_dump()),
        style=style,
    )
    return {"text": compiled.text, "warnings": list(compiled.warnings)}


@app.get("/v1/styles", response_model=list[StyleOut])
def list_styles(session: SessionDep, user: UserDep) -> list[StyleOut]:
    rows = (
        session.execute(
            select(HouseStyleRow)
            .where(HouseStyleRow.owner_id == user.id)
            .order_by(HouseStyleRow.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [_style_out(r) for r in rows]


@app.post("/v1/styles", response_model=StyleOut, status_code=201)
def create_style(body: StyleIn, session: SessionDep, user: UserDep) -> StyleOut:
    row = HouseStyleRow(
        owner_id=user.id,
        name=body.name,
        legend_json=json.dumps(body.legend),
        rules_json=json.dumps(body.rules),
        style_words_json=json.dumps(body.style_words),
        layout=body.layout,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _style_out(row)


@app.patch("/v1/styles/{style_id}", response_model=StyleOut)
def update_style(style_id: str, body: StyleIn, session: SessionDep, user: UserDep) -> StyleOut:
    row = session.get(HouseStyleRow, style_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "style not found")
    row.name = body.name
    row.legend_json = json.dumps(body.legend)
    row.rules_json = json.dumps(body.rules)
    row.style_words_json = json.dumps(body.style_words)
    row.layout = body.layout
    row.updated_at = utcnow()
    session.commit()
    session.refresh(row)
    return _style_out(row)


@app.delete("/v1/styles/{style_id}", status_code=204)
def delete_style(style_id: str, session: SessionDep, user: UserDep) -> None:
    row = session.get(HouseStyleRow, style_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(404, "style not found")
    # Sessions referencing it fall back to no style rather than cascading away.
    session.delete(row)
    session.commit()


@app.get("/v1/styles/suggestions", response_model=list[SuggestionOut])
def style_suggestions(
    session: SessionDep,
    user: UserDep,
    min_occurrences: Annotated[int, Query(ge=2, le=20)] = 3,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SuggestionOut]:
    """Clauses the user keeps typing, with the prompts that produced them.

    Suggestions only — nothing is applied until it is promoted into a style. A learned
    constraint the user cannot see or overrule is one that will eventually ruin a
    picture for reasons nobody can debug.
    """
    prompts = (
        session.execute(
            select(Job.prompt)
            .where(Job.owner_id == user.id, Job.kind != "upload")
            .order_by(Job.created_at.desc())
            .limit(400)
        )
        .scalars()
        .all()
    )
    found = extract_recurring(list(prompts), min_occurrences=min_occurrences)
    return [
        SuggestionOut(text=s.text, occurrences=s.occurrences, examples=list(s.examples))
        for s in found[:limit]
    ]


@app.get("/v1/sessions", response_model=list[SessionOut])
def list_sessions(
    session: SessionDep, user: UserDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[SessionOut]:
    chats = (
        session.execute(
            select(DbSession)
            .where(DbSession.owner_id == user.id)
            .options(selectinload(DbSession.jobs).selectinload(Job.images))
            .order_by(DbSession.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_session_out(c) for c in chats]


@app.get("/v1/sessions/{session_id}/jobs", response_model=list[JobOut])
def session_jobs(session_id: str, session: SessionDep, user: UserDep) -> list[JobOut]:
    chat = session.get(DbSession, session_id)
    if chat is None or chat.owner_id != user.id:
        raise HTTPException(404, "session not found")
    return [_job_out(job) for job in chat.jobs]


@app.patch("/v1/sessions/{session_id}", response_model=SessionOut)
def rename_session(
    session_id: str, body: UpdateSessionRequest, session: SessionDep, user: UserDep
) -> SessionOut:
    chat = session.get(DbSession, session_id)
    if chat is None or chat.owner_id != user.id:
        raise HTTPException(404, "session not found")
    if body.title is not None:
        chat.title = body.title
    if body.style_id is not None:
        style_row = session.get(HouseStyleRow, body.style_id) if body.style_id else None
        if body.style_id and (style_row is None or style_row.owner_id != user.id):
            raise HTTPException(404, f"unknown style {body.style_id!r}")
        chat.style_id = body.style_id or None
    if body.link_consistency is not None:
        chat.link_consistency = body.link_consistency
    session.commit()
    session.refresh(chat)
    return _session_out(chat)


@app.delete("/v1/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, session: SessionDep, user: UserDep) -> None:
    chat = session.get(DbSession, session_id)
    if chat is None or chat.owner_id != user.id:
        raise HTTPException(404, "session not found")
    # ponytail: rows go, blobs stay. Orphaned blobs need a sweeper (or a lifecycle rule
    # on the container) before this ships — deleting bytes on a cascade is how you lose
    # an image that another version still references.
    session.delete(chat)
    session.commit()


@app.get("/v1/jobs", response_model=list[JobOut])
def list_jobs(
    session: SessionDep, user: UserDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[JobOut]:
    jobs = (
        session.execute(
            select(Job)
            .where(Job.owner_id == user.id)
            .options(selectinload(Job.images), selectinload(Job.events))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_job_out(j) for j in jobs]


@app.get("/v1/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: SessionDep, user: UserDep) -> JobOut:
    job = session.get(Job, job_id)
    if job is None or job.owner_id != user.id:
        raise HTTPException(404, "job not found")
    return _job_out(job)


@app.get("/v1/jobs/{job_id}/events")
async def stream_events(job_id: str, session: SessionDep, user: UserDep) -> StreamingResponse:
    """SSE tail of `job_events`, closing once the job reaches a terminal state.

    Polling the table rather than holding a subscription is deliberate: it survives an
    API restart and works identically with several API replicas, which an in-process
    pub/sub would not.

    Deliberately does not call `request.is_disconnected()`: it blocks forever when the
    request body is already consumed. Starlette closes this generator when the client
    goes away, and STREAM_MAX_SECONDS bounds it either way — EventSource reconnects on
    its own, so an idle stream ending is not an error.
    """

    # Checked once, before streaming: the terminal frame carries the whole job,
    # including image URLs, so an unscoped stream is a data leak with extra steps.
    owned = session.get(Job, job_id)
    if owned is None or owned.owner_id != user.id:
        raise HTTPException(404, "job not found")

    async def event_stream() -> AsyncIterator[str]:
        last_seq = -1
        deadline = asyncio.get_running_loop().time() + STREAM_MAX_SECONDS
        while True:
            terminal = False
            payloads: list[str] = []
            session = get_sessionmaker()()
            try:
                job = session.get(Job, job_id)
                if job is None or job.owner_id != user.id:
                    yield _sse("error", {"message": "job not found"})
                    return
                events = (
                    session.execute(
                        select(JobEvent)
                        .where(JobEvent.job_id == job_id, JobEvent.seq > last_seq)
                        .order_by(JobEvent.seq)
                    )
                    .scalars()
                    .all()
                )
                for event in events:
                    last_seq = max(last_seq, event.seq)
                    payloads.append(_sse(event.kind, {"message": event.message, "seq": event.seq}))
                terminal = job.status in JobStatus.TERMINAL
                if terminal:
                    payloads.append(_sse("done", json.loads(_job_out(job).model_dump_json())))
            finally:
                session.close()

            for payload in payloads:
                yield payload
            if terminal:
                return
            if asyncio.get_running_loop().time() >= deadline:
                yield _sse("timeout", {"message": "stream expired; reconnect to continue"})
                return
            await asyncio.sleep(POLL_INTERVAL_S)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/images", response_model=list[ImageOut])
def list_images(
    session: SessionDep, user: UserDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[ImageOut]:
    images = (
        session.execute(
            select(Image)
            .where(Image.owner_id == user.id)
            .order_by(Image.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_image_out(i) for i in images]


@app.get("/v1/images/{image_id}", response_model=ImageOut)
def get_image(image_id: str, session: SessionDep, user: UserDep) -> ImageOut:
    image = session.get(Image, image_id)
    if image is None or image.owner_id != user.id:
        raise HTTPException(404, "image not found")
    return _image_out(image)


@app.get("/v1/images/{image_id}/content")
def image_content(image_id: str, session: SessionDep, user: UserDep) -> RedirectResponse:
    """Redirect to the blob URL. The API never streams the bytes itself (invariant 4)."""
    image = session.get(Image, image_id)
    if image is None or image.owner_id != user.id:
        raise HTTPException(404, "image not found")
    return RedirectResponse(blob_store().signed_url(image.blob_key), status_code=307)


@app.post("/v1/images/{image_id}/export", response_model=ExportOut)
def export_image(
    image_id: str, body: ExportRequest, session: SessionDep, user: UserDep
) -> ExportOut:
    """Post-process an image and hand back a URL to the result.

    ponytail: synchronous. Invariant 1 forbids a synchronous endpoint that calls a
    *model*; this calls numpy, and a 4K transparency pass plus re-encode is a second or
    two. If that stops being true — a real super-resolution model, say — this becomes a
    job like everything else, and the route keeps its shape by returning a job id.
    """
    image = session.get(Image, image_id)
    if image is None or image.owner_id != user.id:
        raise HTTPException(404, "image not found")

    try:
        result = imaging_export(
            blob_store().get(image.blob_key),
            fmt=body.format,
            transparent=body.transparent,
            scale=body.scale,
            quality=body.quality,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # The key encodes the options, so re-exporting the same settings overwrites rather
    # than accumulating a new blob per click.
    parts = [body.format]
    if result.has_alpha:
        parts.append("alpha")
    if body.scale != 1:
        parts.append(f"{body.scale:g}x")
    key = f"exports/{image_id}.{'-'.join(parts)}.{body.format}"
    blob_store().put(key, result.data, result.content_type)

    return ExportOut(
        url=blob_store().signed_url(key),
        width=result.width,
        height=result.height,
        content_type=result.content_type,
        has_alpha=result.has_alpha,
        background_uniform=result.background_uniform,
        size_bytes=len(result.data),
    )


@app.get("/v1/images/{image_id}/lineage", response_model=list[ImageOut])
def image_lineage(image_id: str, session: SessionDep, user: UserDep) -> list[ImageOut]:
    """Walk parent links to the root. Oldest first."""
    chain: list[Image] = []
    seen: set[str] = set()
    current = session.get(Image, image_id)
    if current is None or current.owner_id != user.id:
        raise HTTPException(404, "image not found")
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        parent = session.get(Image, current.parent_id) if current.parent_id else None
        # Never cross an ownership boundary while walking lineage.
        current = parent if parent is not None and parent.owner_id == user.id else None
    return [_image_out(i) for i in reversed(chain)]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
