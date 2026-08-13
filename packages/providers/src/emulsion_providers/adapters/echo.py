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


def diagram_png(width: int, height: int, seed: str) -> bytes:
    """A flat pseudo-diagram: coloured zones on an off-white ground, with gutters.

    Deliberately not a gradient. Echo stands in for a model that produces flat technical
    diagrams, and the rest of the system leans on that shape — gutter snapping finds the
    whitespace between zones, and transparency needs a single background colour. A
    gradient stand-in makes both look broken locally while the real model would be fine.
    """
    background = (245, 245, 247)
    digest = hashlib.sha256(seed.encode("utf-8")).digest()

    margin_x, margin_y = width // 12, height // 12
    gutter_x, gutter_y = width // 14, height // 14
    cell_w = (width - 2 * margin_x - gutter_x) // 2
    cell_h = (height - 2 * margin_y - gutter_y) // 2

    boxes: list[tuple[int, int, int, int, tuple[int, int, int]]] = []
    for index in range(4):
        col, row = index % 2, index // 2
        x0 = margin_x + col * (cell_w + gutter_x)
        y0 = margin_y + row * (cell_h + gutter_y)
        colour = tuple(70 + (digest[index * 3 + channel] % 150) for channel in range(3))
        boxes.append((x0, y0, x0 + cell_w, y0 + cell_h, colour))  # type: ignore[arg-type]

    blank_row = bytes(background) * width
    raw = bytearray()
    for y in range(height):
        row = bytearray(blank_row)
        for x0, y0, x1, y1, colour in boxes:
            if y0 <= y < y1:
                row[x0 * 3 : x1 * 3] = bytes(colour) * (x1 - x0)
        raw.append(0)  # filter type 0 (None) for this scanline
        raw += row

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


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
            data = diagram_png(params.width, params.height, f"{prompt}:{index}")
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
