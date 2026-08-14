"""Queue consumer and the process-wide runtime wiring it owns."""

from emulsion_platform import load_env

# Before .runtime: it reads EMULSION_ADAPTER and the storage settings at import time.
load_env()

from .runner import process_job, process_once, run_forever  # noqa: E402
from .runtime import blob_store, bootstrap, queue, settings  # noqa: E402

__all__ = [
    "blob_store",
    "bootstrap",
    "load_env",
    "process_job",
    "process_once",
    "queue",
    "run_forever",
    "settings",
]
