"""Image imports use the same worker, events, storage, and lineage as generations."""

from emulsion_db import ImageUpload, Job, JobStatus, session_scope, utcnow
from emulsion_imaging.ingest import normalise_upload
from sqlalchemy import select

from .runtime import settings


def staging_path(upload_id: str):
    # Database-generated IDs only. Staging stays outside the publicly served blob root.
    if len(upload_id) != 32 or any(c not in "0123456789abcdef" for c in upload_id):
        raise ValueError("invalid upload id")
    return settings().data_dir / "uploads" / upload_id


def process_import(job_id: str) -> None:
    from .runner import _fail, emit, store_image

    path = None
    try:
        with session_scope() as session:
            job = session.get(Job, job_id)
            upload = session.execute(
                select(ImageUpload).where(ImageUpload.job_id == job_id)
            ).scalar_one()
            if job is None or upload.owner_id != job.owner_id:
                raise ValueError("Upload is unavailable.")
            path = staging_path(upload.id)
        emit(job_id, "progress", "validating uploaded image")
        image = normalise_upload(path.read_bytes())
        if image.flattened_alpha:
            emit(job_id, "warning", "Transparent areas were placed on white for editing.")
        emit(job_id, "progress", "preparing image previews")
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            store_image(
                session,
                job=job,
                data=image.data,
                content_type="image/png",
                width=image.width,
                height=image.height,
                # A filename is not an instruction and must never reach refine().
                prompt="",
                model_id="upload",
            )
            job.status = JobStatus.SUCCEEDED
            job.input_tokens = job.output_tokens = 0
            job.cost_usd = 0.0
            job.finished_at = utcnow()
        emit(job_id, "status", "succeeded")
    except ValueError as exc:
        _fail(job_id, str(exc))
    except Exception:
        _fail(job_id, "Could not prepare this image. Please upload it again.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
