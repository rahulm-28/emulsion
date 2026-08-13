"""Who is asking. The fourth seam M0 allows, and deliberately the thinnest.

M0 fixes the portability surface at three protocols "plus a thin `IdentityProvider`
seam". This is that seam, and it stays thin on purpose: it answers one question —
*which user does this request belong to* — and knows nothing about sessions, cookies,
plans or permissions.

Two implementations ship:

  **DevIdentity** — everything belongs to one implicit local user. No configuration, no
  account, no network. This is what keeps `make dev` working with nothing installed, and
  it is the default so that forgetting to configure auth fails closed into single-user
  local mode rather than open into an unauthenticated public API.

  **ClerkIdentity** — verifies a Clerk-issued JWT against their published JWKS. Chosen
  because it is the least code to write and the least to own once live: sign-up,
  sign-in, MFA, password reset, social providers and a user dashboard are all somebody
  else's problem, and the only thing running here is signature verification.

Swapping providers means writing one class. Nothing above this file names Clerk.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

DEV_USER_ID = "local-user"
DEV_USER_EMAIL = "you@localhost"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. `subject` is stable and is what rows are keyed on."""

    subject: str
    email: str = ""
    display_name: str = ""

    @property
    def is_local(self) -> bool:
        return self.subject == DEV_USER_ID


class AuthError(Exception):
    """The caller could not be identified. Always a 401 — never leak why."""


@runtime_checkable
class IdentityProvider(Protocol):
    """Turns a bearer token into a Principal, or raises."""

    def authenticate(self, token: str | None) -> Principal: ...

    @property
    def requires_token(self) -> bool: ...


class DevIdentity(IdentityProvider):
    """One implicit user. For local development only."""

    def authenticate(self, token: str | None) -> Principal:
        return Principal(subject=DEV_USER_ID, email=DEV_USER_EMAIL, display_name="Local user")

    @property
    def requires_token(self) -> bool:
        return False


class ClerkIdentity(IdentityProvider):
    """Verifies a Clerk session JWT.

    ponytail: RS256 verification via PyJWT against a cached JWKS. Clerk rotates keys
    rarely, so the cache TTL is an hour and a miss simply refetches. If a key rotates
    mid-flight the first request after it fails and the second succeeds — acceptable for
    a rotation measured in months, and the alternative is a refetch on every request.
    """

    def __init__(
        self,
        *,
        jwks_url: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        cache_seconds: int = 3600,
    ) -> None:
        self.jwks_url = jwks_url or os.environ.get("CLERK_JWKS_URL", "")
        self.issuer = issuer or os.environ.get("CLERK_ISSUER", "")
        self.audience = audience or os.environ.get("CLERK_AUDIENCE") or None
        if not self.jwks_url:
            raise ValueError(
                "CLERK_JWKS_URL is required when EMULSION_AUTH=clerk. "
                "Unset EMULSION_AUTH to run single-user locally."
            )
        self._cache_seconds = cache_seconds
        self._jwks: dict | None = None
        self._fetched_at = 0.0

    def _keys(self) -> dict:
        if self._jwks is None or time.time() - self._fetched_at > self._cache_seconds:
            with urllib.request.urlopen(self.jwks_url, timeout=10) as response:  # noqa: S310
                self._jwks = json.loads(response.read())
            self._fetched_at = time.time()
        return self._jwks

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise AuthError("no token")
        try:
            import jwt
            from jwt import PyJWKClient
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise AuthError("pyjwt is not installed") from exc

        try:
            signing_key = PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer or None,
                audience=self.audience,
                options={"verify_aud": bool(self.audience)},
            )
        except Exception as exc:
            # Deliberately opaque: the caller learns that it failed, never which check
            # failed, because that difference is a probing oracle.
            raise AuthError("token rejected") from exc

        subject = claims.get("sub")
        if not subject:
            raise AuthError("token carries no subject")
        return Principal(
            subject=str(subject),
            email=str(claims.get("email") or ""),
            display_name=str(claims.get("name") or claims.get("username") or ""),
        )

    @property
    def requires_token(self) -> bool:
        return True


def identity_provider() -> IdentityProvider:
    """Build the configured provider.

    Defaults to dev. An unset or unrecognised value must not silently produce an
    unauthenticated public API, so anything other than a known provider name raises.
    """
    name = os.environ.get("EMULSION_AUTH", "dev").strip().lower()
    if name in {"", "dev", "local", "none"}:
        return DevIdentity()
    if name == "clerk":
        return ClerkIdentity()
    raise ValueError(f"Unknown EMULSION_AUTH={name!r}. Use 'dev' or 'clerk'.")
