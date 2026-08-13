"""What an adapter is handed and what it gives back.

This is deliberately NOT the `ImageProvider.generate()/edit()` interface M0 §4.1
rejects. That one is rejected because it forces every model to a lowest common
denominator of "prompt in, image out", discarding the model-specific knowledge that
is the moat.

What is here instead: an adapter receives the typed parts (M0 §4.5) plus its own
manifest, and decides for itself what to do with them — which endpoint, which
encoding, which parameters to drop. Two adapters given the same parts can behave
completely differently and neither is wrong. The engine never inspects a model id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ..manifest import Manifest
from ..parts import DroppedPart, Request

ProgressFn = Callable[[str], None]


@dataclass(frozen=True)
class GenerationParams:
    """Resolved, already-validated output parameters."""

    width: int
    height: int
    n: int = 1
    quality: str = "high"
    output_format: str = "png"


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    width: int
    height: int
    content_type: str = "image/png"


@dataclass(frozen=True)
class Result:
    images: list[GeneratedImage]
    dropped: list[DroppedPart] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class Adapter(Protocol):
    """Implemented per provider. `blobs` maps ImagePart/MaskPart blob_id to bytes.

    Passing bytes in rather than a BlobStore keeps `packages/providers` free of any
    storage dependency — it stays a library with a CLI on top (invariant 2).
    """

    manifest: Manifest

    def submit(
        self,
        request: Request,
        params: GenerationParams,
        *,
        blobs: dict[str, bytes] | None = None,
        on_progress: ProgressFn | None = None,
    ) -> Result: ...


class ProviderError(RuntimeError):
    """A provider call failed in a way the user should hear about.

    Messages must never contain a credential — construct them from status codes and
    the provider's own error text, never from request headers.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
