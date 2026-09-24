import io

import pytest
from emulsion_imaging.ingest import normalise_upload
from PIL import Image


def encoded(image, fmt="PNG", **kwargs):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def test_applies_exif_orientation_and_strips_metadata():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private metadata"
    result = normalise_upload(encoded(Image.new("RGB", (80, 40)), "JPEG", exif=exif))
    assert (result.width, result.height) == (40, 80)
    with Image.open(io.BytesIO(result.data)) as image:
        assert not image.getexif()


def test_transparency_is_flattened_on_white_and_reported():
    result = normalise_upload(encoded(Image.new("RGBA", (4, 4), (0, 0, 0, 0))))
    assert result.flattened_alpha
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_opaque_pixels_are_preserved_exactly():
    source = Image.new("RGB", (7, 9), (17, 39, 151))
    result = normalise_upload(encoded(source))
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.tobytes() == source.tobytes()
    assert not result.flattened_alpha


def test_rejects_animation():
    first = Image.new("RGB", (10, 10), "red")
    second = Image.new("RGB", (10, 10), "blue")
    data = encoded(first, "WEBP", save_all=True, append_images=[second], duration=100)
    with pytest.raises(ValueError, match="Animated"):
        normalise_upload(data)


def test_checks_dimensions_before_decoding(monkeypatch):
    monkeypatch.setattr("emulsion_imaging.ingest.MAX_UPLOAD_PIXELS", 10)
    with pytest.raises(ValueError, match="megapixels"):
        normalise_upload(encoded(Image.new("RGB", (4, 4))))
