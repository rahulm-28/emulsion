"""The compiler, checked against a prompt that is known to have worked.

The reference case is the "Timesheet Audit Agent" architecture pair in
`../gpt-image-2/Prompts/` — hand-written, run against the real model, output kept. The
spec below is that prompt reverse-engineered into structure; if the compiler can emit
the parts that made it work, it is doing its job.
"""

import pytest
from emulsion_engine import (
    STRUCTURAL_RULES,
    Callout,
    Component,
    Connection,
    DiagramSpec,
    Emphasis,
    Weight,
    compile_prompt,
    infer_spec,
    render,
)
from emulsion_providers import load_manifest

MANIFEST = load_manifest("gpt-image-2")

LEGEND = {
    "ai": "Purple = AI/LLM",
    "code": "Green = deterministic Python",
    "channel": "Blue = Microsoft 365/channel",
    "storage": "Yellow = storage",
}

TIMESHEET = DiagramSpec(
    title="Timesheet Audit Agent — Proposed Architecture (AI-first agent)",
    key_message=(
        "the AI is now the brain — a central agent loop that plans and orchestrates, "
        "with the deterministic audit engine reduced to a tool it calls"
    ),
    legend=LEGEND,
    components=(
        Component(name="Microsoft Teams", layer="User Interface", role="channel"),
        Component(
            name="LLM Agent Runtime",
            layer="Agent Runtime",
            role="ai",
            emphasis=Emphasis.DOMINANT,
            items=("Agent loop: plan → call tool → observe → repeat", "Multi-step planning"),
        ),
        Component(
            name="Python audit engine",
            layer="Deterministic engine",
            role="code",
            note="reused as-is, now behind tools",
        ),
        Component(name="Azure Table Storage", layer="Memory", role="storage"),
    ),
    connections=(
        Connection(source="Microsoft Teams", target="LLM Agent Runtime", label="user message"),
        Connection(
            source="LLM Agent Runtime",
            target="Python audit engine",
            label="deterministic audit",
        ),
        Connection(
            source="Azure Table Storage",
            target="LLM Agent Runtime",
            label="conversation memory",
            weight=Weight.SECONDARY,
        ),
    ),
    callouts=(
        Callout(
            anchor="Python audit engine",
            text=(
                "Payroll math stays exact and auditable — the AI orchestrates it, "
                "it does not guess."
            ),
        ),
    ),
)


def test_a_bare_sentence_still_gets_the_constraint_pack():
    # The whole point: even one line of intent inherits the encoded knowledge.
    compiled = compile_prompt("an architecture diagram for my timesheet agent", MANIFEST)
    for rule in STRUCTURAL_RULES:
        assert rule in compiled.text


def test_the_gutter_rule_is_always_present():
    """M5 crops on low-variance bands. If the compiler stops asking for gutters, the
    edit subsystem loses the property it depends on."""
    compiled = compile_prompt("anything at all", MANIFEST)
    assert "whitespace gutters" in compiled.text


def test_compilation_expands_intent_substantially():
    intent = "current vs proposed architecture for the timesheet agent"
    compiled = compile_prompt(intent, MANIFEST)
    assert len(compiled.text) > len(intent) * 8


def test_title_is_lifted_from_quotes():
    compiled = compile_prompt('a diagram titled "Payment Flow — v2"', MANIFEST)
    assert '"Payment Flow — v2"' in compiled.text


def test_key_message_is_recovered_from_intent():
    compiled = compile_prompt(
        "architecture diagram showing that the AI is only a thin layer at the edge",
        MANIFEST,
    )
    assert "key message" in compiled.text.lower()
    assert "thin layer at the edge" in compiled.text


def test_reference_spec_renders_its_structure():
    compiled = render(TIMESHEET, MANIFEST)
    text = compiled.text

    assert TIMESHEET.title in text
    assert "key message" in text.lower()
    # Legend, components, arrows, callouts all present.
    assert "Purple = AI/LLM" in text
    assert "LLM Agent Runtime" in text
    assert "Agent loop: plan → call tool → observe → repeat" in text
    assert "user message" in text
    assert "Payroll math stays exact" in text


