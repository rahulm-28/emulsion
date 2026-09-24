"""External images become durable, private lineage roots without a model call."""

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
import pytest
from emulsion_api import app, main
from emulsion_db import ImageUpload, session_scope, utcnow
from emulsion_imaging import Rect, outside_difference, to_array
from emulsion_platform import AuthError, Principal
from emulsion_worker import process_once
from emulsion_worker.imports import staging_path
from fastapi.testclient import TestClient
from PIL import Image


class TestIdentity:
    requires_token = True

    def authenticate(self, token):
        if not token:
            raise AuthError("no token")
        return Principal(subject=f"upload-test-{token}")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_identity", TestIdentity())
    with TestClient(app, headers={"Authorization": "Bearer alice"}) as client:
        yield client


def picture(fmt="PNG", size=(1024, 1024)):
    output = io.BytesIO()
    Image.new("RGB", size, (245, 240, 235)).save(output, format=fmt)
    return output.getvalue()


def intent(client, data, **kwargs):
    response = client.post(
        "/v1/uploads", json={"filename": "diagram.png", "size_bytes": len(data), **kwargs}
    )
    assert response.status_code == 201, response.text
    return response.json()


def complete(client, upload):
    response = client.post(f"/v1/uploads/{upload['id']}/complete")
    assert response.status_code == 202, response.text
    return response.json()


def finish(client, job):
    for _ in range(100):
        current = client.get(f"/v1/jobs/{job['id']}").json()
        if current["status"] in {"failed", "succeeded"}:
            return current
        assert process_once()
    raise AssertionError("import never finished")


def import_image(client, data, **kwargs):
    upload = intent(client, data, **kwargs)
    assert client.put(upload["upload_url"], content=data).status_code == 204
    return upload, finish(client, complete(client, upload))


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_import_is_a_free_job_with_derivatives_and_history(client, monkeypatch, fmt):
    def no_model(*args, **kwargs):
        raise AssertionError("an import must not call a provider")

    monkeypatch.setattr("emulsion_worker.runner.get_adapter", no_model)
    upload, job = import_image(client, picture(fmt))
    assert job["status"] == "succeeded", job
    assert job["kind"] == "upload"
    assert job["cost_usd"] == job["output_tokens"] == 0
    image = job["images"][0]
    assert image["model_id"] == "upload"
    assert image["prompt"] == ""  # filename never becomes a model instruction
    assert image["parent_id"] is None
    assert client.get(image["url"]).content.startswith(b"\x89PNG")
    for url in (image["viewer_url"], image["gallery_url"]):
        assert client.get(url).status_code == 200
    assert not staging_path(upload["id"]).exists()
    history = client.get(f"/v1/sessions/{job['session_id']}/jobs").json()
    assert history[0]["images"][0]["id"] == image["id"]


def test_duplicate_completion_returns_same_job_even_after_ingest(client):
    data = picture()
    upload = intent(client, data)
    assert client.put(upload["upload_url"], content=data).status_code == 204
    first = complete(client, upload)
    assert first["status"] == "queued"
    assert complete(client, upload)["id"] == first["id"]
    finish(client, first)
    assert complete(client, upload)["id"] == first["id"]
    assert client.put(upload["upload_url"], content=data).status_code == 409


def test_concurrent_completion_creates_one_job(client):
    data = picture()
    upload = intent(client, data)
    assert client.put(upload["upload_url"], content=data).status_code == 204
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = list(pool.map(lambda _: complete(client, upload), range(3)))
    assert len({job["id"] for job in jobs}) == 1


def test_anonymous_uploads_are_rejected(client):
    assert (
        client.post(
            "/v1/uploads",
            headers={"Authorization": ""},
            json={"filename": "image.png", "size_bytes": 100},
        ).status_code
        == 401
    )


def test_filenames_are_not_learned_as_constraints(client):
    for index in range(3):
        import_image(client, picture(size=(10, 10)), filename=f"diagram {index}, no gridlines.png")
    suggestions = client.get("/v1/styles/suggestions").json()
    assert all("gridlines" not in suggestion["text"] for suggestion in suggestions)


