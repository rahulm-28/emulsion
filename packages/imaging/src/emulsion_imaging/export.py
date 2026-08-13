"""Post-processing: transparency, format conversion, upscale.

`gpt-image-2` cannot return transparency — it is a hard model limitation, not a
parameter we forgot. For a diagram that is a real problem: a picture destined for a
slide needs to sit on the deck's background, not on the white rectangle it was born on.

So transparency is recovered here instead. On a photograph that would be hopeless; on a
flat diagram the background is a single near-uniform colour reachable from the border,
which makes it a flood fill rather than a segmentation problem. The same property that
makes region edits work makes this work.
"""

from __future__ import annotations

import io
from collections import deque
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image

# How far a pixel may drift from the sampled background and still count as background.
# Generous enough for JPEG ringing and anti-aliased edges, tight enough that a pale
# fill inside a diagram is not eaten.
DEFAULT_TOLERANCE = 12.0

FORMATS = {
    "png": ("PNG", "image/png"),
    "webp": ("WEBP", "image/webp"),
    "jpeg": ("JPEG", "image/jpeg"),
}


# Corners disagreeing by more than this means there is no single background colour —
# a gradient, a photo, a full-bleed illustration. Above it, knocking out "the
# background" is meaningless and the caller is told rather than handed garbage.
FLAT_BACKGROUND_SPREAD = 24.0


@dataclass(frozen=True)
class Exported:
    data: bytes
    width: int
    height: int
    content_type: str
    has_alpha: bool
    # False when the source had no uniform background to remove.
    background_uniform: bool = True


def _corner_colour(image: np.ndarray) -> np.ndarray:
    """Median of the four corners. Median rather than mean so one stray corner — a
    logo, a rounded edge — does not drag the estimate off the true background."""
    h, w = image.shape[:2]
    patch = 8
    corners = np.concatenate(
        [
            image[:patch, :patch].reshape(-1, image.shape[2]),
            image[:patch, -patch:].reshape(-1, image.shape[2]),
            image[-patch:, :patch].reshape(-1, image.shape[2]),
            image[-patch:, -patch:].reshape(-1, image.shape[2]),
        ]
    )
    return np.median(corners[:, :3], axis=0)


