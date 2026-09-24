"""Structured authoring survives storage, worker execution, and later edits."""

from copy import deepcopy
from uuid import uuid4

import pytest
from emulsion_api import app, main
from emulsion_db import Base, Job, JobSpecification, QueueMessage, make_engine, session_scope
from emulsion_providers.adapters.echo import EchoAdapter
from emulsion_providers.parts import TextPart
from emulsion_worker import process_once, runner
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

DIAGRAM = {
    "title": "Order pipeline",
    "key_message": "Queueing isolates the API from slow work",
    "components": [
        {"name": "API", "emphasis": "dominant", "items": ["Validate"]},
        {"name": "Queue"},
    ],
    "connections": [{"source": "API", "target": "Queue", "label": "enqueue"}],
    "callouts": [{"anchor": "Queue", "text": "Workers claim jobs independently"}],
}


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client
        while process_once():
            pass


@pytest.fixture
def prompts(monkeypatch):
    captured = []

    class Capture(EchoAdapter):
        def submit(self, request, params, **kwargs):
            captured.append("\n".join(p.text for p in request.parts if isinstance(p, TextPart)))
            return super().submit(request, params, **kwargs)

    monkeypatch.setattr(runner, "get_adapter", lambda _: Capture(latency_s=0))
    return captured


def submit(client, **kwargs):
    response = client.post(
        "/v1/jobs", json={"prompt": "Use charcoal labels", "diagram": DIAGRAM} | kwargs
    )
    assert response.status_code == 202, response.text
    return response.json()


def done(client, job):
    for _ in range(100):
        current = client.get(f"/v1/jobs/{job['id']}").json()
        if current["status"] in {"succeeded", "failed"}:
            assert current["status"] == "succeeded", current["error"]
            return current
        assert process_once()
    pytest.fail("job did not finish")


def counts():
    with session_scope() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(table))
            for table in (Job, QueueMessage, JobSpecification)
        )


def test_preview_is_free_and_includes_structure_and_instructions(client):
    before = counts()
    response = client.post(
        "/v1/diagrams/preview", json={"diagram": DIAGRAM, "prompt": "Use charcoal labels"}
    )
    assert response.status_code == 200
    text = response.json()["text"]
    for expected in (
        "Order pipeline",
        "API",
        "Queue",
        "enqueue",
        "Workers claim",
        "Use charcoal labels",
        "largest and central",
        "Validate",
    ):
        assert expected in text
    assert counts() == before


def test_structure_survives_worker_and_history(client, prompts):
    job = submit(client)
    finished = done(client, job)
    assert finished["diagram"] == job["diagram"]
    assert "API -> Queue" in prompts[-1]
    assert "Use charcoal labels" in prompts[-1]
    history = client.get(f"/v1/sessions/{job['session_id']}/jobs").json()
    assert history[0]["diagram"]["callouts"][0]["anchor"] == "Queue"


def test_edits_keep_structure_and_all_previous_instructions(client, prompts):
    root = done(client, submit(client))
    first = done(
        client,
        submit(
            client,
            diagram=None,
            mode="edit",
            session_id=root["session_id"],
            prompt="Make the title larger",
        ),
    )
    second = done(
        client,
        submit(
            client,
            diagram=None,
            mode="edit",
            session_id=root["session_id"],
            prompt="Move the queue to the right",
        ),
    )
    assert first["kind"] == second["kind"] == "edit"
    assert second["diagram"] == root["diagram"]
    assert second["parent_image_id"] == first["images"][0]["id"]
    for instruction in (
        "Use charcoal labels",
        "Make the title larger",
        "Move the queue to the right",
        "Workers claim",
    ):
        assert instruction in prompts[-1]


def test_region_edits_do_not_render_the_entire_saved_diagram_in_the_crop(client, prompts):
    root = done(client, submit(client, size="2k"))
    result = done(
        client,
        submit(
            client,
            diagram=None,
            parent_image_id=root["images"][0]["id"],
            prompt="Make this box blue",
            region={"left": 100, "top": 100, "right": 1000, "bottom": 1000},
        ),
    )
    assert result["diagram"] == root["diagram"]
    assert "Workers claim jobs independently" not in prompts[-1]
    assert "Make this box blue" in prompts[-1]
    assert "Use charcoal labels" in result["images"][0]["prompt"]


