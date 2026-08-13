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
from .style import HouseStyle, Suggestion, extract_recurring, link_for_consistency, merge_rules

__all__ = [
    "DEFAULT_LEGEND",
    "PROFILE_RULES",
    "STRUCTURAL_RULES",
    "Callout",
    "CompiledPrompt",
    "Component",
    "Connection",
    "DiagramSpec",
    "HouseStyle",
    "Emphasis",
    "JobSpec",
    "Suggestion",
    "Weight",
    "build_request",
    "compile_prompt",
    "extract_recurring",
    "infer_spec",
    "link_for_consistency",
    "merge_rules",
    "render",
    "resolve_params",
    "run",
]
