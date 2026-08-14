"""Engine construction — specifically, failing legibly when a driver is missing."""

import pytest
from emulsion_db.session import database_url, make_engine


def test_a_missing_driver_explains_itself():
    """Copying .env.example activates a Postgres DATABASE_URL. Say so in one line.

    Without this the failure surfaces as ModuleNotFoundError raised from inside
    SQLAlchemy's dialect import, a dozen frames below anything the reader wrote, and
    the actual cause — a URL in a config file — appears nowhere in the traceback.
    """
    with pytest.raises(RuntimeError) as caught:
        make_engine("postgresql+psycopg://u:p@localhost:5432/x")
    message = str(caught.value)
    assert "uv sync --extra postgres" in message
    assert "unset DATABASE_URL" in message
    # The credentials in the URL must not be echoed back.
    assert "u:p" not in message


def test_the_default_is_a_sqlite_file(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url().startswith("sqlite:///")


def test_database_url_is_honoured(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert database_url() == "sqlite:///:memory:"
