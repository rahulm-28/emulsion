"""A `Queue` implementation over the database.

Satisfies emulsion_platform.ports.Queue. Delivery is at-least-once with a visibility
lease: a worker that dies mid-generation loses its lease and the job is retried rather
than lost.
"""

from __future__ import annotations

import json
from datetime import timedelta

from emulsion_platform.ports import Lease
from sqlalchemy import select, update

from .models import QueueMessage, utcnow


class DbQueue:
    """Queue backed by the `queue_messages` table."""

    def __init__(self, session_factory) -> None:  # noqa: ANN001 - sessionmaker[Session]
        self._session_factory = session_factory

    def enqueue(self, body: dict) -> str:
        with self._session_factory() as session:
            message = QueueMessage(body=json.dumps(body))
            session.add(message)
            session.commit()
            return message.id

    def dequeue(self, lease_seconds: int = 900) -> Lease | None:
        """Claim the oldest visible message, or return None."""
        now = utcnow()
        with self._session_factory() as session:
            candidate = session.execute(
                select(QueueMessage)
                .where((QueueMessage.locked_until.is_(None)) | (QueueMessage.locked_until < now))
                .order_by(QueueMessage.created_at)
                .limit(1)
            ).scalar_one_or_none()
            if candidate is None:
                return None

            # Claim it. The WHERE clause re-checks the lease so two workers racing for
            # the same row cannot both win — the loser updates zero rows.
            claimed = session.execute(
                update(QueueMessage)
                .where(
                    QueueMessage.id == candidate.id,
                    (QueueMessage.locked_until.is_(None)) | (QueueMessage.locked_until < now),
                )
                .values(
                    locked_until=now + timedelta(seconds=lease_seconds),
                    attempts=QueueMessage.attempts + 1,
                )
            )
            session.commit()
            if claimed.rowcount != 1:
                return None
            return Lease(receipt=candidate.id, body=json.loads(candidate.body))

    def ack(self, receipt: str) -> None:
        with self._session_factory() as session:
            message = session.get(QueueMessage, receipt)
            if message is not None:
                session.delete(message)
            session.commit()

    def depth(self) -> int:
        with self._session_factory() as session:
            return session.query(QueueMessage).count()
