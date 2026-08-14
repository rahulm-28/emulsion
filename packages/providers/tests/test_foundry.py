"""The real-model adapter, exercised offline against a mocked transport.

This is the one path that costs money to run for real, which is exactly why it needs
covering without running it for real. Everything here is the actual request the adapter
would put on the wire — URL, headers, body, multipart shape — checked against what the
deployment was measured to accept on 2026-08-12.

The credential assertions are the important ones. A key that leaks into an exception
message ends up in a log aggregator, and BYOK keys are write-only by invariant 6.
"""

import base64
import struct
import zlib

import httpx
import pytest
from emulsion_providers import ImagePart, Request, TextPart, load_manifest
from emulsion_providers.adapters import get_adapter
from emulsion_providers.adapters.base import GenerationParams, ProviderError
from emulsion_providers.adapters.foundry import FoundryAdapter, _endpoint_pair, redact_host

ENDPOINT = "https://my-resource.openai.azure.com/openai/deployments/gpt-image-2/images/generations?api-version=2024-02-01"
SECRET = "super-secret-key-value-0123456789"
MANIFEST = load_manifest("gpt-image-2")


def tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes([0, 255, 255, 255]), 6)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def ok_payload(n: int = 1) -> dict:
    encoded = base64.b64encode(tiny_png()).decode()
    return {
        "data": [{"b64_json": encoded} for _ in range(n)],
        "usage": {"input_tokens": 19, "output_tokens": 107 * n},
    }


def build(handler, **kwargs) -> tuple[FoundryAdapter, list[httpx.Request]]:
    """An adapter wired to a mock transport, plus the list of requests it sends."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request, len(seen))

    client = httpx.Client(transport=httpx.MockTransport(record))
    adapter = FoundryAdapter(endpoint=ENDPOINT, api_key=SECRET, client=client, **kwargs)
    return adapter, seen


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Retry backoff is measured in seconds; the test should not be."""
    monkeypatch.setattr("emulsion_providers.adapters.foundry.time.sleep", lambda _: None)
    monkeypatch.setattr("emulsion_providers.throttle.time.sleep", lambda _: None)


PARAMS = GenerationParams(width=1024, height=640, n=1, quality="low")
TEXT = Request(parts=[TextPart(text="a four-zone diagram")])


# -- URL and api-version --------------------------------------------------------------


def test_one_api_version_covers_both_endpoints():
    """Measured: 2025-04-01-preview works on generations and edits, so the predecessor
    CLI's per-endpoint URL rewrite is unnecessary."""
    generations, edits = _endpoint_pair(ENDPOINT, "2025-04-01-preview")
    assert generations.endswith("/images/generations?api-version=2025-04-01-preview")
    assert edits.endswith("/images/edits?api-version=2025-04-01-preview")


def test_the_configured_api_version_is_overridden_by_the_manifest():
    """The endpoint string carries 2024-02-01, which 404s on edits. The manifest wins."""
    adapter, _ = build(lambda r, i: httpx.Response(200, json=ok_payload()))
    assert MANIFEST.api_version in adapter.generations_url
    assert "2024-02-01" not in adapter.generations_url


def test_a_bare_endpoint_without_a_path_still_works():
    generations, edits = _endpoint_pair("https://host/openai/deployments/m", "v1")
    assert "/images/generations" in generations
    assert "/images/edits" in edits


# -- request assembly -----------------------------------------------------------------


def test_generation_sends_json_with_the_api_key_header():
    adapter, seen = build(lambda r, i: httpx.Response(200, json=ok_payload()))
    adapter.submit(TEXT, PARAMS)

    request = seen[0]
    assert request.method == "POST"
    assert "/images/generations" in str(request.url)
    # Both header shapes authenticate; api-key is the Azure norm and what the manifest
    # lists first.
    assert request.headers["api-key"] == SECRET
    assert "authorization" not in request.headers

    body = request.read().decode()
    assert '"size": "1024x640"' in body.replace("'", '"') or "1024x640" in body
    assert "a four-zone diagram" in body


def test_unsupported_params_are_never_sent():
    """input_fidelity is a hard model-level rejection. The manifest says so, and the
    adapter drops it from data rather than from an `if model ==` branch."""
    adapter, seen = build(lambda r, i: httpx.Response(200, json=ok_payload()))
    adapter.submit(TEXT, PARAMS)
    assert "input_fidelity" not in seen[0].read().decode()
    assert "input_fidelity" in MANIFEST.unsupported_params


def test_an_image_part_routes_to_edits_as_multipart():
    adapter, seen = build(lambda r, i: httpx.Response(200, json=ok_payload()))
    request = Request(
        parts=[TextPart(text="recolour it"), ImagePart(role="source", blob_id="crop")]
    )
    adapter.submit(request, PARAMS, blobs={"crop": tiny_png()})

    sent = seen[0]
    assert "/images/edits" in str(sent.url)
    assert sent.headers["content-type"].startswith("multipart/form-data")
    body = sent.read()
    assert b'name="image[]"' in body
    assert b"\x89PNG" in body


