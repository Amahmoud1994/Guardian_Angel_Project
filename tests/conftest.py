import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest_asyncio

# Point at an isolated temp DB BEFORE importing main — DB_PATH/engine are created at import time.
_tmpdir = tempfile.mkdtemp(prefix="guardian_angel_test_")
os.environ["GUARDIAN_DB_PATH"] = str(Path(_tmpdir) / "test.db")
# The test client talks over plain http://test — a Secure-flagged cookie wouldn't be
# re-sent by the client's cookie jar over a non-https origin, breaking auth in tests.
os.environ["COOKIE_SECURE"] = "false"
# Most tests register/check-in many times in quick succession from the same test-runner
# IP — that's a test-harness artifact, not something worth throttling. Rate limiting
# itself gets its own dedicated test (test_rate_limiting.py), which re-enables it.
os.environ["DISABLE_RATE_LIMIT"] = "true"
# Admins are configured per deployment (no hard-coded defaults) — give the tests their own.
os.environ.setdefault("ADMIN_USERNAMES", "test_admin_one,test_admin_two")

import main  # noqa: E402

# Optional: run the suite against Postgres by setting DATABASE_URL. pytest-asyncio gives each
# test its own event loop, and asyncpg connections are bound to the loop that opened them, so
# pooled connections can't be reused across tests — open a fresh one per checkout instead.
if main.IS_POSTGRES:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    main.engine = create_async_engine(main.DATABASE_URL, poolclass=NullPool, connect_args=main._DB_CONNECT_ARGS)
    main.AsyncSessionLocal = async_sessionmaker(main.engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session")
async def app():
    """Runs the real startup (creates tables, migrations, starts the watchdog) once for the whole test run."""
    async with main.lifespan(main.app):
        yield main.app


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@asynccontextmanager
async def new_client(app):
    """A second, independent cookie jar — for tests that need to act as two different logged-in users at once."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def unique(prefix: str) -> str:
    """Unique-ish identifier so tests sharing the session DB don't collide."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


ADMIN_PASSWORD = "admin-pw-123456"


async def login_as_admin(client, username=None):
    """Admin usernames are fixed constants (main.ADMIN_USERNAMES) — register once per
    test session and log in on every subsequent call, since multiple test files need it."""
    username = username or next(iter(main.ADMIN_USERNAMES))
    r = await client.post("/api/register", json={"username": username, "password": ADMIN_PASSWORD, "accept_terms": True})
    if r.status_code == 200:
        return r.json()
    r = await client.post("/api/login", json={"username": username, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


async def sign_in(client, prefix: str = "tester") -> dict:
    """Register (and thereby sign in) a fresh account on this client — journeys require an account."""
    r = await client.post("/api/register", json={"username": unique(prefix), "password": "pw123456", "accept_terms": True})
    assert r.status_code == 200, r.text
    return r.json()
