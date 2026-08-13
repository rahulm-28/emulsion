"""Capability manifests — what a model can actually do, expressed as data.

The engine reads manifests. It never branches on a model id (CLAUDE.md invariant 3).
Adding a model is a YAML file plus, at most, an adapter.

Values are measured against a real deployment wherever possible; each field's
provenance is recorded as a comment in the YAML, marked `confirmed`, `inferred`
or `unverified`. A guess encoded as fact silently degrades every request routed
to that model, so an unknown stays absent rather than being filled in.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ponytail: manifests load from YAML on disk. M0 §4.2 wants them seeded as DB rows so a
# new model is a row plus a config deploy rather than a release. Swap `load_manifest`'s
# body for a repository lookup when `packages/db` exists (M3) — the callers don't change.
MANIFEST_DIR = Path(__file__).parent / "manifests"


class MaskSupport(StrEnum):
    """How seriously a model takes a mask."""

    NONE = "none"
    SOFT = "soft"  # accepted, but does not pixel-lock outside the masked region
    HARD = "hard"  # true pixel replacement, e.g. DALL-E 2


class PixelRules(BaseModel):
    """Dimensional limits a request must satisfy before it is worth sending."""

    model_config = ConfigDict(frozen=True)

    min: int
    max: int
    long_edge: int
    aspect: tuple[float, float]
    multiple_of: int = 1


class RateLimit(BaseModel):
    """A token bucket, not a per-minute cap.

    Deployments express this as `requests` per `window_s`; flattening it to an RPM
    figure is what produced the wrong 2-RPM number this project ran on for months.
    """

    model_config = ConfigDict(frozen=True)

    requests: int
    window_s: float

    @property
    def approx_rpm(self) -> float:
        return self.requests * 60.0 / self.window_s


class CostModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    usd_per_1m_input_tokens: float
    usd_per_1m_output_tokens: float


class Manifest(BaseModel):
    """A model's declared capabilities."""

    model_config = ConfigDict(frozen=True)

    id: str
    provider: str
    modalities_in: list[str]
    modalities_out: list[str]

    pixels: PixelRules
    mask_support: MaskSupport
    transparency: bool
    edit_full_regen: bool
    multi_reference: int

    n_per_request: int = 1
    rate_limit: RateLimit
    max_input_bytes: int
    input_formats: list[str]
    output_formats: list[str]

    api_version: str
    auth_headers: list[str]

    prompt_profile: str
    strengths: dict[str, str] = Field(default_factory=dict)
    cost_model: CostModel

    # Params an adapter must drop before sending, and report as dropped (invariant 7).
    unsupported_params: list[str] = Field(default_factory=list)


@cache
def load_manifest(model_id: str) -> Manifest:
    """Load and validate the manifest for `model_id`."""
    path = MANIFEST_DIR / f"{model_id}.yaml"
    if not path.is_file():
        raise KeyError(f"No manifest for model {model_id!r}. Available: {available_models()}")
    return Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def available_models() -> list[str]:
    return sorted(p.stem for p in MANIFEST_DIR.glob("*.yaml"))


def cost_usd(manifest: Manifest, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call, from the token counts the API reports in `usage`.

    Token counts are ground truth; the per-token rates in the manifest may not be.
    Check `cost_model` provenance before quoting a price to a user.
    """
    c = manifest.cost_model
    return (
        input_tokens * c.usd_per_1m_input_tokens + output_tokens * c.usd_per_1m_output_tokens
    ) / 1_000_000
