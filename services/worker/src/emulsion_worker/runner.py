"""Execute one job to completion.

The worker has no HTTP request above it, so it may take the 40–300 seconds a real 4K
generation needs (invariant 1). Progress is written to `job_events`; the API's SSE
endpoint is a tail of that table.
"""

from __future__ import annotations

import json
import logging
import time

from emulsion_db import Image, Job, JobEvent, JobStatus, new_id, session_scope, utcnow
from emulsion_engine import JobSpec, run
from emulsion_providers import cost_usd, load_manifest
from emulsion_providers.adapters import get_adapter
from emulsion_providers.adapters.base import ProviderError

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
        spec = JobSpec(
            prompt=job.prompt,
            model_id=job.model_id,
            size=job.size,
            n=job.n,
            source_blob_ids=list(_parent_blob_keys(session, job)),
        )

    emit(job_id, "status", "running")

    try:
        adapter = get_adapter(settings().adapter)
        result = run(
            spec,
            adapter,
            blobs=_load_blobs(spec),
            on_progress=lambda message: emit(job_id, "progress", message),
        )
    except (ProviderError, ValueError) as exc:
        _fail(job_id, str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - a worker must always land somewhere
        log.exception("job %s failed unexpectedly", job_id)
        _fail(job_id, f"unexpected error: {exc}")
        return

    store = blob_store()
    manifest = load_manifest(spec.model_id)

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        for generated in result.images:
            image_id = new_id()
            key = f"images/{image_id}.png"
            store.put(key, generated.data, generated.content_type)
            session.add(
                Image(
                    id=image_id,
                    job_id=job_id,
                    parent_id=job.parent_image_id,
                    blob_key=key,
                    content_type=generated.content_type,
                    width=generated.width,
                    height=generated.height,
                    size_bytes=len(generated.data),
                    model_id=spec.model_id,
                    prompt=job.prompt,
                )
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
