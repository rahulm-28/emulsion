"""`.env` loading: found by walking up, and never louder than the real environment."""

import os
from pathlib import Path

from emulsion_platform import find_env, load_env


def test_no_env_file_is_not_an_error(tmp_path: Path):
    assert find_env(tmp_path) is None
    assert load_env(tmp_path) is None


def test_found_from_a_subdirectory(tmp_path: Path):
    """Running uvicorn from services/api must find the repo root's .env."""
    (tmp_path / ".env").write_text("EMULSION_TEST_A=file\n")
    nested = tmp_path / "services" / "api"
    nested.mkdir(parents=True)
    assert find_env(nested) == tmp_path / ".env"


def test_values_are_loaded(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("EMULSION_TEST_B=from-file\n")
    monkeypatch.delenv("EMULSION_TEST_B", raising=False)
    load_env(tmp_path)
    assert os.environ["EMULSION_TEST_B"] == "from-file"


def test_a_real_variable_beats_the_file(tmp_path: Path, monkeypatch):
    """A value exported by make, a container or CI is deliberate. The file yields.

    Without this, filling in .env would silently override the environment a deploy
    had carefully set — and the failure would look like the deploy config being
    ignored for no reason.
    """
    (tmp_path / ".env").write_text("EMULSION_TEST_C=from-file\n")
    monkeypatch.setenv("EMULSION_TEST_C", "from-shell")
    load_env(tmp_path)
    assert os.environ["EMULSION_TEST_C"] == "from-shell"


def test_the_nearest_file_wins(tmp_path: Path):
    (tmp_path / ".env").write_text("EMULSION_TEST_D=outer\n")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / ".env").write_text("EMULSION_TEST_D=inner\n")
    assert find_env(inner) == inner / ".env"
