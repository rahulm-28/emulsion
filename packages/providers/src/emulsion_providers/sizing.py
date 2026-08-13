"""Resolve and validate output dimensions against a model's declared pixel rules.

Ported from ../gpt-image-2/generate.py with one deliberate change: these raise
ValueError, not SystemExit. This is a library, not a CLI (CLAUDE.md invariant 2) —
the caller decides whether a bad size is a 400 to the user or a crash.

Nothing here knows which model it is looking at. It reads PixelRules.
"""

from __future__ import annotations

from .manifest import PixelRules

SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "4k-uhd": (3840, 2160),
    "4k-square": (2880, 2880),
    "4k-portrait": (2160, 3840),
    "2k": (2048, 2048),
    "1k": (1024, 1024),
}


def validate_size(width: int, height: int, pixels: PixelRules) -> None:
    """Raise ValueError with a specific reason if (width, height) breaks the rules."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid size {width}x{height}: dimensions must be positive.")

    if pixels.multiple_of > 1:
        for name, value in (("width", width), ("height", height)):
            if value % pixels.multiple_of:
                raise ValueError(
                    f"Invalid size {width}x{height}: {name} must be a multiple of "
                    f"{pixels.multiple_of}."
                )

    long_edge = max(width, height)
    if long_edge > pixels.long_edge:
        raise ValueError(
            f"Invalid size {width}x{height}: long edge {long_edge} exceeds max {pixels.long_edge}."
        )

    ratio = width / height
    lo, hi = pixels.aspect
    if not lo <= ratio <= hi:
        raise ValueError(
            f"Invalid size {width}x{height}: aspect ratio {ratio:.3f} outside "
            f"allowed range {lo}–{hi}."
        )

    count = width * height
    if count < pixels.min:
        raise ValueError(
            f"Invalid size {width}x{height}: {count} pixels is below min {pixels.min}."
        )
    if count > pixels.max:
        raise ValueError(f"Invalid size {width}x{height}: {count} pixels exceeds max {pixels.max}.")


def resolve_size(spec: str, pixels: PixelRules) -> tuple[int, int]:
    """Turn a preset name or a 'WxH' string into validated (width, height)."""
    if spec in SIZE_PRESETS:
        width, height = SIZE_PRESETS[spec]
    else:
        width, height = _parse_wxh(spec)
    validate_size(width, height, pixels)
    return width, height


def _parse_wxh(spec: str) -> tuple[int, int]:
    parts = spec.lower().split("x")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    raise ValueError(
        f"Invalid size {spec!r}. Use a preset ({', '.join(SIZE_PRESETS)}) "
        f"or raw WxH (e.g. 2048x1152)."
    )
