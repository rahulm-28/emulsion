"""One user must never see another user's work.

The dev identity returns a single principal, so these tests swap the app's identity
provider for one keyed on a header. That is the only way to get two distinct users
through the same in-process app — and without it, every scoping bug in the API would
pass the rest of the suite silently, which is exactly what happened while this was
being written.
"""

import pytest
from emulsion_api import main
from emulsion_platform import AuthError, Principal
from emulsion_worker import process_once
from fastapi.testclient import TestClient


class HeaderIdentity:
    """Whatever the bearer token says, that is who you are. Tests only."""

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise AuthError("no token")
        return Principal(subject=token, email=f"{token}@test", display_name=token)

    @property
    def requires_token(self) -> bool:
        return True


@pytest.fixture
def two_users(monkeypatch):
    monkeypatch.setattr(main, "_identity", HeaderIdentity())
    with TestClient(main.app) as client:
        alice = {"Authorization": "Bearer alice"}
        bob = {"Authorization": "Bearer bob"}
        yield client, alice, bob


def make_job(client, headers, prompt="secret diagram"):
    response = client.post("/v1/jobs", json={"prompt": prompt, "size": "1k"}, headers=headers)
    assert response.status_code == 202, response.text
    job = response.json()
    for _ in range(20):
        current = client.get(f"/v1/jobs/{job['id']}", headers=headers).json()
        if current["status"] in {"succeeded", "failed"}:
            return current
        assert process_once() is True
    raise AssertionError("job never finished")


def test_an_anonymous_caller_is_rejected(two_users):
    client, _, _ = two_users
    assert client.get("/v1/sessions").status_code == 401
    assert client.post("/v1/jobs", json={"prompt": "x", "size": "1k"}).status_code == 401


def test_listings_are_scoped(two_users):
    client, alice, bob = two_users
    make_job(client, alice, prompt="alice only")

    assert client.get("/v1/sessions", headers=bob).json() == []
    assert client.get("/v1/jobs", headers=bob).json() == []
    assert client.get("/v1/images", headers=bob).json() == []
    assert len(client.get("/v1/sessions", headers=alice).json()) == 1


def test_another_users_job_is_not_readable(two_users):
    client, alice, bob = two_users
    job = make_job(client, alice)
    assert client.get(f"/v1/jobs/{job['id']}", headers=bob).status_code == 404


def test_another_users_image_is_not_readable(two_users):
    client, alice, bob = two_users
    image = make_job(client, alice)["images"][0]
    for path in (
        f"/v1/images/{image['id']}",
        f"/v1/images/{image['id']}/lineage",
        f"/v1/images/{image['id']}/content",
    ):
        assert client.get(path, headers=bob).status_code == 404, path


def test_another_users_event_stream_is_not_readable(two_users):
    """Regression: this endpoint was unscoped, and its terminal frame carries the whole
    job including image URLs."""
    client, alice, bob = two_users
    job = make_job(client, alice)
    assert client.get(f"/v1/jobs/{job['id']}/events", headers=bob).status_code == 404


def test_another_users_session_cannot_be_read_renamed_or_deleted(two_users):
    client, alice, bob = two_users
    job = make_job(client, alice)
    session_id = job["session_id"]

    assert client.get(f"/v1/sessions/{session_id}/jobs", headers=bob).status_code == 404
    assert (
        client.patch(
            f"/v1/sessions/{session_id}", json={"title": "hijacked"}, headers=bob
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/sessions/{session_id}", headers=bob).status_code == 404
    # Alice's session survived all of that.
    assert client.get(f"/v1/sessions/{session_id}/jobs", headers=alice).status_code == 200


def test_a_job_cannot_be_attached_to_another_users_session(two_users):
    client, alice, bob = two_users
    job = make_job(client, alice)
    response = client.post(
        "/v1/jobs",
        json={"prompt": "x", "size": "1k", "session_id": job["session_id"]},
        headers=bob,
    )
    assert response.status_code == 404


def test_another_users_image_cannot_be_used_as_a_parent(two_users):
    client, alice, bob = two_users
    image = make_job(client, alice)["images"][0]
    response = client.post(
        "/v1/jobs",
        json={"prompt": "x", "size": "1k", "parent_image_id": image["id"]},
        headers=bob,
    )
    assert response.status_code == 404


def test_styles_are_scoped(two_users):
    client, alice, bob = two_users
    created = client.post("/v1/styles", json={"name": "Alice deck"}, headers=alice).json()

    assert client.get("/v1/styles", headers=bob).json() == []
    assert (
        client.patch(
            f"/v1/styles/{created['id']}", json={"name": "stolen"}, headers=bob
        ).status_code
        == 404
    )
    assert client.delete(f"/v1/styles/{created['id']}", headers=bob).status_code == 404
    assert len(client.get("/v1/styles", headers=alice).json()) == 1


def test_suggestions_are_built_only_from_your_own_prompts(two_users):
    client, alice, bob = two_users
    for index in range(4):
        client.post(
            "/v1/jobs",
            json={"prompt": f"chart {index}, no gridlines", "size": "1k"},
            headers=alice,
        )
    assert client.get("/v1/styles/suggestions", headers=bob).json() == []
    texts = [s["text"] for s in client.get("/v1/styles/suggestions", headers=alice).json()]
    assert "no gridlines" in texts


def test_an_idempotency_key_does_not_cross_users(two_users):
    """Two people can use the same key without one receiving the other's job."""
    client, alice, bob = two_users
    key = {"Idempotency-Key": "same-key"}
    first = client.post(
        "/v1/jobs", json={"prompt": "alice", "size": "1k"}, headers={**alice, **key}
    ).json()
    second = client.post("/v1/jobs", json={"prompt": "bob", "size": "1k"}, headers={**bob, **key})
    assert second.status_code == 202
    assert second.json()["id"] != first["id"]
    assert second.json()["prompt"] == "bob"
