"""Execute one job to completion.

The worker has no HTTP request above it, so it may take the 40–300 seconds a real 4K
generation needs (invariant 1). Progress is written to `job_events`; the API's SSE
endpoint is a tail of that table.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace

from emulsion_db import Image, Job, JobEvent, JobStatus, new_id, session_scope, utcnow
from emulsion_engine import JobSpec, run
from emulsion_imaging import build_pyramid, to_png
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
        spec = JobSpec(
            prompt=job.prompt,
            model_id=job.model_id,
            size=job.size,
            n=job.n,
            source_blob_ids=[parent_key] if parent_key else [],
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
