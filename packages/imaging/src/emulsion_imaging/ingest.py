"""Validate untrusted images before they enter the RGB editing pipeline."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_PIXELS = 32_000_000


@dataclass(frozen=True)
class ImportedImage:
    data: bytes
    width: int
    height: int
    flattened_alpha: bool


def normalise_upload(data: bytes) -> ImportedImage:
    """Decode pixels, not the declared MIME type. Strip metadata and orient once."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Choose an image between 1 byte and 50 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Choose a PNG, JPEG, or WebP image.")
                if source.width * source.height > MAX_UPLOAD_PIXELS:
                    raise ValueError("This image is too large. Use an image up to 32 megapixels.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported. Upload a still image.")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                rgba = oriented.convert("RGBA")
                flattened = alpha and rgba.getchannel("A").getextrema()[0] < 255
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                output = io.BytesIO()
                rgb.save(output, format="PNG")
                encoded = output.getvalue()
                if len(encoded) > MAX_UPLOAD_BYTES:
                    raise ValueError(
                        "The decoded image is too large to edit. Upload a smaller image."
                    )
                return ImportedImage(encoded, rgb.width, rgb.height, flattened)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("This image is too large. Use an image up to 32 megapixels.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(
            "This file could not be read as an image. Try another PNG, JPEG, or WebP."
        ) from exc
