"""Load a `.env` file into the process environment.

Called explicitly by the service entrypoints rather than on import. Importing a library
must never mutate `os.environ`: the test suite imports these packages expecting a clean
environment, and a developer's real `.env` — `EMULSION_AUTH=clerk`, a live
`AZURE_API_KEY` — leaking into a test run would either break the suite or, far worse,
quietly point it at a paid endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def find_env(start: Path | None = None) -> Path | None:
    """The nearest `.env` at or above `start`, or None.

    Walking up means `make dev` from the repo root and `uvicorn` from inside
    `services/api` find the same file.
    """
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(start: Path | None = None) -> Path | None:
    """Load `.env` if there is one, and report which file was used.

    Real environment variables always win. A value already exported — by `make`, by a
    container, by CI — is a deliberate act, and a file on disk should not silently
    override it.
    """
    path = find_env(start)
    if path is not None:
        load_dotenv(path, override=False)
    return path


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # Resolved, because on macOS /var is a symlink to /private/var and find_env
        # returns the resolved path.
        root = Path(tmp).resolve()
        (root / "nested").mkdir()
        (root / ".env").write_text("EMULSION_DEMO_ONE=from-file\nEMULSION_DEMO_TWO=from-file\n")

        os.environ.pop("EMULSION_DEMO_ONE", None)
        os.environ["EMULSION_DEMO_TWO"] = "from-shell"

        found = load_env(root / "nested")
        assert found == root / ".env", found
        assert os.environ["EMULSION_DEMO_ONE"] == "from-file"
        # The shell wins. This is the whole point of override=False.
        assert os.environ["EMULSION_DEMO_TWO"] == "from-shell"

    assert load_env(Path(tempfile.gettempdir()) / "definitely-not-a-repo") is None
    print("env: ok — found by walking up, and a real variable beats the file")
