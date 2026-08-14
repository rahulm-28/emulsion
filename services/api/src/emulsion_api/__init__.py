"""FastAPI application. Thin by design — it creates jobs and reports on them."""

from emulsion_platform import load_env

# Before importing .main: it resolves the identity provider at import time, so a
# .env that sets EMULSION_AUTH has to be in place first.
load_env()

from .main import app  # noqa: E402

__all__ = ["app"]