def background_spread(image: np.ndarray) -> float:
    """How much the four corner patches disagree, in 0-255 units.

    A flat diagram sits near zero. A gradient or a photograph does not, and on those the
    whole premise of "remove the background" fails: the sampled colour matches some band
    through the middle of the picture instead of its edges, and the flood fill eats the
    subject. Measuring this is the difference between a wrong answer and a refusal.
    """
    h, w = image.shape[:2]
    patch = max(2, min(8, h // 4, w // 4))
    corners = [
        image[:patch, :patch, :3],
        image[:patch, -patch:, :3],
        image[-patch:, :patch, :3],
        image[-patch:, -patch:, :3],
    ]
    means = np.stack([c.reshape(-1, 3).mean(axis=0) for c in corners])
    return float(np.abs(means.max(axis=0) - means.min(axis=0)).max())


def has_flat_background(image: np.ndarray, threshold: float = FLAT_BACKGROUND_SPREAD) -> bool:
    return background_spread(image) <= threshold


def background_mask(image: np.ndarray, tolerance: float = DEFAULT_TOLERANCE) -> np.ndarray:
    """True where the pixel is background *connected to the border*.

    Connectivity is the whole point. A white box drawn inside the diagram is the same
    colour as the background, and a plain colour-threshold would punch a hole through
    it. Only what the border can reach becomes transparent.
    """
    rgb = image[..., :3].astype(np.float32)
    background = _corner_colour(image)
    close = np.abs(rgb - background).max(axis=2) <= tolerance

    height, width = close.shape
    reachable = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    for x in range(width):
        for y in (0, height - 1):
            if close[y, x] and not reachable[y, x]:
                reachable[y, x] = True
                queue.append((y, x))
    for y in range(height):
        for x in (0, width - 1):
            if close[y, x] and not reachable[y, x]:
                reachable[y, x] = True
                queue.append((y, x))

    # Row-wise flood fill: expand each popped pixel along its scanline in one slice,
    # then only queue the rows above and below. Pixel-at-a-time BFS on a 4K image is
    # tens of millions of Python iterations; this is a few thousand.
    while queue:
        y, x = queue.popleft()
        left = x
        while left > 0 and close[y, left - 1] and not reachable[y, left - 1]:
            left -= 1
            reachable[y, left] = True
        right = x
        while right < width - 1 and close[y, right + 1] and not reachable[y, right + 1]:
            right += 1
            reachable[y, right] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < height:
                span = close[ny, left : right + 1] & ~reachable[ny, left : right + 1]
                for offset in np.flatnonzero(span):
                    nx = left + int(offset)
                    reachable[ny, nx] = True
                    queue.append((ny, nx))
    return reachable


def make_transparent(image: np.ndarray, tolerance: float = DEFAULT_TOLERANCE) -> np.ndarray:
    """RGBA with border-connected background knocked out.

    ponytail: a binary mask, so edges anti-aliased against the old background keep a
    faint halo of it. Fine on flat vector output, visible on a soft-edged photo. The
    upgrade is alpha estimated from distance to the background colour rather than a
    hard threshold; this stays binary because a diagram's edges are one pixel wide.
    """
    mask = background_mask(image, tolerance)
    rgba = np.dstack([image[..., :3], np.full(image.shape[:2], 255, dtype=np.uint8)])
    rgba[mask, 3] = 0
    return rgba


def upscale(image: np.ndarray, factor: float) -> np.ndarray:
    """Lanczos resample.

    ponytail: resampling, not super-resolution — it makes an image larger without
    inventing detail, which is honest but is not what "upscale" implies to everyone.
    Real upscaling is a model call and belongs behind the provider layer with its own
    manifest entry. Kept because exporting a 1k diagram at 2x for a slide is a genuine
    need and Lanczos is the right answer to it.
    """
    if factor <= 0:
        raise ValueError(f"upscale factor must be positive, got {factor}")
    height, width = image.shape[:2]
    target = (max(1, round(width * factor)), max(1, round(height * factor)))
    mode = "RGBA" if image.shape[2] == 4 else "RGB"
    return np.array(Image.fromarray(image, mode=mode).resize(target, Image.LANCZOS), dtype=np.uint8)


def encode(image: np.ndarray, fmt: str, *, quality: int = 90) -> Exported:
    """Encode to png / webp / jpeg, dropping alpha where the format cannot carry it."""
    key = fmt.lower()
    if key == "jpg":
        key = "jpeg"
    if key not in FORMATS:
        raise ValueError(f"unsupported format {fmt!r}; use one of {', '.join(FORMATS)}")
    pillow_format, content_type = FORMATS[key]

    has_alpha = image.shape[2] == 4
    if has_alpha and key == "jpeg":
        # JPEG has no alpha. Compositing onto white rather than silently dropping the
        # channel, because dropping it turns transparent pixels black.
        rgb = image[..., :3].astype(np.float32)
        alpha = (image[..., 3:4].astype(np.float32)) / 255.0
        image = np.clip(rgb * alpha + 255.0 * (1 - alpha), 0, 255).astype(np.uint8)
        has_alpha = False

    picture = Image.fromarray(image, mode="RGBA" if has_alpha else "RGB")
    buffer = io.BytesIO()
    if key == "png":
        picture.save(buffer, format=pillow_format, optimize=True)
    else:
        picture.save(buffer, format=pillow_format, quality=quality)

    return Exported(
        data=buffer.getvalue(),
        width=picture.width,
        height=picture.height,
        content_type=content_type,
        has_alpha=has_alpha,
    )


def export(
    original: bytes,
    *,
    fmt: str = "png",
    transparent: bool = False,
    scale: float = 1.0,
    tolerance: float = DEFAULT_TOLERANCE,
    quality: int = 90,
) -> Exported:
    """Full post-processing pass over encoded bytes.

    Order matters: knock out the background before scaling, so the flood fill runs on
    original pixels rather than on interpolated ones that have drifted away from the
    background colour.
    """
    with Image.open(io.BytesIO(original)) as opened:
        array = np.array(opened.convert("RGB"), dtype=np.uint8)

    uniform = True
    if transparent:
        uniform = has_flat_background(array)
        if uniform:
            array = make_transparent(array, tolerance)
        # When it is not uniform the image is returned untouched: silently producing a
        # mask that removes the subject is worse than producing no mask at all.
    if scale != 1.0:
        array = upscale(array, scale)

    result = encode(array, fmt, quality=quality)
    return replace(result, background_uniform=uniform)
