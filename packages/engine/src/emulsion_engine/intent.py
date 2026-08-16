"""Decide whether a chat message asks for a new picture or a change to the last one.

This is the conversational half of M5. Drawing a region works, but nobody wants to draw
a box to say "make the title bigger" — they want to type it, the way they would to a
colleague. The layer's job is to notice that the sentence refers to something already
on screen and route it as an edit, carrying the original intent forward so the model
does not lose everything that was already right.

The distinction is mostly grammatical, and one pattern carries most of it: **a
determiner**. "make a flowchart" introduces something new; "make the arrows thicker"
points at something that exists. Indefinite means generate, definite means edit.

Ambiguity resolves to `generate`. Both paths cost the same and neither loses data, but
an unasked-for edit is the more confusing failure: the person sees their new request
silently reinterpreted as a tweak of the old picture, and the prompt they typed appears
to have been ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Verbs that act on something already present. "add" counts: with a picture on screen,
# "add a legend" means add it *to that picture*.
EDIT_VERBS = frozenset(
    [
        "add",
        "adjust",
        "align",
        "brighten",
        "centre",
        "center",
        "change",
        "crop",
        "darken",
        "decrease",
        "delete",
        "enlarge",
        "fix",
        "flip",
        "increase",
        "lighten",
        "lower",
        "make",
        "move",
        "raise",
        "recolor",
        "recolour",
        "reduce",
        "remove",
        "rename",
        "replace",
        "resize",
        "rotate",
        "set",
        "shrink",
        "swap",
        "tweak",
        "update",
        "widen",
    ]
)

# Verbs that can introduce a whole new subject as easily as modify an existing one.
# Only for these does an indefinite article flip the reading: "make a flowchart" is a
# new picture, while "add a legend" is a legend added to the picture already there.
SUBJECT_INTRODUCING = frozenset({"make", "set", "update", "build", "produce"})

# Said explicitly, these override everything — including a definite article.
GENERATE_MARKERS = (
    "new diagram",
    "new image",
    "new version of",
    "another diagram",
    "another image",
    "start over",
    "from scratch",
    "instead draw",
    "now draw",
    "generate a",
    "generate an",
    "create a",
    "create an",
    "draw a",
    "draw an",
)

# Pronouns and definite references that only mean something if a picture exists.
DEFINITE = re.compile(
    r"\b(it|its|it's|that|this|these|those|them|they|the same|again)\b",
    re.IGNORECASE,
)
DEFINITE_NOUN = re.compile(r"\bthe\s+[a-z]", re.IGNORECASE)

# Whether the *sentence opens* definite decides a verbless message. "the labels are too
# small" is a complaint about what is on screen; "a diagram of the deploy pipeline"
# also contains "the", but names its subject with "a" first. Position carries the
# meaning that presence alone does not.
OPENS_DEFINITE = re.compile(
    r"^\s*(the|it|its|that|this|these|those|they)\b",
    re.IGNORECASE,
)

Kind = Literal["generate", "edit"]


@dataclass(frozen=True)
class Intent:
    kind: Kind
    reason: str
    confidence: float

    @property
    def is_edit(self) -> bool:
        return self.kind == "edit"


def _first_two_words(message: str) -> tuple[str, str]:
    words = re.findall(r"[a-z']+", message.lower())
    return (words[0] if words else "", words[1] if len(words) > 1 else "")


def classify(message: str, *, has_previous_image: bool) -> Intent:
    """Route one chat message.

    `has_previous_image` is the hard gate: with nothing on screen there is nothing to
    edit, and no wording can change that.
    """
    text = message.strip()
    if not has_previous_image:
        return Intent("generate", "nothing has been generated yet", 1.0)
    if not text:
        return Intent("generate", "empty message", 1.0)

    lowered = text.lower()

    for marker in GENERATE_MARKERS:
        if marker in lowered:
            return Intent("generate", f"says {marker!r}", 0.95)

    verb, obj = _first_two_words(lowered)
    opens_with_edit_verb = verb in EDIT_VERBS
    has_definite = bool(DEFINITE.search(lowered) or DEFINITE_NOUN.search(lowered))

    # The determiner *directly after the verb* decides, not one anywhere in the
    # sentence: "make a flowchart of the deploy pipeline" names its subject with "a"
    # and only mentions "the" downstream, where it modifies the subject rather than
    # pointing at the screen.
    if verb in SUBJECT_INTRODUCING and obj in {"a", "an"}:
        return Intent("generate", f"'{verb} {obj} …' introduces a new subject", 0.8)

    if opens_with_edit_verb and has_definite:
        return Intent("edit", f"'{verb}' acting on something already shown", 0.9)
    if opens_with_edit_verb:
        return Intent("edit", f"opens with '{verb}'", 0.7)
    if DEFINITE.search(lowered):
        return Intent("edit", "refers back to the current image", 0.65)
    if OPENS_DEFINITE.match(lowered):
        return Intent("edit", "opens by naming something already shown", 0.65)

    return Intent("generate", "reads as a fresh subject", 0.6)


def refine(original_prompt: str, instruction: str) -> str:
    """Build the prompt for a conversational edit.

    `gpt-image-2` regenerates the entire image on every edit — there is no partial
    edit and no parameter that creates one. So the original intent has to be restated,
    or everything that was already right is re-rolled on a prompt that only describes
    the change. Restating it is the difference between "make the title bigger" keeping
    your diagram and returning an unrelated picture of a bigger title.
    """
    original = original_prompt.strip()
    change = instruction.strip().rstrip(".")
    if not original:
        return change
    return (
        f"{original}\n\n"
        f"Reproduce the supplied image exactly, then apply only this change: {change}. "
        f"Everything not mentioned must stay identical — same layout, same palette, "
        f"same wording, same positions."
    )


if __name__ == "__main__":
    edits = [
        "make the title bigger",
        "move the database box to the left",
        "remove the arrow between them",
        "change it to a blue palette",
        "add a legend",
        "the labels are too small",
    ]
    generates = [
        "a four-zone architecture diagram",
        "make a flowchart of the deploy pipeline",
        "create an isometric view of a switch",
        "new diagram showing the data path",
        "draw a sequence diagram",
    ]
    for message in edits:
        got = classify(message, has_previous_image=True)
        assert got.is_edit, f"{message!r} -> {got}"
    for message in generates:
        got = classify(message, has_previous_image=True)
        assert not got.is_edit, f"{message!r} -> {got}"
    # The gate beats every wording.
    assert not classify("make the title bigger", has_previous_image=False).is_edit

    prompt = refine("a four-zone architecture diagram", "make the title bigger.")
    assert "four-zone" in prompt and "make the title bigger" in prompt
    assert "stay identical" in prompt

    print("intent: ok —", len(edits), "edits and", len(generates), "generations routed")
