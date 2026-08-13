"""House styles and learned constraints.

The corpus in these tests is the shape of the user's real prompts: comma-delimited
constraint lists, repeated across a deck.
"""

import pytest
from emulsion_engine import (
    STRUCTURAL_RULES,
    Component,
    DiagramSpec,
    HouseStyle,
    compile_prompt,
    extract_recurring,
    link_for_consistency,
    merge_rules,
    render,
)
from emulsion_providers import load_manifest

MANIFEST = load_manifest("gpt-image-2")

HOUSE = HouseStyle(
    name="Deck",
    legend={"ai": "Teal = models", "code": "Slate = deterministic code"},
    rules=("Use sentence case for every label.",),
    layout="three columns, left to right",
    style_words=("muted palette", "no drop shadows"),
)


# -- house styles ---------------------------------------------------------------------


def test_house_style_supplies_a_legend_when_the_spec_has_none():
    text = render(DiagramSpec(title="t", key_message="k"), MANIFEST, style=HOUSE).text
    assert "Teal = models" in text


def test_the_spec_wins_over_the_house_style():
    """A house style is a default, not an override — someone who typed a legend for
    this one diagram meant it."""
    spec = DiagramSpec(title="t", key_message="k", legend={"ai": "Crimson = models"})
    text = render(spec, MANIFEST, style=HOUSE).text
    assert "Crimson = models" in text
    assert "Teal = models" not in text


def test_house_style_layout_fills_a_gap_but_does_not_replace():
    filled = render(DiagramSpec(title="t", layout=""), MANIFEST, style=HOUSE).text
    assert "three columns, left to right" in filled

    explicit = render(DiagramSpec(title="t", layout="a radial hub"), MANIFEST, style=HOUSE).text
    assert "a radial hub" in explicit
    assert "three columns" not in explicit


def test_house_rules_are_appended_after_the_profile_rules():
    text = render(DiagramSpec(title="t", key_message="k"), MANIFEST, style=HOUSE).text
    assert "Use sentence case for every label." in text
    # The profile pack still applies — a house style adds, it does not replace.
    for rule in STRUCTURAL_RULES:
        assert rule in text


def test_house_style_words_reach_the_style_block():
    text = render(DiagramSpec(title="t"), MANIFEST, style=HOUSE).text
    style_line = text.rsplit("Style:", 1)[1]
    assert "muted palette" in style_line
    assert "no drop shadows" in style_line


def test_merge_rules_does_not_duplicate():
    style = HouseStyle(name="x", rules=(STRUCTURAL_RULES[0], "Something new."))
    merged = merge_rules(STRUCTURAL_RULES, style)
    assert merged.count(STRUCTURAL_RULES[0]) == 1
    assert merged[-1] == "Something new."


def test_compile_prompt_accepts_a_style_for_a_bare_sentence():
    text = compile_prompt("a diagram of the pipeline", MANIFEST, style=HOUSE).text
    assert "Teal = models" in text
    assert "Use sentence case for every label." in text


# -- deck consistency -----------------------------------------------------------------


def test_consistency_link_is_added_when_absent():
    spec = link_for_consistency(DiagramSpec(title="Proposed"), "Current Architecture")
    assert spec.consistency_with == "Current Architecture"
    text = render(spec, MANIFEST).text
    assert "side by side" in text


def test_an_existing_consistency_link_is_not_overwritten():
    spec = DiagramSpec(title="C", consistency_with="A")
    assert link_for_consistency(spec, "B").consistency_with == "A"


def test_an_empty_previous_title_is_a_no_op():
    spec = DiagramSpec(title="C")
    assert link_for_consistency(spec, "").consistency_with == ""


# -- learned constraints --------------------------------------------------------------

DECK = [
    "A four-zone architecture diagram, flat vector, no gridlines, generous gutters",
    "A sequence diagram of the checkout flow, flat vector, no gridlines",
    "An editorial chart of quarterly revenue, no gridlines, muted palette",
    "A one-off sketch of a bird",
]


def test_a_clause_repeated_across_prompts_is_surfaced():
    suggestions = extract_recurring(DECK, min_occurrences=3)
    assert [s.text for s in suggestions] == ["no gridlines"]
    assert suggestions[0].occurrences == 3


def test_a_clause_used_once_is_not_surfaced():
    texts = [s.text for s in extract_recurring(DECK, min_occurrences=2)]
    assert "muted palette" not in texts
    assert "a one-off sketch of a bird" not in texts


def test_repetition_inside_one_prompt_is_not_a_habit():
    """Emphasis is not evidence. Counted per prompt, not per occurrence."""
    shouty = ["no gridlines, no gridlines, no gridlines"]
    assert extract_recurring(shouty, min_occurrences=2) == []


def test_suggestions_carry_their_evidence():
    suggestion = extract_recurring(DECK, min_occurrences=3)[0]
    assert suggestion.occurrences == 3
    assert len(suggestion.examples) == 3
    assert "appeared in 3 prompts" in suggestion.explain()


def test_most_repeated_comes_first():
    prompts = [
        "flat vector, no gridlines",
        "flat vector, no gridlines",
        "flat vector",
        "flat vector",
    ]
    texts = [s.text for s in extract_recurring(prompts, min_occurrences=2)]
    assert texts[0] == "flat vector"


@pytest.mark.parametrize("clause", ["and", "the", "please", "x"])
def test_connective_tissue_and_fragments_are_ignored(clause):
    prompts = [f"a diagram, {clause}"] * 5
    assert all(s.text != clause for s in extract_recurring(prompts))


def test_very_long_clauses_are_ignored():
    """A whole sentence is not a reusable constraint; it is one prompt."""
    long_clause = " ".join(["word"] * 20)
    assert extract_recurring([long_clause] * 5) == []


def test_an_empty_corpus_yields_nothing():
    assert extract_recurring([]) == []


def test_a_learned_constraint_can_be_promoted_into_a_house_style():
    """The loop the feature exists for: notice, then persist."""
    suggestion = extract_recurring(DECK, min_occurrences=3)[0]
    style = HouseStyle(name="Deck", rules=(suggestion.text,))
    text = render(DiagramSpec(title="t", key_message="k"), MANIFEST, style=style).text
    assert "no gridlines" in text


def test_house_style_survives_a_spec_with_components():
    spec = DiagramSpec(title="t", key_message="k", components=(Component(name="A", role="ai"),))
    compiled = render(spec, MANIFEST, style=HOUSE)
    assert "Teal" in compiled.text
    # The role resolves against the house legend, so it is not reported as missing.
    assert compiled.warnings == ()
