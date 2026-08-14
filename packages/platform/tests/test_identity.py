"""The identity seam, verified against a locally generated key pair.

No Clerk account, no network. A real RSA key signs real tokens and `ClerkIdentity`
verifies them, so the signature path, the expiry check, the issuer check and the
failure modes are all exercised before anybody creates an account.

The negative cases matter more than the positive one. A verifier that accepts a token
signed by the wrong key, or an expired one, is worse than no verifier at all — it looks
like security while providing none.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from emulsion_platform import (
    DEV_USER_ID,
    AuthError,
    ClerkIdentity,
    DevIdentity,
    Principal,
    identity_provider,
)

ISSUER = "https://example.clerk.accounts.dev"


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, other


class FakeSigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwkClient:
    """Stands in for PyJWKClient, returning one fixed public key."""

    def __init__(self, public_key):
        self._key = FakeSigningKey(public_key)
        self.calls = 0

    def get_signing_key_from_jwt(self, token):  # noqa: ANN001
        self.calls += 1
        return self._key


@pytest.fixture
def clerk(keys):
    private, _ = keys
    return ClerkIdentity(
        issuer=ISSUER, jwk_client=FakeJwkClient(private.public_key()), jwks_url="unused"
    )


def make_token(private, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user_2abc",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "email": "someone@example.com",
        "name": "Someone",
    } | overrides
    return jwt.encode(claims, private, algorithm="RS256")


# -- dev identity ---------------------------------------------------------------------


def test_dev_identity_needs_no_token():
    principal = DevIdentity().authenticate(None)
    assert principal.subject == DEV_USER_ID
    assert principal.is_local
    assert DevIdentity().requires_token is False


def test_the_default_provider_is_dev_so_a_misconfiguration_fails_closed(monkeypatch):
    monkeypatch.delenv("EMULSION_AUTH", raising=False)
    assert isinstance(identity_provider(), DevIdentity)


def test_an_unknown_provider_name_raises_rather_than_opening_the_api(monkeypatch):
    """Silently falling back to 'no auth' on a typo is how an API ends up public."""
    monkeypatch.setenv("EMULSION_AUTH", "clerkk")
    with pytest.raises(ValueError, match="Unknown EMULSION_AUTH"):
        identity_provider()


# -- clerk: the happy path ------------------------------------------------------------


def test_a_valid_token_yields_its_principal(clerk, keys):
    private, _ = keys
    principal = clerk.authenticate(make_token(private))
    assert principal == Principal(
        subject="user_2abc", email="someone@example.com", display_name="Someone"
    )
    assert not principal.is_local


def test_username_is_used_when_name_is_absent(clerk, keys):
    private, _ = keys
    token = make_token(private, name=None, username="someone")
    assert clerk.authenticate(token).display_name == "someone"


def test_the_key_client_is_reused_rather_than_rebuilt(keys):
    """An earlier version built a PyJWKClient per request, so the advertised cache did
    nothing and every API call made a network round trip first."""
    private, _ = keys
    client = FakeJwkClient(private.public_key())
    provider = ClerkIdentity(issuer=ISSUER, jwk_client=client, jwks_url="unused")
    for _ in range(3):
        provider.authenticate(make_token(private))
    assert client.calls == 3
    assert provider._jwk_client is client


# -- clerk: everything that must be refused -------------------------------------------


def test_no_token_is_refused(clerk):
    with pytest.raises(AuthError):
        clerk.authenticate(None)
    with pytest.raises(AuthError):
        clerk.authenticate("")


def test_a_token_signed_by_another_key_is_refused(clerk, keys):
    _, other = keys
    with pytest.raises(AuthError):
        clerk.authenticate(make_token(other))


def test_an_expired_token_is_refused(clerk, keys):
    private, _ = keys
    now = int(time.time())
    with pytest.raises(AuthError):
        clerk.authenticate(make_token(private, exp=now - 120, iat=now - 3600))


def test_a_token_from_another_issuer_is_refused(clerk, keys):
    private, _ = keys
    with pytest.raises(AuthError):
        clerk.authenticate(make_token(private, iss="https://evil.example"))


def test_a_token_without_an_expiry_is_refused(clerk, keys):
    """A token that never expires is a permanent credential in a cookie."""
    private, _ = keys
    now = int(time.time())
    claims = {"sub": "user_2abc", "iss": ISSUER, "iat": now}
    with pytest.raises(AuthError):
        clerk.authenticate(jwt.encode(claims, private, algorithm="RS256"))


def test_a_token_without_a_subject_is_refused(clerk, keys):
    private, _ = keys
    now = int(time.time())
    claims = {"iss": ISSUER, "iat": now, "exp": now + 60}
    with pytest.raises(AuthError):
        clerk.authenticate(jwt.encode(claims, private, algorithm="RS256"))


def test_a_tampered_token_is_refused(clerk, keys):
    private, _ = keys
    token = make_token(private)
    head, payload, signature = token.split(".")
    with pytest.raises(AuthError):
        clerk.authenticate(f"{head}.{payload}x.{signature}")


def test_an_unsigned_token_is_refused(clerk):
    """alg=none is the oldest JWT attack there is."""
    forged = jwt.encode({"sub": "admin", "iss": ISSUER}, key=None, algorithm="none")
    with pytest.raises(AuthError):
        clerk.authenticate(forged)


def test_failures_do_not_reveal_which_check_failed(clerk, keys):
    """Distinguishable errors are a probing oracle: they tell an attacker whether a
    token was merely expired, or signed by a key they do not have."""
    private, other = keys
    now = int(time.time())
    collected = []
    for token in (
        make_token(other),
        make_token(private, exp=now - 300, iat=now - 3600),
        make_token(private, iss="https://evil.example"),
    ):
        with pytest.raises(AuthError) as exc:
            clerk.authenticate(token)
        collected.append(str(exc.value))
    assert len(set(collected)) == 1, collected
    assert collected[0] == "token rejected"


# -- audience -------------------------------------------------------------------------


def test_audience_is_checked_when_configured(keys):
    private, _ = keys
    provider = ClerkIdentity(
        issuer=ISSUER,
        audience="emulsion",
        jwk_client=FakeJwkClient(private.public_key()),
        jwks_url="unused",
    )
    assert provider.authenticate(make_token(private, aud="emulsion")).subject == "user_2abc"
    with pytest.raises(AuthError):
        provider.authenticate(make_token(private, aud="something-else"))


def test_audience_is_ignored_when_not_configured(clerk, keys):
    private, _ = keys
    assert clerk.authenticate(make_token(private, aud="anything")).subject == "user_2abc"


def test_a_missing_jwks_url_names_the_free_alternative():
    with pytest.raises(ValueError, match="single-user locally"):
        ClerkIdentity(jwks_url="")
