"""The prompt compiler. This is the moat.

Everyone else sends the user's sentence to the model. The difference between "a diagram
of my architecture" and a picture worth putting in a deck is roughly twenty-five lines of
structure, and those lines are the same every time. Encoding them is the product.

Two deliberate decisions:

**No model call happens here.** The compiler is deterministic templating plus encoded
knowledge, not a second LLM in the loop. That keeps `packages/engine` a pure library
(invariant 2), makes the output reproducible, keeps latency at zero, and means the
knowledge is inspectable and improvable rather than hidden in another model's weights.

**Constraint packs are keyed on `prompt_profile`, never on a model id** (invariant 3).
gpt-image-2 declares `long_structured`; a diffusion model would declare something else
and get a different pack without a line of branching here.

The whitespace-gutter directive is the load-bearing one. It is not a style preference —
flat diagrams with low-variance gutters between zones are precisely what makes M5's
crop-and-composite edit viable, because there is nothing to blend at the seam. The
compiler creates the conditions the editor later depends on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from emulsion_providers import Manifest

from .spec import Component, Connection, DiagramSpec, Emphasis, Weight
from .style import HouseStyle, merge_rules

# --------------------------------------------------------------------------------------
# Constraint packs
# --------------------------------------------------------------------------------------

STYLE_BASE: tuple[str, ...] = (
    "vector, flat design, high contrast",
    "clean modern professional look",
    "readable at slide/presentation size",
)

# Why each line earns its place is recorded next to it — a constraint nobody can justify
# is a constraint that will be dropped by the next person who reads this.
STRUCTURAL_RULES: tuple[str, ...] = (
    # Makes region edits possible later: low-variance bands give M5 a seam-free crop.
    "Leave generous whitespace gutters between zones; do not let boxes touch.",
    # Autoregressive models render in-image text well, but only if told it matters.
    "Every box and every arrow carries a short readable label.",
    "Spell all labels exactly as written; do not paraphrase or abbreviate them.",
    # Without this the legend is invented per-run and the colour mapping drifts.
    "Include a legend box mapping each colour to its meaning.",
    # Straight orthogonal routing survives downscaling to a 2048px viewer derivative.
    "Route arrows orthogonally with clear arrowheads; avoid crossing lines where possible.",
)

PROFILE_RULES: dict[str, tuple[str, ...]] = {
    "long_structured": STRUCTURAL_RULES,
    # A short-prompt model drowns in the list above; give it the two that matter most.
    "short_descriptive": STRUCTURAL_RULES[:2],
}

DEFAULT_LEGEND: dict[str, str] = {
    "ai": "Purple = AI/LLM",
    "code": "Green = deterministic code",
    "channel": "Blue = user-facing channel",
    "integration": "Orange = integration",
    "storage": "Yellow = storage",
    "observability": "Grey = observability",
}

_EMPHASIS_PHRASE = {
    Emphasis.DOMINANT: "largest and central",
    Emphasis.ASIDE: "small and off to the side",
    Emphasis.NORMAL: "",
}


@dataclass(frozen=True)
class CompiledPrompt:
    """The rendered prompt plus what the compiler noticed while building it."""

    text: str
    warnings: tuple[str, ...] = ()

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.text


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------


def render(
    spec: DiagramSpec, manifest: Manifest, *, style: HouseStyle | None = None
) -> CompiledPrompt:
    """Turn a spec into the prompt this model's profile rewards.

    A house style contributes defaults and extra rules; the spec always wins on any
    field it has already set.
    """
    if style is not None:
        spec = style.apply_to(spec)
    warnings: list[str] = []
    lines: list[str] = []

    subject = "cloud architecture diagram" if spec.legend else "diagram"
    opening = f'Create a professional {subject} titled "{spec.title}".'
    if spec.layout:
        opening += f" Lay it out as {spec.layout}, with directional, labeled arrows."
    if spec.legend:
        opening += " Use this color legend: " + "; ".join(spec.legend.values()) + "."
    lines.append(opening)

    if spec.key_message:
        # Stated before the component list on purpose: it is the instruction the model
        # falls back on when the components alone under-determine size and placement.
        lines.append(f"\nThe key message this diagram must convey: {spec.key_message}")

    if spec.consistency_with:
        lines.append(
            f"\nUse the same layout, colour legend and visual language as "
            f'"{spec.consistency_with}", so the two can sit side by side.'
        )

    if spec.components:
        lines.append("\nComponents:")
        lines.extend(_render_components(spec))

    if spec.connections:
        lines.append("\nConnections (draw these as directional, labeled arrows):")
        lines.extend(f"- {_render_connection(c)}" for c in spec.connections)

    if spec.callouts:
        lines.append("\nAnnotation callouts:")
        for index, callout in enumerate(spec.callouts, start=1):
            prefix = f"({index}) " if len(spec.callouts) > 1 else ""
            anchor = f"on the {callout.anchor} box: " if callout.anchor else ""
            lines.append(f'- {prefix}{anchor}"{callout.text}"')

    rules = PROFILE_RULES.get(manifest.prompt_profile, STRUCTURAL_RULES)
    if style is not None:
        rules = merge_rules(rules, style)
    if rules:
        lines.append("\nRules:")
        lines.extend(f"- {rule}" for rule in rules)

    style_words = [*STYLE_BASE, *(style.style_words if style else ())]
    lines.append("\nStyle: " + ", ".join(style_words) + ".")

    warnings.extend(_validate(spec))
    return CompiledPrompt(text="\n".join(lines).strip(), warnings=tuple(warnings))


def _render_components(spec: DiagramSpec) -> list[str]:
    out: list[str] = []
    layers = spec.layers()
    grouped = layers or [""]
    counter = 0
    for layer in grouped:
        members = [c for c in spec.components if (c.layer or "") == layer]
        for component in members:
            counter += 1
            out.append(f"{counter}. {_render_component(component, spec)}")
    return out


def _render_component(component: Component, spec: DiagramSpec) -> str:
    parts: list[str] = []
    if component.layer:
        parts.append(f"{component.layer} —")
    parts.append(component.name)

    qualifiers: list[str] = []
    colour = spec.legend.get(component.role, "")
    if colour:
        # "Purple = AI/LLM" -> "Purple"
        qualifiers.append(colour.split("=")[0].strip())
    phrase = _EMPHASIS_PHRASE[component.emphasis]
    if phrase:
        qualifiers.append(phrase)
    if qualifiers:
        parts.append(f"({', '.join(qualifiers)})")

    text = " ".join(parts)
    if component.items:
        text += ". Inside it show: " + "; ".join(component.items)
    if component.note:
        text += f'. Label it "{component.note}"'
    return text.rstrip(".") + "."


def _render_connection(connection: Connection) -> str:
    arrow = "<->" if connection.bidirectional else "->"
    text = f"{connection.source} {arrow} {connection.target}"
    if connection.label:
        text += f' — "{connection.label}"'
    if connection.weight is Weight.SECONDARY:
        text += ". Draw this arrow thin and secondary"
    elif connection.weight is Weight.PRIMARY and connection.label:
        pass
    return text


def _validate(spec: DiagramSpec) -> list[str]:
    """Problems the user should hear about rather than discover in the picture."""
    warnings: list[str] = []

    for connection in spec.dangling_connections():
        warnings.append(
            f"connection {connection.source!r} -> {connection.target!r} references a "
            f"component that was never declared; the model will invent it"
        )
    for callout in spec.orphan_callouts():
        warnings.append(f"callout anchored to unknown component {callout.anchor!r}")

    dominant = [c for c in spec.components if c.emphasis is Emphasis.DOMINANT]
    if len(dominant) > 1:
        warnings.append(
            "more than one component is marked dominant; the model cannot make two "
            f"things largest ({', '.join(c.name for c in dominant)})"
        )
    if spec.components and not spec.key_message:
        warnings.append(
            "no key message — the diagram will be a component list rather than an argument"
        )
    roles = {c.role for c in spec.components if c.role}
    unknown = roles - set(spec.legend)
    if unknown:
        warnings.append(f"component roles missing from the legend: {', '.join(sorted(unknown))}")
    return warnings


# --------------------------------------------------------------------------------------
# Intent -> spec
# --------------------------------------------------------------------------------------

_TITLE_QUOTED = re.compile(r"[\"“]([^\"”]{3,120})[\"”]")
_TITLED_AS = re.compile(r"\btitled\s+(.+?)(?:[.;]|$)", re.IGNORECASE)

# Words that signal the picture is arguing something, not just listing boxes.
_MESSAGE_MARKERS = (
    "showing that",
    "to show",
    "the point is",
    "emphasise",
    "emphasize",
    "make clear",
    "conveying",
)


def infer_spec(intent: str, *, house_legend: dict[str, str] | None = None) -> DiagramSpec:
    """Best-effort spec from a free-text sentence.

    ponytail: shallow parsing — a quoted title, a key-message marker, and defaults for
    everything else. It is deliberately not a semantic parser: the honest upgrade is to
    let the user edit the spec directly in the UI (the structure is already typed for
    it), not to guess harder here. What this does buy is that even a one-line intent
    picks up the constraint pack, which is where most of the quality lives.
    """
    text = " ".join(intent.split())

    title = ""
    quoted = _TITLE_QUOTED.search(text)
    titled = _TITLED_AS.search(text)
    if quoted:
        title = quoted.group(1)
    elif titled:
        title = titled.group(1).strip(" \"'")
    else:
        title = text[:80].rstrip(".,;")

    key_message = ""
    lowered = text.lower()
    for marker in _MESSAGE_MARKERS:
        index = lowered.find(marker)
        if index != -1:
            key_message = text[index + len(marker) :].strip(" ,.:;")
            break

    return DiagramSpec(
        title=title or "Untitled diagram",
        key_message=key_message,
        legend=dict(house_legend or DEFAULT_LEGEND),
    )


def compile_prompt(
    user_intent: str,
    manifest: Manifest,
    *,
    spec: DiagramSpec | None = None,
    house_legend: dict[str, str] | None = None,
    style: HouseStyle | None = None,
) -> CompiledPrompt:
    """Expand short user intent into the prompt the model actually needs.

    Pass `spec` when the caller already has structure (the UI's spec editor, a saved
    house style, a rerun of an earlier job). Otherwise one is inferred from the text.
    """
    if spec is None:
        spec = infer_spec(
            user_intent, house_legend=house_legend or (style.legend if style else None)
        )
    return render(spec, manifest, style=style)
