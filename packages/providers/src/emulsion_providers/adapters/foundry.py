"""Azure AI Foundry / OpenAI-compatible image adapter.

Everything here that looks arbitrary was measured against a live deployment on
2026-08-12 or earned in `../gpt-image-2/generate.py` over three months. See the
manifest YAML for per-field provenance.

Credential handling, in order of importance:
  * the key is never logged, never echoed into an exception, never returned;
  * error messages are built from status codes and the provider's own error text;
  * the endpoint host is redacted in anything user-facing.
"""

from __future__ import annotations

import base64
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..manifest import Manifest, load_manifest
from ..parts import ImagePart, MaskPart, Request, TextPart, split_parts
from ..throttle import TokenBucket, retry_delay
from .base import (
    GeneratedImage,
    GenerationParams,
    ProgressFn,
    ProviderError,
    Result,
)

REQUEST_TIMEOUT_S = 300.0


def redact_host(text: str) -> str:
    """Replace any https host with a placeholder. Applied to everything user-facing."""
    return re.sub(r"https://[^/\s]+", "https://<host>", text)


def _endpoint_pair(endpoint: str, api_version: str) -> tuple[str, str]:
    """Derive (generations_url, edits_url) from a configured endpoint.

    Accepts the full generations URL the predecessor CLI already uses, with or without
    a query string, and pins the api-version to the manifest's.
    """
    parts = urlsplit(endpoint)
    path = parts.path
    if "/images/" not in path:
        path = path.rstrip("/") + "/images/generations"
    gen_path = re.sub(r"/images/(generations|edits)", "/images/generations", path)
    edit_path = re.sub(r"/images/(generations|edits)", "/images/edits", path)
    query = f"api-version={api_version}"
    base = (parts.scheme, parts.netloc)
    return (
        urlunsplit((*base, gen_path, query, "")),
        urlunsplit((*base, edit_path, query, "")),
    )


class FoundryAdapter:
    """Calls `/images/generations` or `/images/edits` depending on the parts it is given."""

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        manifest: Manifest | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.manifest = manifest or load_manifest("gpt-image-2")
        endpoint = endpoint or os.environ.get("AZURE_ENDPOINT", "")
        if not endpoint:
            raise ProviderError(
                "No endpoint configured. Set AZURE_ENDPOINT, or use the echo adapter "
                "(EMULSION_ADAPTER=echo) to run without a provider."
            )
        self._api_key = api_key or os.environ.get("AZURE_API_KEY", "")
        if not self._api_key:
            # ponytail: key auth only. The hosted tier is meant to use managed identity
            # (DefaultAzureCredential + get_bearer_token_provider, scope
            # https://cognitiveservices.azure.com/.default). That needs `azure-identity`
            # and a logged-in principal; add it when the platform tier exists (M8).
            raise ProviderError("No credential configured. Set AZURE_API_KEY.")
        self.generations_url, self.edits_url = _endpoint_pair(endpoint, self.manifest.api_version)
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_S)
        self._bucket = TokenBucket(self.manifest.rate_limit)

    # -- headers ---------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        """Both shapes authenticate on this deployment; `api-key` is the Azure norm."""
        if "api-key" in self.manifest.auth_headers:
            return {"api-key": self._api_key}
        return {"Authorization": f"Bearer {self._api_key}"}

    # -- request assembly ------------------------------------------------------

    def _fields(self, prompt: str, params: GenerationParams) -> dict[str, str]:
        fields = {
            "prompt": prompt,
            "size": f"{params.width}x{params.height}",
            "quality": params.quality,
            "n": str(params.n),
            "output_format": params.output_format,
        }
        # The manifest says what this model refuses; never send it (invariant 3 — the
        # rule lives in data, not in an `if model ==` here).
        for name in self.manifest.unsupported_params:
            fields.pop(name, None)
        return fields

    def submit(
        self,
        request: Request,
        params: GenerationParams,
        *,
        blobs: dict[str, bytes] | None = None,
        on_progress: ProgressFn | None = None,
    ) -> Result:
        blobs = blobs or {}
        kept, dropped = split_parts(request, self.manifest)

        prompt = "\n".join(p.text for p in kept if isinstance(p, TextPart))
        images = [p for p in kept if isinstance(p, ImagePart)]
        masks = [p for p in kept if isinstance(p, MaskPart)]

        if images:
            payload = self._call_edits(prompt, params, images, masks, blobs, on_progress)
        else:
            payload = self._call_generations(prompt, params, on_progress)

        usage = payload.get("usage") or {}
        return Result(
            images=self._decode(payload, params),
            dropped=dropped,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    # -- transport -------------------------------------------------------------

    def _call_generations(
        self, prompt: str, params: GenerationParams, on_progress: ProgressFn | None
    ) -> dict:
        body = self._fields(prompt, params)
        body["n"] = params.n  # type: ignore[assignment] - JSON wants a number here
        return self._send(
            lambda: self._client.post(
                self.generations_url,
                json=body,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
            ),
            on_progress,
        )

    def _call_edits(
        self,
        prompt: str,
        params: GenerationParams,
        images: list[ImagePart],
        masks: list[MaskPart],
        blobs: dict[str, bytes],
        on_progress: ProgressFn | None,
    ) -> dict:
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, part in enumerate(images):
            data = blobs.get(part.blob_id)
            if data is None:
                raise ProviderError(f"missing bytes for image part {part.blob_id!r}")
            files.append(("image[]", (f"image_{index}.png", data, "image/png")))
        for part in masks:
            data = blobs.get(part.blob_id)
            if data is not None:
                files.append(("mask", ("mask.png", data, "image/png")))

        return self._send(
            lambda: self._client.post(
                self.edits_url,
                data=self._fields(prompt, params),
                files=files,
                headers=self._auth_headers(),
            ),
            on_progress,
        )

    def _send(self, call, on_progress: ProgressFn | None) -> dict:  # noqa: ANN001
        attempt = 0
        while True:
            waited = self._bucket.acquire()
            if waited and on_progress:
                on_progress(f"waiting {waited:.0f}s for the provider rate limit")

            try:
                response = call()
            except httpx.TimeoutException as exc:
                raise ProviderError(f"provider timed out after {REQUEST_TIMEOUT_S:.0f}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"network error: {redact_host(str(exc))}") from exc

            if response.status_code == 200:
                return response.json()

            delay = retry_delay(
                response.status_code,
                attempt,
                retry_after=_retry_after(response),
            )
            if delay is None:
                raise ProviderError(
                    f"provider returned {response.status_code}: "
                    f"{redact_host(_error_text(response))}",
                    status=response.status_code,
                )
            if on_progress:
                on_progress(f"provider returned {response.status_code}; retrying in {delay:.0f}s")
            time.sleep(delay)
            attempt += 1

    def _decode(self, payload: dict, params: GenerationParams) -> list[GeneratedImage]:
        items = payload.get("data") or []
        if not items:
            raise ProviderError("provider returned no images")
        out: list[GeneratedImage] = []
        for index, item in enumerate(items):
            encoded = item.get("b64_json")
            if not encoded:
                raise ProviderError(f"provider result {index} carried no image data")
            out.append(
                GeneratedImage(
                    data=base64.b64decode(encoded),
                    width=params.width,
                    height=params.height,
                    content_type=f"image/{params.output_format}",
                )
            )
        return out


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("message", ""))[:500]
    except Exception:
        return response.text[:500]
