"""Bounded local storage PUTs. Production replaces this shim with signed blob URLs."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


async def receive(request: Request, path: Path, expected_bytes: int) -> None:
    if path.exists():
        raise HTTPException(409, "This upload has already been received.")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            matches = int(length) == expected_bytes
        except ValueError:
            matches = False
        if not matches:
            raise HTTPException(400, "The uploaded file size does not match. Attach it again.")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    try:
        file = partial.open("xb")
    except FileExistsError as exc:
        raise HTTPException(409, "This upload is already in progress.") from exc
    try:
        with file:
            total = 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > expected_bytes:
                    raise HTTPException(413, "The uploaded file exceeds its declared size.")
                await run_in_threadpool(file.write, chunk)
            if total != expected_bytes:
                raise HTTPException(400, "The upload was incomplete. Please attach it again.")
        # Publish without overwriting an immutable object, even if two PUTs race.
        try:
            os.link(partial, path)
        except FileExistsError as exc:
            raise HTTPException(409, "This upload has already been received.") from exc
    finally:
        partial.unlink(missing_ok=True)