def test_new_image_mode_overrides_edit_intent(client):
    root = done(client, submit(client))
    fresh = submit(
        client,
        session_id=root["session_id"],
        prompt="Make the title larger",
        mode="generate",
        diagram=None,
    )
    assert fresh["parent_image_id"] is None
    assert fresh["diagram"] is None
    assert fresh["kind"] == "generate"


def test_edit_latest_requires_an_image_without_leaving_partial_work(client):
    before = counts()
    response = client.post("/v1/jobs", json={"prompt": "edit it", "mode": "edit"})
    assert response.status_code == 422
    assert counts() == before


@pytest.mark.parametrize(
    "patch",
    [
        {"title": "  "},
        {"components": [{"name": "API"}, {"name": " API "}]},
        {"connections": [{"source": "API", "target": "Missing"}]},
        {"callouts": [{"anchor": "Missing", "text": "No orphan annotations"}]},
        {"callouts": [{"anchor": "API", "text": "  "}]},
        {"components": [{"name": str(i)} for i in range(41)]},
    ],
)
def test_invalid_structure_is_rejected_before_work_is_created(client, patch):
    before = counts()
    invalid = deepcopy(DIAGRAM) | patch
    for path, body in (
        ("/v1/jobs", {"prompt": "x", "diagram": invalid}),
        ("/v1/diagrams/preview", {"diagram": invalid}),
    ):
        assert client.post(path, json=body).status_code == 422
    assert counts() == before


def test_first_job_gets_selected_style_before_worker_runs(client, prompts):
    style = client.post(
        "/v1/styles", json={"name": "Editorial", "rules": ["Use coral separators"]}
    ).json()
    job = submit(client, style_id=style["id"], link_consistency=True)
    done(client, job)
    assert "Use coral separators" in prompts[-1]
    chat = next(s for s in client.get("/v1/sessions").json() if s["id"] == job["session_id"])
    assert chat["style_id"] == style["id"] and chat["link_consistency"] is True


def test_repeated_idempotency_key_keeps_original_snapshot_and_one_queue_entry(client):
    before = counts()
    headers = {"Idempotency-Key": str(uuid4())}
    body = {"prompt": "x", "diagram": DIAGRAM}
    first = client.post("/v1/jobs", json=body, headers=headers).json()
    retry = client.post(
        "/v1/jobs", json=body | {"diagram": DIAGRAM | {"title": "Changed"}}, headers=headers
    ).json()
    assert first["id"] == retry["id"]
    assert retry["diagram"]["title"] == "Order pipeline"
    assert counts() == tuple(n + 1 for n in before)


def test_another_users_style_cannot_be_used_for_preview_or_generation(client, monkeypatch):
    from emulsion_platform import Principal

    class Identity:
        requires_token = True

        def authenticate(self, token):
            return Principal(subject=token, email="", display_name="")

    monkeypatch.setattr(main, "_identity", Identity())
    owner = {"Authorization": f"Bearer {uuid4()}"}
    other = {"Authorization": f"Bearer {uuid4()}"}
    style = client.post("/v1/styles", json={"name": "Private"}, headers=owner).json()
    for path in ("/v1/jobs", "/v1/diagrams/preview"):
        response = client.post(
            path, json={"prompt": "x", "diagram": DIAGRAM, "style_id": style["id"]}, headers=other
        )
        assert response.status_code == 404


def test_additive_schema_preserves_old_jobs(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    tables = [
        table for table in Base.metadata.tables.values() if table.name != "job_specifications"
    ]
    Base.metadata.create_all(engine, tables=tables)
    # A real legacy row with its account, using the existing schema only.
    from emulsion_db import User

    with Session(engine) as session:
        user = User(subject="legacy")
        session.add(user)
        session.flush()
        session.add(
            Job(
                id="old-job",
                owner_id=user.id,
                model_id="gpt-image-2",
                prompt="old prompt",
                size="1k",
            )
        )
        session.commit()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        old = session.get(Job, "old-job")
        assert old.prompt == "old prompt" and old.specification is None
    engine.dispose()


def test_dates_include_timezone_for_correct_local_history_grouping(client):
    job = done(client, submit(client))
    session = next(s for s in client.get("/v1/sessions").json() if s["id"] == job["session_id"])
    for value in (
        job["created_at"],
        job["started_at"],
        job["finished_at"],
        job["images"][0]["created_at"],
        job["events"][0]["created_at"],
        session["updated_at"],
    ):
        assert value.endswith("+00:00")
