"""Test environment, set before any test module imports application code.

Hermetic on purpose: a developer with EMULSION_ADAPTER=foundry in their shell must not
have the test suite start spending money against a real deployment.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="emulsion-tests-"))

os.environ["EMULSION_DATA_DIR"] = str(_TMP)
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["EMULSION_ADAPTER"] = "echo"
os.environ["EMULSION_INLINE_WORKER"] = "0"
os.environ["EMULSION_ECHO_LATENCY_S"] = "0"
os.environ["EMULSION_POLL_INTERVAL_S"] = "0.01"
