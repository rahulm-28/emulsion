"""Turn a job specification into a provider call and its results.

This is the seam the moat will fill. Today it does the two things that are already
decided — resolve parameters against the model's manifest, and assemble typed parts —
and passes a prompt through unchanged. M2 replaces `compile_prompt` with the real
compiler; nothing else in the flow has to move when it does.

Imports nothing web-related (invariant 2). No `if model == ...` anywhere (invariant 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emulsion_providers import (
    ImagePart,
    Manifest,
    Request,
    TextPart,
    load_manifest,
    resolve_size,
)
from emulsion_providers.adapters.base import Adapter, GenerationParams, Result


@dataclass(frozen=True)
class JobSpec:
    """Everything needed to run one job, independent of how it was requested."""

    prompt: str
    model_id: str = "gpt-image-2"
    size: str = "1k"
    n: int = 1
    quality: str = "high"
    output_format: str = "png"
    source_blob_ids: list[str] = field(default_factory=list)
    reference_blob_ids: list[str] = field(default_factory=list)


def compile_prompt(user_intent: str, manifest: Manifest) -> str:
    """Expand short user intent into the prompt the model actually needs.

    ponytail: pass-through. The real compiler is M2 and it is the product's whole
    reason to exist — `prompt_profile` on the manifest (`long_structured` for
    gpt-image-2) is the switch it will dispatch on. Kept as a named function so the
    call site is already in the right place.
    """
    return user_intent


def build_request(spec: JobSpec, manifest: Manifest) -> Request:
    """Assemble typed parts. Never a bare prompt string (M0 §4.5)."""
    parts: list = [TextPart(text=compile_prompt(spec.prompt, manifest))]
    parts += [ImagePart(role="source", blob_id=b) for b in spec.source_blob_ids]
    parts += [ImagePart(role="reference", blob_id=b) for b in spec.reference_blob_ids]
    return Request(parts=parts)


def resolve_params(spec: JobSpec, manifest: Manifest) -> GenerationParams:
    width, height = resolve_size(spec.size, manifest.pixels)
    # Asking for more candidates than the model returns per call is not an error —
    # it is a batching decision the adapter layer will make. Clamp to what it declares.
    n = max(1, min(spec.n, manifest.n_per_request))
    return GenerationParams(
        width=width,
        height=height,
        n=n,
        quality=spec.quality,
        output_format=spec.output_format,
    )


def run(
    spec: JobSpec,
    adapter: Adapter,
    *,
    blobs: dict[str, bytes] | None = None,
    on_progress=None,  # noqa: ANN001 - Callable[[str], None]
) -> Result:
    manifest = (
        adapter.manifest if adapter.manifest.id == spec.model_id else load_manifest(spec.model_id)
    )
    request = build_request(spec, manifest)
    params = resolve_params(spec, manifest)
    if on_progress:
        on_progress(f"resolved {params.width}x{params.height}, n={params.n}")
    return adapter.submit(request, params, blobs=blobs, on_progress=on_progress)
