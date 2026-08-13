"""The layer between the user and the model."""

from .compile import (
    DEFAULT_LEGEND,
    PROFILE_RULES,
    STRUCTURAL_RULES,
    CompiledPrompt,
    compile_prompt,
    infer_spec,
    render,
)
from .run import JobSpec, build_request, resolve_params, run
from .spec import Callout, Component, Connection, DiagramSpec, Emphasis, Weight

__all__ = [
    "DEFAULT_LEGEND",
    "PROFILE_RULES",
    "STRUCTURAL_RULES",
    "Callout",
    "CompiledPrompt",
    "Component",
    "Connection",
    "DiagramSpec",
    "Emphasis",
    "JobSpec",
    "Weight",
    "build_request",
    "compile_prompt",
    "infer_spec",
    "render",
    "resolve_params",
    "run",
]
