"""An adapter that costs nothing and needs no network.

It exists so the whole product — API, queue, worker, SSE, library, lineage — can be
run and tested end to end without spending money or reaching a cloud. The image it
returns is a deterministic gradient derived from the prompt, so the same prompt always
produces the same picture and a changed prompt visibly changes it.

This is a development tool, not a model.
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
import zlib

from ..manifest import Manifest, load_manifest
from ..parts import Request, TextPart, split_parts
from .base import GeneratedImage, GenerationParams, ProgressFn, Result


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def gradient_png(width: int, height: int, base: tuple[int, int, int]) -> bytes:
    """A vertical gradient as a valid PNG, using only the standard library."""
    r0, g0, b0 = base
    raw = bytearray()
    for y in range(height):
        t = y / max(1, height - 1)
        scale = 1.0 - 0.55 * t
        pixel = bytes((int(r0 * scale), int(g0 * scale), int(b0 * scale)))
        raw.append(0)  # filter type 0 (None) for this scanline
        raw += pixel * width

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def _colour_for(seed: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    # Bias upward so the result is a legible colour rather than near-black.
    return tuple(90 + (b % 140) for b in digest[:3])  # type: ignore[return-value]


class EchoAdapter:
    """Returns a generated-looking image without calling anything."""

    def __init__(self, manifest: Manifest | None = None, *, latency_s: float | None = None) -> None:
        self.manifest = manifest or load_manifest("gpt-image-2")
        if latency_s is None:
            latency_s = float(os.environ.get("EMULSION_ECHO_LATENCY_S", "0.6"))
        self.latency_s = latency_s

    def submit(
        self,
        request: Request,
        params: GenerationParams,
        *,
        blobs: dict[str, bytes] | None = None,
        on_progress: ProgressFn | None = None,
    ) -> Result:
        kept, dropped = split_parts(request, self.manifest)
        prompt = " ".join(p.text for p in kept if isinstance(p, TextPart))

        images: list[GeneratedImage] = []
        for index in range(params.n):
            if on_progress:
                on_progress(f"rendering candidate {index + 1} of {params.n}")
            # Stand in for real generation latency so progress streaming is observable.
            time.sleep(self.latency_s)
            data = gradient_png(params.width, params.height, _colour_for(f"{prompt}:{index}"))
            images.append(
                GeneratedImage(
                    data=data,
                    width=params.width,
                    height=params.height,
                    content_type="image/png",
                )
            )

        # Token counts follow the real model's observed scaling closely enough to keep
        # the cost column meaningful in development.
        output_tokens = max(1, round(params.width * params.height / 6200)) * params.n
        return Result(
            images=images,
            dropped=dropped,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=output_tokens,
        )