def test_upload_and_completion_are_owner_scoped(client):
    data = picture()
    upload = intent(client, data)
    bob = {"Authorization": "Bearer bob"}
    assert client.put(upload["upload_url"], content=data, headers=bob).status_code == 404
    assert client.post(f"/v1/uploads/{upload['id']}/complete", headers=bob).status_code == 404
    assert client.put(upload["upload_url"], content=data).status_code == 204
    job = finish(client, complete(client, upload))
    assert client.get(f"/v1/images/{job['images'][0]['id']}", headers=bob).status_code == 404
    assert (
        client.post(
            "/v1/uploads",
            headers=bob,
            json={"filename": "x.png", "size_bytes": 10, "session_id": job["session_id"]},
        ).status_code
        == 404
    )


def test_expiry_prevents_put_and_completion(client):
    upload = intent(client, picture())
    with session_scope() as session:
        session.get(ImageUpload, upload["id"]).expires_at = utcnow() - timedelta(seconds=1)
    assert client.put(upload["upload_url"], content=picture()).status_code == 410
    assert client.post(f"/v1/uploads/{upload['id']}/complete").status_code == 410


def test_upload_cannot_complete_before_bytes_arrive(client):
    upload = intent(client, picture())
    assert client.post(f"/v1/uploads/{upload['id']}/complete").status_code == 409


def test_failed_transfer_can_be_retried_and_does_not_publish_partial_bytes(client):
    data = picture()
    upload = intent(client, data)
    assert client.put(upload["upload_url"], content=data[:-1]).status_code == 400
    assert not staging_path(upload["id"]).exists()
    assert client.put(upload["upload_url"], content=data).status_code == 204


def test_chunked_body_cannot_exceed_intent_limit(client):
    upload = intent(client, b"123")
    response = client.put(upload["upload_url"], content=iter([b"12", b"345"]))
    assert response.status_code == 413
    assert not staging_path(upload["id"]).exists()
    assert not staging_path(upload["id"]).with_suffix(".part").exists()


@pytest.mark.parametrize("size", [0, 50 * 1024 * 1024 + 1])
def test_invalid_declared_size_is_rejected(client, size):
    assert (
        client.post("/v1/uploads", json={"filename": "huge.png", "size_bytes": size}).status_code
        == 422
    )


def test_fake_image_fails_in_worker_and_removes_staged_file(client):
    upload, job = import_image(client, b"<svg>not a supported image</svg>")
    assert job["status"] == "failed"
    assert "could not be read" in job["error"]
    assert job["images"] == []
    assert not staging_path(upload["id"]).exists()


def test_import_then_conversational_and_region_edits_keep_lineage(client):
    _, root = import_image(client, picture(size=(1600, 1200)))
    original = root["images"][0]
    conversation = root["session_id"]
    edit = client.post(
        "/v1/jobs", json={"prompt": "make the title bigger", "session_id": conversation}
    ).json()
    assert edit["parent_image_id"] == original["id"]
    assert finish(client, edit)["status"] == "succeeded"
    region = client.post(
        "/v1/jobs",
        json={
            "prompt": "add a blue box",
            "session_id": conversation,
            "parent_image_id": original["id"],
            "region": {"left": 400, "top": 200, "right": 1200, "bottom": 1000},
        },
    ).json()
    done = finish(client, region)
    assert done["status"] == "succeeded", done
    result = done["images"][0]
    lineage = client.get(f"/v1/images/{result['id']}/lineage").json()
    assert [x["id"] for x in lineage] == [original["id"], result["id"]]
    before = to_array(client.get(original["url"]).content)
    after = to_array(client.get(result["url"]).content)
    from emulsion_providers import load_manifest
    from emulsion_worker.regions import prepare

    request, _, _ = prepare(
        client.get(original["url"]).content,
        Rect(400, 200, 1200, 1000),
        load_manifest("gpt-image-2"),
    )
    assert np.any(before != after)
    assert outside_difference(before, after, request.rect) == 0
