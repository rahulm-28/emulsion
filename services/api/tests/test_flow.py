"""End to end: submit a job, run the worker, get an image back.

Uses the echo adapter, so it costs nothing and needs no network — which is the whole
reason the echo adapter exists.
"""

import json

import pytest
from emulsion_api import app
from emulsion_worker import process_once
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def submit(client, **overrides) -> dict:
    body = {"prompt": "a wiring diagram", "size": "1k", "n": 1} | overrides
    response = client.post("/v1/jobs", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def drain(client, job_id: str, *, limit: int = 20) -> dict:
    """Run the worker until `job_id` is terminal.

    Earlier tests leave their own jobs queued, so a single `process_once()` is not
    guaranteed to pick up the one we just submitted.
    """
    for _ in range(limit):
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        assert process_once() is True, "queue drained before the job ran"
    raise AssertionError(f"job {job_id} never finished")


def test_health_reports_the_configured_adapter(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["adapter"] == "echo"


def test_models_endpoint_exposes_measured_capabilities(client):
    models = client.get("/v1/models").json()
    assert [m["id"] for m in models] == ["gpt-image-2"]
    only = models[0]
    assert only["mask_support"] == "soft"
    assert only["edit_full_regen"] is True
    assert "input_fidelity" in only["unsupported_params"]


def test_job_is_queued_not_executed_inline(client):
    """Invariant 1: POST returns before any model work happens."""
    job = submit(client)
    assert job["status"] == "queued"
    assert job["images"] == []
    assert job["finished_at"] is None


def test_worker_completes_the_job_and_stores_an_image(client):
    job = submit(client)
    done = drain(client, job["id"])

    assert done["status"] == "succeeded"
    assert len(done["images"]) == 1

    image = done["images"][0]
    assert (image["width"], image["height"]) == (1024, 1024)
    assert image["size_bytes"] > 0
    assert done["cost_usd"] > 0


def test_stored_bytes_are_a_real_png(client):
    job = submit(client)
    image = drain(client, job["id"])["images"][0]
    blob = client.get(image["url"])
    assert blob.status_code == 200
    assert blob.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_image_content_redirects_rather_than_proxying(client):
    """Invariant 4: the API hands out a URL, it does not stream bytes."""
    job = submit(client)
    image_id = drain(client, job["id"])["images"][0]["id"]
    response = client.get(f"/v1/images/{image_id}/content", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith("/_blobs/")


def test_idempotency_key_returns_the_same_job(client):
    headers = {"Idempotency-Key": "repeat-me"}
    first = client.post("/v1/jobs", json={"prompt": "one", "size": "1k"}, headers=headers)
    second = client.post("/v1/jobs", json={"prompt": "one", "size": "1k"}, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/v1/jobs").json()) >= 1


def test_bad_size_is_rejected_before_queueing(client):
    too_small = client.post("/v1/jobs", json={"prompt": "x", "size": "32x32"})
    assert too_small.status_code == 422
    assert "below min" in too_small.text

    off_grid = client.post("/v1/jobs", json={"prompt": "x", "size": "1020x640"})
    assert off_grid.status_code == 422
    assert "multiple of 16" in off_grid.text


def test_unknown_model_is_rejected(client):
    response = client.post("/v1/jobs", json={"prompt": "x", "model_id": "nope"})
    assert response.status_code == 404


def test_progress_events_stream_and_close(client):
    job = submit(client)
    drain(client, job["id"])
    with client.stream("GET", f"/v1/jobs/{job['id']}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())
    assert "event: status" in body
    assert "event: done" in body
    # The terminal frame carries the finished job, so a client needs no follow-up GET.
    payload = body.split("event: done\ndata: ")[1].splitlines()[0]
    assert json.loads(payload)["status"] == "succeeded"


def test_lineage_walks_back_to_the_root(client):
    first = submit(client, prompt="root")
    root_image = drain(client, first["id"])["images"][0]

    second = submit(client, prompt="child", parent_image_id=root_image["id"])
    child_image = drain(client, second["id"])["images"][0]

    lineage = client.get(f"/v1/images/{child_image['id']}/lineage").json()
    assert [i["id"] for i in lineage] == [root_image["id"], child_image["id"]]


def test_n_is_clamped_to_what_the_model_declares(client):
    # The manifest says 2 images per request; asking for 8 must not fabricate 8.
    job = submit(client, n=8)
    assert len(drain(client, job["id"])["images"]) == 2


# -- sessions ------------------------------------------------------------------


def test_a_first_prompt_creates_its_own_session(client):
    job = submit(client, prompt="a cutaway of a turbofan engine")
    assert job["session_id"]

    sessions = client.get("/v1/sessions").json()
    mine = next(s for s in sessions if s["id"] == job["session_id"])
    assert mine["title"] == "a cutaway of a turbofan engine"
    assert mine["job_count"] == 1


def test_long_prompts_get_a_trimmed_title(client):
    job = submit(client, prompt="word " * 60)
    sessions = client.get("/v1/sessions").json()
    title = next(s["title"] for s in sessions if s["id"] == job["session_id"])
    assert len(title) <= 49
    assert title.endswith("…")


def test_follow_up_prompts_join_the_same_session(client):
    first = submit(client, prompt="a control panel")
    second = submit(client, prompt="make it wider", session_id=first["session_id"])
    assert second["session_id"] == first["session_id"]

    jobs = client.get(f"/v1/sessions/{first['session_id']}/jobs").json()
    assert [j["prompt"] for j in jobs] == ["a control panel", "make it wider"]


def test_session_carries_a_thumbnail_and_running_cost(client):
    job = submit(client, prompt="a lighthouse cross-section")
    drain(client, job["id"])
    sessions = client.get("/v1/sessions").json()
    mine = next(s for s in sessions if s["id"] == job["session_id"])
    assert mine["image_count"] == 1
    assert mine["thumbnail_url"].startswith("/_blobs/")
    assert mine["cost_usd"] > 0


def test_sessions_are_ordered_most_recently_touched_first(client):
    older = submit(client, prompt="older conversation")
    newer = submit(client, prompt="newer conversation")
    ids = [s["id"] for s in client.get("/v1/sessions").json()]
    assert ids.index(newer["session_id"]) < ids.index(older["session_id"])


def test_session_can_be_renamed(client):
    job = submit(client, prompt="rename me")
    response = client.patch(f"/v1/sessions/{job['session_id']}", json={"title": "Turbine deck"})
    assert response.status_code == 200
    assert response.json()["title"] == "Turbine deck"


def test_deleting_a_session_removes_its_jobs(client):
    job = submit(client, prompt="temporary")
    session_id = job["session_id"]
    assert client.delete(f"/v1/sessions/{session_id}").status_code == 204
    assert client.get(f"/v1/sessions/{session_id}/jobs").status_code == 404
    assert client.get(f"/v1/jobs/{job['id']}").status_code == 404


def test_unknown_session_is_rejected(client):
    response = client.post("/v1/jobs", json={"prompt": "x", "size": "1k", "session_id": "nope"})
    assert response.status_code == 404


def test_job_exposes_its_event_trail(client):
    job = submit(client, prompt="show me the pipeline")
    done = drain(client, job["id"])
    kinds = [e["kind"] for e in done["events"]]
    messages = [e["message"] for e in done["events"]]
    assert "status" in kinds
    assert any("resolved 1024x1024" in m for m in messages)
    assert [e["seq"] for e in done["events"]] == sorted(e["seq"] for e in done["events"])