def test_emphasis_becomes_an_instruction_the_model_can_act_on():
    text = render(TIMESHEET, MANIFEST).text
    assert "largest and central" in text


def test_secondary_arrows_are_marked_down():
    text = render(TIMESHEET, MANIFEST).text
    assert "thin and secondary" in text


def test_bidirectional_arrows_render_as_such():
    spec = DiagramSpec(
        title="t",
        components=(Component(name="A"), Component(name="B")),
        connections=(Connection(source="A", target="B", bidirectional=True, label="sync"),),
    )
    assert "A <-> B" in render(spec, MANIFEST).text


def test_consistency_directive_supports_deck_pairs():
    """The real prompt pair asked for side-by-side comparability. That is M7's seed."""
    spec = DiagramSpec(title="Proposed", consistency_with="Current Architecture")
    text = render(spec, MANIFEST).text
    assert "same layout" in text.lower()
    assert "side by side" in text


# -- the compiler tells you when the spec is wrong ------------------------------------


def test_dangling_connection_is_reported():
    spec = DiagramSpec(
        title="t",
        key_message="k",
        components=(Component(name="A"),),
        connections=(Connection(source="A", target="Ghost"),),
    )
    warnings = render(spec, MANIFEST).warnings
    assert any("Ghost" in w for w in warnings)


def test_two_dominant_components_is_reported():
    spec = DiagramSpec(
        title="t",
        key_message="k",
        components=(
            Component(name="A", emphasis=Emphasis.DOMINANT),
            Component(name="B", emphasis=Emphasis.DOMINANT),
        ),
    )
    assert any("dominant" in w for w in render(spec, MANIFEST).warnings)


def test_missing_key_message_is_reported():
    spec = DiagramSpec(title="t", components=(Component(name="A"),))
    assert any("key message" in w for w in render(spec, MANIFEST).warnings)


def test_role_absent_from_legend_is_reported():
    spec = DiagramSpec(
        title="t",
        key_message="k",
        legend={"ai": "Purple = AI"},
        components=(Component(name="A", role="storage"),),
    )
    assert any("storage" in w for w in render(spec, MANIFEST).warnings)


def test_a_correct_spec_produces_no_warnings():
    assert render(TIMESHEET, MANIFEST).warnings == ()


def test_orphan_callout_is_reported():
    spec = DiagramSpec(
        title="t",
        key_message="k",
        components=(Component(name="A"),),
        callouts=(Callout(anchor="Nowhere", text="hi"),),
    )
    assert any("Nowhere" in w for w in render(spec, MANIFEST).warnings)


# -- profile dispatch, not model dispatch ---------------------------------------------


def test_rules_follow_the_profile_not_the_model_id():
    """Invariant 3: swapping the declared profile changes the pack with no branching."""
    short = MANIFEST.model_copy(update={"prompt_profile": "short_descriptive"})
    long_text = compile_prompt("x", MANIFEST).text
    short_text = compile_prompt("x", short).text
    assert len(short_text) < len(long_text)
    assert "Include a legend box" in long_text
    assert "Include a legend box" not in short_text


def test_unknown_profile_falls_back_rather_than_failing():
    odd = MANIFEST.model_copy(update={"prompt_profile": "something-new"})
    assert "whitespace gutters" in compile_prompt("x", odd).text


@pytest.mark.parametrize("intent", ["", "   ", "."])
def test_empty_intent_does_not_crash(intent):
    assert compile_prompt(intent, MANIFEST).text


def test_inferred_spec_carries_the_house_legend():
    spec = infer_spec("a diagram", house_legend={"ai": "Teal = models"})
    assert spec.legend == {"ai": "Teal = models"}


def test_explicit_structure_keeps_freeform_corrections():
    instruction = "Keep every box, but make the title larger and use charcoal arrows."
    compiled = compile_prompt(instruction, MANIFEST, spec=TIMESHEET)
    assert instruction in compiled.text
    assert TIMESHEET.title in compiled.text
    assert compiled.warnings == render(TIMESHEET, MANIFEST).warnings


def test_inference_preserves_details_beyond_the_title():
    instruction = "A labelled diagram. " + "Keep these boxes equally spaced. " * 5 + "NO GRADIENTS."
    assert instruction in compile_prompt(instruction, MANIFEST).text
