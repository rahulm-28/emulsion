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
from typing import Annotated

from emulsion_db import HouseStyle as HouseStyleRow
from emulsion_db import Image, Job, JobEvent, JobStatus, get_sessionmaker, utcnow
from emulsion_db import Session as DbSession
from emulsion_engine import extract_recurring
from emulsion_providers import SIZE_PRESETS, available_models, load_manifest
from emulsion_worker import blob_store, bootstrap, queue, run_forever, settings
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .schemas import (
    CreateJobRequest,
    DroppedPartOut,
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


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
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
        job_count=len(session.jobs),
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


@app.post("/v1/jobs", response_model=JobOut, status_code=202)
def create_job(
    body: CreateJobRequest,
    session: SessionDep,
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

    if body.parent_image_id and session.get(Image, body.parent_image_id) is None:
        raise HTTPException(404, f"unknown parent image {body.parent_image_id!r}")

    chat = session.get(DbSession, body.session_id) if body.session_id else None
    if body.session_id and chat is None:
        raise HTTPException(404, f"unknown session {body.session_id!r}")
    if chat is None:
        # A first prompt creates its own conversation, so nothing has to exist first.
        chat = DbSession(title=_title_from(body.prompt), model_id=body.model_id)
        session.add(chat)
        session.flush()
    else:
        chat.updated_at = utcnow()
        chat.model_id = body.model_id

    if idempotency_key:
        existing = session.execute(
            select(Job).where(Job.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return _job_out(existing)

    job = Job(
        idempotency_key=idempotency_key,
        session_id=chat.id,
        region=(
            f"{body.region.left},{body.region.top},{body.region.right},{body.region.bottom}"
            if body.region
            else None
        ),
        status=JobStatus.QUEUED,
        model_id=body.model_id,
        prompt=body.prompt,
        size=body.size,
        n=body.n,
        parent_image_id=body.parent_image_id,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        # Invariant 8: the unique index is the real guard. Two concurrent submits with
        # the same key race here, and the loser returns the winner's job rather than
        # creating a second one — a double charge on a paid tier otherwise.
        session.rollback()
        existing = session.execute(
            select(Job).where(Job.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is None:
            raise
        return _job_out(existing)

    session.refresh(job)
    queue().enqueue({"job_id": job.id})
    return _job_out(job)


@app.get("/v1/styles", response_model=list[StyleOut])
def list_styles(session: SessionDep) -> list[StyleOut]:
    rows = (
        session.execute(select(HouseStyleRow).order_by(HouseStyleRow.updated_at.desc()))
        .scalars()
        .all()
    )
    return [_style_out(r) for r in rows]


@app.post("/v1/styles", response_model=StyleOut, status_code=201)
def create_style(body: StyleIn, session: SessionDep) -> StyleOut:
    row = HouseStyleRow(
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
def update_style(style_id: str, body: StyleIn, session: SessionDep) -> StyleOut:
    row = session.get(HouseStyleRow, style_id)
    if row is None:
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
def delete_style(style_id: str, session: SessionDep) -> None:
    row = session.get(HouseStyleRow, style_id)
    if row is None:
        raise HTTPException(404, "style not found")
    # Sessions referencing it fall back to no style rather than cascading away.
    session.delete(row)
    session.commit()


@app.get("/v1/styles/suggestions", response_model=list[SuggestionOut])
def style_suggestions(
    session: SessionDep,
    min_occurrences: Annotated[int, Query(ge=2, le=20)] = 3,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SuggestionOut]:
    """Clauses the user keeps typing, with the prompts that produced them.

    Suggestions only — nothing is applied until it is promoted into a style. A learned
    constraint the user cannot see or overrule is one that will eventually ruin a
    picture for reasons nobody can debug.
    """
    prompts = (
        session.execute(select(Job.prompt).order_by(Job.created_at.desc()).limit(400))
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
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[SessionOut]:
    chats = (
        session.execute(
            select(DbSession)
            .options(selectinload(DbSession.jobs).selectinload(Job.images))
            .order_by(DbSession.updated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_session_out(c) for c in chats]


@app.get("/v1/sessions/{session_id}/jobs", response_model=list[JobOut])
def session_jobs(session_id: str, session: SessionDep) -> list[JobOut]:
    chat = session.get(DbSession, session_id)
    if chat is None:
        raise HTTPException(404, "session not found")
    return [_job_out(job) for job in chat.jobs]


@app.patch("/v1/sessions/{session_id}", response_model=SessionOut)
def rename_session(session_id: str, body: UpdateSessionRequest, session: SessionDep) -> SessionOut:
    chat = session.get(DbSession, session_id)
    if chat is None:
        raise HTTPException(404, "session not found")
    if body.title is not None:
        chat.title = body.title
    if body.style_id is not None:
        if body.style_id and session.get(HouseStyleRow, body.style_id) is None:
            raise HTTPException(404, f"unknown style {body.style_id!r}")
        chat.style_id = body.style_id or None
    if body.link_consistency is not None:
        chat.link_consistency = body.link_consistency
    session.commit()
    session.refresh(chat)
    return _session_out(chat)


@app.delete("/v1/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, session: SessionDep) -> None:
    chat = session.get(DbSession, session_id)
    if chat is None:
        raise HTTPException(404, "session not found")
    # ponytail: rows go, blobs stay. Orphaned blobs need a sweeper (or a lifecycle rule
    # on the container) before this ships — deleting bytes on a cascade is how you lose
    # an image that another version still references.
    session.delete(chat)
    session.commit()


@app.get("/v1/jobs", response_model=list[JobOut])
def list_jobs(session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[JobOut]:
    jobs = (
        session.execute(
            select(Job)
            .options(selectinload(Job.images), selectinload(Job.events))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [_job_out(j) for j in jobs]


@app.get("/v1/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: SessionDep) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_out(job)


@app.get("/v1/jobs/{job_id}/events")
async def stream_events(job_id: str) -> StreamingResponse:
    """SSE tail of `job_events`, closing once the job reaches a terminal state.

    Polling the table rather than holding a subscription is deliberate: it survives an
    API restart and works identically with several API replicas, which an in-process
    pub/sub would not.

    Deliberately does not call `request.is_disconnected()`: it blocks forever when the
    request body is already consumed. Starlette closes this generator when the client
    goes away, and STREAM_MAX_SECONDS bounds it either way — EventSource reconnects on
    its own, so an idle stream ending is not an error.
    """

    async def event_stream() -> AsyncIterator[str]:
        last_seq = -1
        deadline = asyncio.get_running_loop().time() + STREAM_MAX_SECONDS
        while True:
            terminal = False
            payloads: list[str] = []
            session = get_sessionmaker()()
            try:
                job = session.get(Job, job_id)
                if job is None:
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
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[ImageOut]:
    images = (
        session.execute(select(Image).order_by(Image.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [_image_out(i) for i in images]


@app.get("/v1/images/{image_id}", response_model=ImageOut)
def get_image(image_id: str, session: SessionDep) -> ImageOut:
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(404, "image not found")
    return _image_out(image)


@app.get("/v1/images/{image_id}/content")
def image_content(image_id: str, session: SessionDep) -> RedirectResponse:
    """Redirect to the blob URL. The API never streams the bytes itself (invariant 4)."""
    image = session.get(Image, image_id)
    if image is None:
        raise HTTPException(404, "image not found")
    return RedirectResponse(blob_store().signed_url(image.blob_key), status_code=307)


@app.get("/v1/images/{image_id}/lineage", response_model=list[ImageOut])
def image_lineage(image_id: str, session: SessionDep) -> list[ImageOut]:
    """Walk parent links to the root. Oldest first."""
    chain: list[Image] = []
    seen: set[str] = set()
    current = session.get(Image, image_id)
    if current is None:
        raise HTTPException(404, "image not found")
    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        current = session.get(Image, current.parent_id) if current.parent_id else None
    return [_image_out(i) for i in reversed(chain)]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
