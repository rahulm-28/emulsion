"""Invariant 7: adapters drop what they cannot send, and say so."""

import pytest
from emulsion_providers import (
    ImagePart,
    MaskPart,
    MaskSupport,
    RegionPart,
    Request,
    TextPart,
    load_manifest,
    split_parts,
)

GPT_IMAGE_2 = load_manifest("gpt-image-2")


def test_text_and_images_survive():
    req = Request(
        parts=[
            TextPart(text="a wiring diagram"),
            ImagePart(role="source", blob_id="blob-1"),
            ImagePart(role="reference", blob_id="blob-2"),
        ]
    )
    kept, dropped = split_parts(req, GPT_IMAGE_2)
    assert len(kept) == 3
    assert dropped == []


def test_region_never_reaches_a_provider():
    req = Request(parts=[RegionPart(bbox=(0, 0, 100, 100))])
    kept, dropped = split_parts(req, GPT_IMAGE_2)
    assert kept == []
    assert [d.kind for d in dropped] == ["region"]
    assert "engine" in dropped[0].reason


def test_mask_is_kept_when_support_is_soft():
    # Soft means unreliable, not unusable. M5 decides whether to trust it; the adapter
    # is not the place to second-guess the manifest.
    assert GPT_IMAGE_2.mask_support is MaskSupport.SOFT
    kept, dropped = split_parts(Request(parts=[MaskPart(blob_id="m")]), GPT_IMAGE_2)
    assert len(kept) == 1
    assert dropped == []


def test_mask_is_dropped_when_unsupported():
    no_mask = GPT_IMAGE_2.model_copy(update={"mask_support": MaskSupport.NONE})
    kept, dropped = split_parts(Request(parts=[MaskPart(blob_id="m")]), no_mask)
    assert kept == []
    assert dropped[0].kind == "mask"


def test_references_beyond_the_cap_are_dropped_and_reported():
    cap = GPT_IMAGE_2.multi_reference
    req = Request(parts=[ImagePart(role="reference", blob_id=f"b{i}") for i in range(cap + 3)])
    kept, dropped = split_parts(req, GPT_IMAGE_2)
    assert len(kept) == cap
    assert len(dropped) == 3
    assert all(str(cap) in d.reason for d in dropped)


def test_source_image_does_not_count_against_the_reference_cap():
    cap = GPT_IMAGE_2.multi_reference
    parts = [ImagePart(role="source", blob_id="src")]
    parts += [ImagePart(role="reference", blob_id=f"b{i}") for i in range(cap)]
    kept, dropped = split_parts(Request(parts=parts), GPT_IMAGE_2)
    assert len(kept) == cap + 1
    assert dropped == []


def test_text_only_model_drops_images():
    text_only = GPT_IMAGE_2.model_copy(update={"modalities_in": ["text"]})
    req = Request(parts=[TextPart(text="hi"), ImagePart(role="source", blob_id="b")])
    kept, dropped = split_parts(req, text_only)
    assert [p.kind for p in kept] == ["text"]
    assert [d.kind for d in dropped] == ["image"]


def test_every_dropped_part_carries_a_reason():
    req = Request(
        parts=[
            RegionPart(bbox=(0, 0, 10, 10)),
            *[
                ImagePart(role="reference", blob_id=f"b{i}")
                for i in range(GPT_IMAGE_2.multi_reference + 1)
            ],
        ]
    )
    _, dropped = split_parts(req, GPT_IMAGE_2)
    assert dropped
    assert all(d.reason.strip() for d in dropped)


def test_parts_deserialize_by_discriminator():
    req = Request.model_validate(
        {"parts": [{"kind": "text", "text": "x"}, {"kind": "region", "bbox": [0, 0, 8, 8]}]}
    )
    assert isinstance(req.parts[0], TextPart)
    assert isinstance(req.parts[1], RegionPart)


def test_unknown_part_kind_is_rejected():
    with pytest.raises(ValueError, match="kind"):
        Request.model_validate({"parts": [{"kind": "audio", "blob_id": "a"}]})