def test_an_edit_without_its_bytes_fails_loudly():
    adapter, _ = build(lambda r, i: httpx.Response(200, json=ok_payload()))
    request = Request(parts=[ImagePart(role="source", blob_id="missing")])
    with pytest.raises(ProviderError, match="missing bytes"):
        adapter.submit(request, PARAMS, blobs={})


# -- responses ------------------------------------------------------------------------


def test_images_and_usage_are_decoded():
    adapter, _ = build(lambda r, i: httpx.Response(200, json=ok_payload(n=2)))
    result = adapter.submit(TEXT, GenerationParams(width=1024, height=640, n=2))

    assert len(result.images) == 2
    assert all(i.data.startswith(b"\x89PNG") for i in result.images)
    assert result.input_tokens == 19
    assert result.output_tokens == 214


def test_n_equals_two_is_a_single_request():
    """Measured: two images come back from one call, one rate-limit slot. This is what
    makes candidate generation affordable."""
    adapter, seen = build(lambda r, i: httpx.Response(200, json=ok_payload(n=2)))
    adapter.submit(TEXT, GenerationParams(width=1024, height=640, n=2))
    assert len(seen) == 1


def test_an_empty_data_array_is_an_error_not_an_empty_success():
    adapter, _ = build(lambda r, i: httpx.Response(200, json={"data": []}))
    with pytest.raises(ProviderError, match="no images"):
        adapter.submit(TEXT, PARAMS)


# -- retry ----------------------------------------------------------------------------


def test_a_429_is_retried_and_then_succeeds():
    def handler(request, attempt):
        if attempt == 1:
            return httpx.Response(429, headers={"retry-after": "11"}, json={"error": {}})
        return httpx.Response(200, json=ok_payload())

    adapter, seen = build(handler)
    result = adapter.submit(TEXT, PARAMS)
    assert len(seen) == 2
    assert len(result.images) == 1


def test_a_persistent_429_eventually_gives_up():
    adapter, seen = build(lambda r, i: httpx.Response(429, json={"error": {}}))
    with pytest.raises(ProviderError) as exc:
        adapter.submit(TEXT, PARAMS)
    assert exc.value.status == 429
    assert len(seen) == 4  # the initial call plus three backoff attempts


def test_a_400_is_not_retried():
    """A bad request fails identically on retry; retrying just spends the rate limit."""
    adapter, seen = build(lambda r, i: httpx.Response(400, json={"error": {"message": "bad size"}}))
    with pytest.raises(ProviderError, match="bad size"):
        adapter.submit(TEXT, PARAMS)
    assert len(seen) == 1


def test_a_5xx_is_retried_once():
    adapter, seen = build(lambda r, i: httpx.Response(503, json={"error": {}}))
    with pytest.raises(ProviderError):
        adapter.submit(TEXT, PARAMS)
    assert len(seen) == 2


def test_a_timeout_becomes_a_readable_error():
    def handler(request, attempt):
        raise httpx.TimeoutException("too slow")

    adapter, _ = build(handler)
    with pytest.raises(ProviderError, match="timed out"):
        adapter.submit(TEXT, PARAMS)


# -- credentials never leak (invariant 6) ---------------------------------------------


def test_the_key_never_appears_in_an_error_message():
    adapter, _ = build(
        lambda r, i: httpx.Response(400, json={"error": {"message": f"bad key {SECRET}"}})
    )
    with pytest.raises(ProviderError) as exc:
        adapter.submit(TEXT, PARAMS)
    # The provider echoed the key back at us. It must not survive into our exception,
    # because that string ends up in a log aggregator (invariant 6).
    assert SECRET not in str(exc.value)
    assert "<redacted>" in str(exc.value)


def test_the_endpoint_host_is_redacted_in_errors():
    adapter, _ = build(
        lambda r, i: httpx.Response(
            500, json={"error": {"message": f"upstream {ENDPOINT} exploded"}}
        )
    )
    with pytest.raises(ProviderError) as exc:
        adapter.submit(TEXT, PARAMS)
    assert "my-resource.openai.azure.com" not in str(exc.value)
    assert "https://<host>" in str(exc.value)


def test_redact_host_leaves_paths_intact():
    assert redact_host("see https://a.b.com/x/y?z=1") == "see https://<host>/x/y?z=1"


# -- configuration --------------------------------------------------------------------


def test_a_missing_endpoint_points_at_the_free_alternative(monkeypatch):
    monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
    with pytest.raises(ProviderError, match="echo"):
        FoundryAdapter(api_key=SECRET)


def test_a_missing_key_is_refused(monkeypatch):
    monkeypatch.delenv("AZURE_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="No credential"):
        FoundryAdapter(endpoint=ENDPOINT)


def test_get_adapter_defaults_to_echo_so_nothing_costs_money_by_accident():
    assert type(get_adapter()).__name__ == "EchoAdapter"
    assert type(get_adapter("echo")).__name__ == "EchoAdapter"


def test_get_adapter_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="Unknown adapter"):
        get_adapter("stable-diffusion")
