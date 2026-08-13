"""Local implementations of the portability protocols. No cloud, no containers.

These exist so the whole product runs on a laptop with nothing installed. They are
real implementations of the same protocols the Azure ones will satisfy, not stubs —
the code path under test is the code path that ships.
"""

from __future__ import annotations

import os
from pathlib import Path

from .ports import BlobStore, SecretStore


class FilesystemBlobStore(BlobStore):
    """Blobs as files under `root`; signed URLs as plain paths under `base_url`.

    ponytail: no signing, no expiry — anything that can reach the dev server can read
    any blob. That is correct for localhost and unacceptable anywhere else. The Azure
    implementation issues user-delegation SAS URLs with a real TTL; this class exists
    so `docker compose` is optional, not so it can be deployed.
    """

    def __init__(self, root: Path | str, base_url: str = "/_blobs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        # Keys are generated internally, but treat them as untrusted anyway: a key
        # containing '..' must not escape the store.
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"blob key escapes the store root: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def signed_url(self, key: str, ttl_seconds: int = 3600) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class EnvSecretStore(SecretStore):
    """Secrets from the process environment. Read-only in practice.

    ponytail: `put`/`delete` mutate os.environ, which does not survive a restart. Good
    enough for a single-user laptop; BYOK storage proper is envelope encryption in
    Postgres with a per-user DEK (M8), behind this same protocol.
    """

    def __init__(self, prefix: str = "EMULSION_SECRET_") -> None:
        self.prefix = prefix

    def _var(self, name: str) -> str:
        return f"{self.prefix}{name.upper().replace('-', '_')}"

    def get(self, name: str) -> str | None:
        return os.environ.get(self._var(name))

    def put(self, name: str, value: str) -> None:
        os.environ[self._var(name)] = value

    def delete(self, name: str) -> None:
        os.environ.pop(self._var(name), None)
