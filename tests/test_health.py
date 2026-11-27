from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


class FakeConnection:
    async def execute(self, query: str) -> None:
        assert query == "SELECT 1"


class FakePool:
    """Stands in for a working database so the test needs no Supabase."""

    async def open(self, wait: bool = True) -> None:
        pass

    async def close(self) -> None:
        pass

    @asynccontextmanager
    async def connection(self):
        yield FakeConnection()


def make_settings(url: str, **kwargs) -> Settings:
    # _env_file=None: ignore any real .env on the machine
    return Settings(database_url=url, _env_file=None, **kwargs)


def test_health_ok():
    app = create_app(pool=FakePool())
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_database_down():
    # Nothing listens on port 1, so the real pool never gets a connection.
    settings = make_settings(
        "postgresql://user:pass@127.0.0.1:1/db?connect_timeout=1",
        db_pool_timeout_seconds=0.5,
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:  # app must start despite the DB being down
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "database": "unavailable"}


def test_settings_reject_transaction_pooler():
    with pytest.raises(ValidationError, match="transaction pooler"):
        make_settings("postgresql://u:p@aws-0-ap-south-1.pooler.supabase.com:6543/postgres")


def test_settings_accept_session_mode():
    settings = make_settings("postgresql://u:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres")
    assert settings.database_url.get_secret_value().endswith(":5432/postgres")
