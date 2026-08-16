"""Routing a chat message to generate-or-edit."""

import pytest
from emulsion_engine.intent import classify, refine

EDITS = [
    "make the title bigger",
    "move the database box to the left",
    "remove the arrow between them",
    "change it to a blue palette",
    "add a legend",
    "the labels are too small",
    "swap the colours of the two zones",
    "make it wider",
    "align the boxes",
    "recolour the arrows",
]

GENERATES = [
    "a four-zone architecture diagram",
    "make a flowchart of the deploy pipeline",
    "create an isometric view of a switch",
    "new diagram showing the data path",
    "draw a sequence diagram",
    "an editorial chart of quarterly revenue",
    "generate a network topology",
]


@pytest.mark.parametrize("message", EDITS)
def test_edits_are_routed_as_edits(message):
    assert classify(message, has_previous_image=True).is_edit


@pytest.mark.parametrize("message", GENERATES)
def test_fresh_subjects_are_routed_as_generations(message):
    assert not classify(message, has_previous_image=True).is_edit


@pytest.mark.parametrize("message", EDITS)
def test_nothing_is_an_edit_without_a_previous_image(message):
    """The gate beats every wording. There is nothing on screen to act on."""
    assert not classify(message, has_previous_image=False).is_edit


def test_a_definite_noun_downstream_does_not_flip_the_subject():
    """Regression: "the" anywhere in the sentence used to force an edit.

    "make a flowchart of the deploy pipeline" names its subject with "a"; the later
    "the" modifies that subject rather than pointing at the screen.
    """
    got = classify("make a flowchart of the deploy pipeline", has_previous_image=True)
    assert not got.is_edit, got


def test_add_is_an_edit_even_with_an_indefinite_object():
    """Regression: "add a legend" means add it to the picture that exists.

    Only verbs that can introduce a whole new subject — make, build, produce — get the
    indefinite-article override.
    """
    assert classify("add a legend", has_previous_image=True).is_edit


def test_an_explicit_marker_beats_a_definite_article():
    assert not classify("new diagram of the same system", has_previous_image=True).is_edit


def test_empty_and_whitespace_are_generations():
    assert not classify("   ", has_previous_image=True).is_edit
    assert not classify("", has_previous_image=True).is_edit


def test_the_reason_is_populated_for_the_event_trail():
    got = classify("make the title bigger", has_previous_image=True)
    assert got.reason and 0.0 < got.confidence <= 1.0


def test_refine_restates_the_original():
    """The model regenerates fully on edit, so dropping the original loses the diagram."""
    prompt = refine("a four-zone architecture diagram", "make the title bigger.")
    assert "four-zone architecture diagram" in prompt
    assert "make the title bigger" in prompt
    assert "stay identical" in prompt
    # The trailing full stop is absorbed rather than doubled mid-sentence.
    assert "bigger.." not in prompt


def test_refine_without_an_original_is_just_the_instruction():
    assert refine("", "make it blue") == "make it blue"
