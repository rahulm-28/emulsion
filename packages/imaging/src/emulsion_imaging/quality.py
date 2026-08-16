"""Score a freshly generated diagram with no reference to compare against.

`score.py` ranks candidates on the crop-composite path, where there *is* a reference:
the parent image. A plain generation has none — K candidates come back and nothing
says which is best. This module supplies the missing judgement.

**Polarity differs from `score.py` deliberately.** `CandidateScore.total` is a penalty
and `rank()` sorts ascending; `DiagramQuality.total` is a quality and
`rank_diagrams()` sorts descending. Two opposite conventions in one package is a
footgun, so the names never overlap: `rank` vs `rank_diagrams`.

What is being measured is *diagram* quality, not beauty. The domain advantage stated in
CLAUDE.md is that flat technical diagrams have whitespace gutters between zones — so a
candidate whose zones are cleanly separated is both a better diagram and cheaper to
edit later, because a region edit can snap to those gutters and skip blending
altogether. That makes gutter structure the heaviest term, and it is the one signal
here a general-purpose image scorer would not think to use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .gutters import column_flatness, flat_runs, row_flatness

# Gutters dominate: they are the domain signal and they decide whether M5 can edit a
# region without blending. Contrast is next — a washed-out diagram is unusable at
# thumbnail size. Ink is a clutter guard, and background flatness separates a diagram
# from something photographic.
WEIGHTS = {"gutters": 0.40, "contrast": 0.25, "ink": 0.20, "background": 0.15}

# ponytail: hand-set constants, tuned against the echo adapter's synthetic diagrams and
# the 4K outputs in ../gpt-image-2/out. They are a prior, not a measurement. Upgrade
# path is to fit them against human picks once the library has enough ranked pairs —
# that is the M7 "learned constraints" loop, and it needs real usage first.
IDEAL_INK = (0.12, 0.45)
TARGET_SEPARATORS = 6
MIN_SEPARATOR_PX = 4


def _luma(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image.astype(np.float64)
    rgb = image[:, :, :3].astype(np.float64)
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def _interior_runs(runs: list[tuple[int, int]], extent: int) -> list[tuple[int, int]]:
    """Drop runs touching an edge — an outer margin is not a gutter between zones."""
    return [
        (start, stop)
        for start, stop in runs
        if start > 0 and stop < extent and (stop - start) >= MIN_SEPARATOR_PX
    ]


def separator_count(image: np.ndarray) -> int:
    """How many clean whitespace channels run through the interior."""
    height, width = _luma(image).shape
    rows = _interior_runs(flat_runs(row_flatness(image)), height)
    cols = _interior_runs(flat_runs(column_flatness(image)), width)
    return len(rows) + len(cols)


def gutter_score(image: np.ndarray) -> float:
    """0..1, saturating once there are enough separators to edit around."""
    return min(separator_count(image), TARGET_SEPARATORS) / TARGET_SEPARATORS


def contrast_score(image: np.ndarray) -> float:
    """Robust luma spread. Percentiles, so a few blown pixels do not score as contrast."""
    luma = _luma(image)
    spread = float(np.percentile(luma, 99) - np.percentile(luma, 1))
    return min(spread / 255.0, 1.0)


def _border_luma(luma: np.ndarray) -> np.ndarray:
    return np.concatenate([luma[0, :], luma[-1, :], luma[:, 0], luma[:, -1]])


def ink_fraction(image: np.ndarray) -> float:
    """Share of pixels that differ from the background tone.

    Background is the modal luma *of the border ring*, not of the whole frame. Using
    the whole frame inverts the measurement on a densely inked image: once the dark
    zones outnumber the light background, the dark becomes modal and a 71%-covered
    diagram reports 29% ink. The border is background in essentially every diagram,
    which is the same assumption the transparency flood fill already relies on.
    """
    luma = _luma(image)
    histogram, _ = np.histogram(_border_luma(luma), bins=32, range=(0, 255))
    modal_bin = int(np.argmax(histogram))
    modal_luma = (modal_bin + 0.5) * (255.0 / 32)
    return float(np.mean(np.abs(luma - modal_luma) > 24))


def ink_score(image: np.ndarray) -> float:
    """1.0 inside the comfortable band, falling off outside it.

    Both failure modes are real: a near-empty frame is a wasted generation, and a
    wall-to-wall one has no gutters left to edit through.
    """
    ink = ink_fraction(image)
    low, high = IDEAL_INK
    if low <= ink <= high:
        return 1.0
    # Each side is scaled by its own headroom. Dividing both by `low` looks tidy and is
    # wrong: it makes anything above ~0.57 ink score exactly zero, so every real
    # diagram ties on this term and ranking silently collapses onto contrast.
    if ink < low:
        return max(0.0, 1.0 - (low - ink) / low)
    return max(0.0, 1.0 - (ink - high) / (1.0 - high))


def background_score(image: np.ndarray) -> float:
    """Flat background reads as a diagram; a noisy one reads as a photograph."""
    return max(0.0, 1.0 - float(np.std(_border_luma(_luma(image)))) / 64.0)


@dataclass(frozen=True)
class DiagramQuality:
    gutters: float
    contrast: float
    ink: float
    background: float
    separators: int
    total: float

    def explain(self) -> str:
        return (
            f"gutters {self.gutters:.2f} ({self.separators} sep) · "
            f"contrast {self.contrast:.2f} · ink {self.ink:.2f} · "
            f"bg {self.background:.2f} → {self.total:.2f}"
        )


def score_diagram(image: np.ndarray) -> DiagramQuality:
    """Judge one candidate on its own, with nothing to compare it to."""
    gutters = gutter_score(image)
    contrast = contrast_score(image)
    ink = ink_score(image)
    background = background_score(image)
    total = (
        WEIGHTS["gutters"] * gutters
        + WEIGHTS["contrast"] * contrast
        + WEIGHTS["ink"] * ink
        + WEIGHTS["background"] * background
    )
    return DiagramQuality(
        gutters=gutters,
        contrast=contrast,
        ink=ink,
        background=background,
        separators=separator_count(image),
        total=total,
    )


def rank_diagrams(scores: list[DiagramQuality]) -> list[int]:
    """Indices best first. Descending — higher is better here, unlike `rank()`.

    Stable, so equally-scored candidates keep generation order and a rerun of the same
    prompt does not reshuffle for no reason.
    """
    return sorted(range(len(scores)), key=lambda i: -scores[i].total)


if __name__ == "__main__":
    rng = np.random.default_rng(0)

    # A diagram: flat background, four zones, clean gutters between them.
    diagram = np.full((256, 256, 3), 250, dtype=np.uint8)
    for top in (16, 140):
        for left in (16, 140):
            diagram[top : top + 100, left : left + 100] = 40

    noise = rng.integers(0, 255, (256, 256, 3), dtype=np.uint8)
    blank = np.full((256, 256, 3), 250, dtype=np.uint8)

    d, n, b = (score_diagram(x) for x in (diagram, noise, blank))
    assert d.total > n.total, f"noise beat the diagram: {n.explain()} vs {d.explain()}"
    assert d.total > b.total, f"blank beat the diagram: {b.explain()} vs {d.explain()}"
    assert d.separators >= 2, d.explain()
    assert b.separators == 0, "an empty frame has no interior separators"
    assert ink_score(blank) < 0.5, "an empty frame should be penalised on ink"

    order = rank_diagrams([n, d, b])
    assert order[0] == 1, order

    print("quality: ok —", d.explain())
