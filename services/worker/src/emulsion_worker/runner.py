"""Execute one job to completion.

The worker has no HTTP request above it, so it may take the 40–300 seconds a real 4K
generation needs (invariant 1). Progress is written to `job_events`; the API's SSE
endpoint is a tail of that table.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import replace

from emulsion_db import HouseStyle as HouseStyleRow
from emulsion_db import Image, Job, JobEvent, JobStatus, new_id, session_scope, utcnow
from emulsion_engine import HouseStyle, JobSpec, refine, run
from emulsion_imaging import build_pyramid, rank_diagrams, score_diagram, to_array, to_png
from emulsion_providers import cost_usd, load_manifest
from emulsion_providers.adapters import get_adapter
from emulsion_providers.adapters.base import ProviderError

from .regions import CROP_BLOB_ID, RegionTooSmall, finish, parse_region, prepare
from .runtime import blob_store, queue, settings

log = logging.getLogger("emulsion.worker")


def emit(job_id: str, kind: str, message: str) -> None:
    """Append a progress event. Its own transaction so it is visible immediately."""
    with session_scope() as session:
        seq = (
            session.query(JobEvent).filter(JobEvent.job_id == job_id).count()  # noqa: E501
        )
        session.add(JobEvent(job_id=job_id, seq=seq, kind=kind, message=message))


def _load_blobs(spec: JobSpec) -> dict[str, bytes]:
    store = blob_store()
    keys = [*spec.source_blob_ids, *spec.reference_blob_ids]
    return {key: store.get(key) for key in keys}


def store_image(
    session,  # noqa: ANN001 - Session
    *,
    job: Job,
    data: bytes,
    content_type: str,
    width: int,
    height: int,
    prompt: str,
    model_id: str,
) -> Image:
    """Write the archival bytes plus the derivative pyramid, and record the row.

    The pyramid is built here rather than lazily on first view because the worker
    already has the bytes in memory and is the only process with no request timeout
    above it. Resizing a 13 MB PNG inside an API handler is how a page load becomes a
    30-second wait.
    """
    image_id = new_id()
    store = blob_store()

    archival_key = f"images/{image_id}.png"
    keys: dict[str, str] = {}
    for derivative in build_pyramid(data):
        if derivative.name == "archival":
            store.put(archival_key, derivative.data, content_type)
            continue
        key = f"images/{image_id}.{derivative.name}.webp"
        store.put(key, derivative.data, derivative.content_type)
        keys[derivative.name] = key

    image = Image(
        id=image_id,
        job_id=job.id,
        owner_id=job.owner_id,
        parent_id=job.parent_image_id,
        blob_key=archival_key,
        viewer_key=keys.get("viewer"),
        gallery_key=keys.get("gallery"),
        content_type=content_type,
        width=width,
        height=height,
        size_bytes=len(data),
        model_id=model_id,
        prompt=prompt,
    )
    session.add(image)
    return image


Stored = tuple[bytes, str, int, int]


def _rank_generated(
    job_id: str,
    stored: list[Stored],
    progress: Callable[[str], None],
) -> list[Stored]:
    """Order K candidates best first, and say why in the event trail.

    The crop-composite path already ranks, because it has the parent to compare
    against. A plain generation has no reference, so without this K candidates come
    back and the person picks by eye — which is the model's job done twice and the
    layer above it doing nothing.

    Ordering rather than discarding: the losers stay in the library, because the score
    is a heuristic prior and being overruled is a normal outcome.
    """
    try:
        scores = [score_diagram(to_array(data)) for data, *_ in stored]
    except Exception:  # noqa: BLE001 - a scoring failure must not lose the images
        log.exception("job %s: candidate scoring failed; keeping generation order", job_id)
        emit(job_id, "warning", "could not rank candidates; showing them in generation order")
        return stored

    order = rank_diagrams(scores)
    progress(f"ranked {len(stored)} candidates; best {scores[order[0]].explain()}")
    for position, index in enumerate(order[1:], start=2):
        emit(job_id, "progress", f"#{position}: {scores[index].explain()}")
    return [stored[i] for i in order]


def process_job(job_id: str) -> None:
    """Run a single job. Terminal state is always reached, success or failure."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            log.warning("job %s vanished before it ran", job_id)
            return
        if job.status in JobStatus.TERMINAL:
            return
        job.status = JobStatus.RUNNING
        job.started_at = utcnow()
        region = parse_region(job.region)
        parent_key = next(iter(_parent_blob_keys(session, job)), None)
        prompt = job.prompt
        if parent_key is not None and region is None:
            # A conversational edit. The model regenerates the whole image on every
            # edit call, so sending only "make the title bigger" re-rolls everything
            # that was already right against a prompt that no longer describes the
            # diagram. The parent's prompt is what makes it an edit rather than a new
            # picture that happens to have a bigger title.
            parent = session.get(Image, job.parent_image_id) if job.parent_image_id else None
            if parent is not None and parent.prompt:
                prompt = refine(parent.prompt, job.prompt)
        spec = JobSpec(
            prompt=prompt,
            model_id=job.model_id,
            size=job.size,
            n=job.n,
            source_blob_ids=[parent_key] if parent_key else [],
            style=_house_style(session, job),
            consistency_with=_previous_title(session, job),
        )

    emit(job_id, "status", "running")
    progress = lambda message: emit(job_id, "progress", message)  # noqa: E731

    parent_array = None
    plan = None

    try:
        manifest = load_manifest(spec.model_id)
        blobs = _load_blobs(spec)

        if region is not None:
            if parent_key is None:
                raise ValueError("a region edit needs a parent image")
            request, parent_array, plan = prepare(blobs[parent_key], region, manifest)
            progress(request.describe())
            if not plan.is_clean():
                # Said before the money is spent, not after the seam is visible.
                emit(
                    job_id,
                    "warning",
                    f"only {request.gutter_fraction:.0%} of the region boundary sits in "
                    f"whitespace; expect a visible seam",
                )
            # The crop is what the model sees, so it is what the size must describe.
            spec = replace(
                spec,
                size=f"{request.width}x{request.height}",
                source_blob_ids=[CROP_BLOB_ID],
            )
            blobs = {CROP_BLOB_ID: request.crop_png}

        adapter = get_adapter(settings().adapter)
        result = run(spec, adapter, blobs=blobs, on_progress=progress)
    except RegionTooSmall as exc:
        _fail(job_id, str(exc))
        return
    except (ProviderError, ValueError) as exc:
        _fail(job_id, str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - a worker must always land somewhere
        log.exception("job %s failed unexpectedly", job_id)
        _fail(job_id, f"unexpected error: {exc}")
        return

    if plan is not None:
        try:
            winner, ranked = finish(parent_array, plan, [i.data for i in result.images])
        except ValueError as exc:
            _fail(job_id, str(exc))
            return
        progress(f"ranked {len(ranked)} candidate(s); best {winner.score.explain()}")
        composited = to_png(winner.image)
        stored = [(composited, "image/png", winner.image.shape[1], winner.image.shape[0])]
    else:
        stored = [(g.data, g.content_type, g.width, g.height) for g in result.images]
        if len(stored) > 1:
            stored = _rank_generated(job_id, stored, progress)

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        for data, content_type, width, height in stored:
            store_image(
                session,
                job=job,
                data=data,
                content_type=content_type,
                width=width,
                height=height,
                prompt=job.prompt,
                model_id=spec.model_id,
            )
        job.input_tokens = result.input_tokens
        job.output_tokens = result.output_tokens
        job.cost_usd = cost_usd(manifest, result.input_tokens, result.output_tokens)
        job.dropped_parts = (
            json.dumps([d.model_dump() for d in result.dropped]) if result.dropped else None
        )
        job.status = JobStatus.SUCCEEDED
        job.finished_at = utcnow()

    if result.dropped:
        # Invariant 7: never silent.
        for dropped in result.dropped:
            emit(job_id, "warning", f"dropped {dropped.kind}: {dropped.reason}")
    emit(job_id, "status", "succeeded")


def _house_style(session, job: Job) -> HouseStyle | None:  # noqa: ANN001
    """The session's house style, as the engine's plain dataclass.

    The ORM row stays in the database layer; the engine sees a frozen dataclass with no
    session attached to it (invariant 2).
    """
    chat = job.session
    if chat is None or not chat.style_id:
        return None
    row = session.get(HouseStyleRow, chat.style_id)
    if row is None:
        return None
    return HouseStyle(
        name=row.name,
        legend=json.loads(row.legend_json or "{}"),
        rules=tuple(json.loads(row.rules_json or "[]")),
        layout=row.layout or "",
        style_words=tuple(json.loads(row.style_words_json or "[]")),
    )


def _previous_title(session, job: Job) -> str:  # noqa: ANN001
    """The title of the last diagram in this session, when the user asked for a deck.

    Opt-in per session: linking every picture to the previous one is right for a deck
    and wrong for a scratch pad, and only the user knows which this is.
    """
    chat = job.session
    if chat is None or not chat.link_consistency:
        return ""
    earlier = [j for j in chat.jobs if j.id != job.id and j.status == JobStatus.SUCCEEDED]
    return earlier[-1].prompt[:80] if earlier else ""


def _parent_blob_keys(session, job: Job) -> list[str]:  # noqa: ANN001
    """The parent image's blob key, when this job edits an existing image."""
    if not job.parent_image_id:
        return []
    parent = session.get(Image, job.parent_image_id)
    return [parent.blob_key] if parent else []


def _fail(job_id: str, message: str) -> None:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = message
            job.finished_at = utcnow()
    emit(job_id, "error", message)
    emit(job_id, "status", "failed")


def process_once() -> bool:
    """Claim and run at most one job. Returns True if work was done."""
    lease = queue().dequeue(lease_seconds=settings().lease_seconds)
    if lease is None:
        return False
    job_id = lease.body.get("job_id")
    try:
        if job_id:
            process_job(job_id)
    finally:
        # ponytail: acked unconditionally, so a job that crashes the worker mid-flight
        # is marked failed rather than retried. Real retry needs a poison-message count
        # and a dead-letter path; the `attempts` column is already there for it.
        queue().ack(lease.receipt)
    return True


def run_forever(stop=None) -> None:  # noqa: ANN001 - threading.Event | None
    """Poll until told to stop. The worker entrypoint in both inline and job mode."""
    interval = settings().poll_interval_s
    log.info("worker polling every %.1fs (adapter=%s)", interval, settings().adapter)
    while stop is None or not stop.is_set():
        try:
            if not process_once():
                time.sleep(interval)
        except Exception:  # noqa: BLE001 - the loop must survive a bad job
            log.exception("worker loop error")
            time.sleep(interval)
