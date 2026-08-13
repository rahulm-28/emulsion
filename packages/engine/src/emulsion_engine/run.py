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

from .compile import CompiledPrompt, compile_prompt
from .spec import DiagramSpec


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
    # Supplied when the caller already has structure — a spec editor, a saved house
    # style, or a rerun. Absent means infer it from `prompt`.
    diagram: DiagramSpec | None = None
    house_legend: dict[str, str] | None = None


def build_request(spec: JobSpec, manifest: Manifest) -> tuple[Request, CompiledPrompt]:
    """Assemble typed parts. Never a bare prompt string (M0 §4.5).

    Returns the compiled prompt alongside the request so the caller can surface the
    compiler's warnings — a spec with a dangling arrow produces a picture with an
    invented box, and the user should hear about it before paying for the render.
    """
    compiled = compile_prompt(
        spec.prompt,
        manifest,
        spec=spec.diagram,
        house_legend=spec.house_legend,
    )
    parts: list = [TextPart(text=compiled.text)]
    parts += [ImagePart(role="source", blob_id=b) for b in spec.source_blob_ids]
    parts += [ImagePart(role="reference", blob_id=b) for b in spec.reference_blob_ids]
    return Request(parts=parts), compiled


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
    request, compiled = build_request(spec, manifest)
    params = resolve_params(spec, manifest)
    if on_progress:
        source = "supplied spec" if spec.diagram else "inferred spec"
        on_progress(
            f"compiled prompt from {source}: {len(spec.prompt)} → {len(compiled.text)} chars"
        )
        for warning in compiled.warnings:
            on_progress(f"prompt warning: {warning}")
        on_progress(f"resolved {params.width}x{params.height}, n={params.n}")
    return adapter.submit(request, params, blobs=blobs, on_progress=on_progress)
