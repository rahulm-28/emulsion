"""The structured form of a picture, independent of any model's prompt dialect.

This is the intermediate representation the compiler targets. A user expresses intent
in a sentence; the compiler produces one of these; a renderer turns it into whatever
prose the target model rewards. Swapping models changes the renderer, not the spec.

The shape is not invented. It is the structure recovered from prompts that demonstrably
worked against gpt-image-2 — see `../gpt-image-2/Prompts/`. Every field below appears in
those files because leaving it out produced a worse picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Emphasis(StrEnum):
    """Relative visual weight. Autoregressive models honour this; it is not decoration."""

    DOMINANT = "dominant"  # largest, central — "the brain"
    NORMAL = "normal"
    ASIDE = "aside"  # small, off to the side


class Weight(StrEnum):
    """Whether a connection carries the story or merely exists."""

    PRIMARY = "primary"
    SECONDARY = "secondary"


@dataclass(frozen=True)
class Component:
    """One labelled box. `items` become chips inside it."""

    name: str
    layer: str = ""
    role: str = ""  # legend key, e.g. "ai" — resolved against DiagramSpec.legend
    items: tuple[str, ...] = ()
    note: str = ""
    emphasis: Emphasis = Emphasis.NORMAL


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    label: str = ""
    bidirectional: bool = False
    weight: Weight = Weight.PRIMARY


@dataclass(frozen=True)
class Callout:
    """An annotation pointing at a component. Carries the argument, not the label."""

    anchor: str
    text: str


@dataclass(frozen=True)
class DiagramSpec:
    """A diagram, fully specified.

    `key_message` is the single most load-bearing field: it is what the picture must
    argue, and it is what the model uses to decide relative size and placement when the
    component list alone is ambiguous.
    """

    title: str
    key_message: str = ""
    layout: str = "layers stacked top to bottom"
    legend: dict[str, str] = field(default_factory=dict)
    components: tuple[Component, ...] = ()
    connections: tuple[Connection, ...] = ()
    callouts: tuple[Callout, ...] = ()
    consistency_with: str = ""

    def layers(self) -> list[str]:
        """Distinct layers in declaration order."""
        seen: list[str] = []
        for component in self.components:
            if component.layer and component.layer not in seen:
                seen.append(component.layer)
        return seen

    def names(self) -> set[str]:
        return {c.name for c in self.components}

    def dangling_connections(self) -> list[Connection]:
        """Connections naming a component that was never declared.

        A model handed an arrow to a box that does not exist invents the box, which is
        how a diagram grows a component nobody asked for.
        """
        known = self.names()
        return [c for c in self.connections if c.source not in known or c.target not in known]

    def orphan_callouts(self) -> list[Callout]:
        known = self.names()
        return [c for c in self.callouts if c.anchor and c.anchor not in known]


def diagram_from_dict(data: dict) -> DiagramSpec:
    """Rehydrate previously validated storage data without importing web or ORM types."""
    return DiagramSpec(
        title=data["title"],
        key_message=data.get("key_message", ""),
        layout=data.get("layout", ""),
        legend=dict(data.get("legend", {})),
        components=tuple(
            Component(
                **{
                    **item,
                    "items": tuple(item.get("items", [])),
                    "emphasis": Emphasis(item.get("emphasis", "normal")),
                }
            )
            for item in data.get("components", [])
        ),
        connections=tuple(
            Connection(**{**item, "weight": Weight(item.get("weight", "primary"))})
            for item in data.get("connections", [])
        ),
        callouts=tuple(Callout(**item) for item in data.get("callouts", [])),
        consistency_with=data.get("consistency_with", ""),
    )
