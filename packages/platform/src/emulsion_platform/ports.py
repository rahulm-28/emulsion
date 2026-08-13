"""The entire portability surface: three protocols.

M0 §8 is emphatic that this list stays at three. Everything else in the system is
Postgres, containers and HTTP, which run unchanged anywhere. A fourth protocol needs
a spec amendment, because a generic cloud abstraction layer is the most reliable way
to make this codebase worse.

Azure implementations land in M1/M3. The local ones in `local.py` are what makes
`docker compose`-free development possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    """Where image bytes live. Callers hand out `signed_url`s; they never proxy bytes."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def signed_url(self, key: str, ttl_seconds: int = 3600) -> str: ...

    def delete(self, key: str) -> None: ...


@dataclass(frozen=True)
class Lease:
    """A dequeued message plus the receipt needed to ack it."""

    receipt: str
    body: dict


@runtime_checkable
class Queue(Protocol):
    """At-least-once delivery with a visibility lease.

    Not ack-ing returns the message to the queue when the lease expires — that is the
    crash-safety story for a worker that dies mid-generation.
    """

    def enqueue(self, body: dict) -> str: ...

    def dequeue(self, lease_seconds: int = 900) -> Lease | None: ...

    def ack(self, receipt: str) -> None: ...


@runtime_checkable
class SecretStore(Protocol):
    """Long-lived secrets. In this system that means users' BYOK keys and nothing else.

    Implementations must never log a value (invariant 6). Redaction belongs at the
    logger, not at each call site.
    """

    def get(self, name: str) -> str | None: ...

    def put(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...
