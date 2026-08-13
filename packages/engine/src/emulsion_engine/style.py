"""House styles and learned constraints — the part that gets better the more you use it.

Two mechanisms, deliberately both inspectable:

**House style.** A named, reusable set of defaults — a colour legend, extra rules, a
layout preference. Applied before rendering, so every diagram in a deck inherits the
same visual language without anyone retyping it. The user's own prompt pair does this by
hand: the second one opens by asking for "the same color legend as the current diagram,
so the two can sit side by side". A house style is that sentence, persisted.

**Learned constraints.** Recurring clauses lifted out of prompts the user has already
written. If "no gridlines" appears in four separate prompts, it is not a one-off — it is
how this person wants charts to look, and it should stop needing to be typed.

There is no model in here and no embedding store. The extraction is clause counting,
which means every suggestion can be traced to the prompts that produced it and dismissed
if it is wrong. A learned constraint the user cannot see or overrule is a constraint that
will eventually ruin a picture for reasons nobody can debug.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from .spec import DiagramSpec

# Clause separators. Structured prompts are written as comma-delimited constraint lists,
# which is what makes clause counting work at all on this corpus.
_SPLIT = re.compile(r"[,;.\n]+")

# Clauses that carry no reusable instruction. Kept small and explicit rather than a
# general stopword list — the goal is to drop connective tissue, not vocabulary.
_NOISE = frozenset(
    {
        "and",
        "or",
        "with",
        "for",
        "the",
        "a",
        "an",
        "please",
        "make it",
        "create",
        "generate",
        "show",
        "draw",
        "i want",
        "can you",
    }
)

MIN_CLAUSE_WORDS = 2
MAX_CLAUSE_WORDS = 12
DEFAULT_MIN_OCCURRENCES = 3


@dataclass(frozen=True)
class HouseStyle:
    """Reusable defaults applied to every diagram that opts into it."""

    name: str
    legend: dict[str, str] = field(default_factory=dict)
    rules: tuple[str, ...] = ()
    layout: str = ""
    # Free-text style words appended to the style block, e.g. "muted palette".
    style_words: tuple[str, ...] = ()

    def apply_to(self, spec: DiagramSpec) -> DiagramSpec:
        """Fill in what the spec has not already said.

        The spec wins on every conflict. A house style is a default, not an override —
        someone who typed a legend for this one diagram meant it.
        """
        return replace(
            spec,
            legend={**self.legend, **spec.legend} if self.legend else spec.legend,
            layout=spec.layout or self.layout or DiagramSpec.layout,
        )


@dataclass(frozen=True)
class Suggestion:
    """A constraint the user keeps typing, with the evidence for it."""

    text: str
    occurrences: int
    examples: tuple[str, ...] = ()

    def explain(self) -> str:
        return f'"{self.text}" appeared in {self.occurrences} prompts'


def _clauses(prompt: str) -> list[str]:
    out: list[str] = []
    for raw in _SPLIT.split(prompt):
        clause = " ".join(raw.split()).strip().lower()
        if not clause or clause in _NOISE:
            continue
        words = clause.split()
        if not MIN_CLAUSE_WORDS <= len(words) <= MAX_CLAUSE_WORDS:
            continue
        out.append(clause)
    return out


def extract_recurring(
    prompts: list[str], *, min_occurrences: int = DEFAULT_MIN_OCCURRENCES
) -> list[Suggestion]:
    """Clauses appearing in at least `min_occurrences` distinct prompts.

    Counted per prompt, not per occurrence: someone who writes the same phrase three
    times in one long prompt has emphasised it once, not established a habit.
    """
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}

    for prompt in prompts:
        for clause in set(_clauses(prompt)):
            counts[clause] += 1
            examples.setdefault(clause, []).append(prompt[:80])

    suggestions = [
        Suggestion(text=clause, occurrences=count, examples=tuple(examples[clause][:3]))
        for clause, count in counts.items()
        if count >= min_occurrences
    ]
    # Most-repeated first, then longest — a longer clause carries more instruction.
    suggestions.sort(key=lambda s: (-s.occurrences, -len(s.text)))
    return suggestions


def link_for_consistency(spec: DiagramSpec, previous_title: str) -> DiagramSpec:
    """Ask for the new diagram to match an earlier one.

    This is what makes a deck read as a deck rather than as N unrelated pictures, and
    it is the one M7 behaviour the user's own hand-written prompts already performed.
    """
    if not previous_title or spec.consistency_with:
        return spec
    return replace(spec, consistency_with=previous_title)


def merge_rules(base: tuple[str, ...], style: HouseStyle) -> tuple[str, ...]:
    """Profile rules plus the house style's, in that order, without duplicates."""
    seen = list(base)
    for rule in style.rules:
        if rule not in seen:
            seen.append(rule)
    return tuple(seen)
