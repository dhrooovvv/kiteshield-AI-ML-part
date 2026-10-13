"""
KiteShield Wallet — Test Configuration

Provides shared fixtures for all test layers.
Uses a separate in-memory SQLite database for test isolation.
"""

import os

import pytest
import pytest_asyncio

# Set test environment variables BEFORE importing app modules
os.environ.update(
    {
        "APP_ENV": "test",
        "APP_DEBUG": "false",
        "CAPABILITY_TOKEN_SECRET": "a" * 64,  # Test-only secret (64 hex chars)
        "API_KEY": "test-api-key-for-unit-tests-only",
        "CHAIN_ID": "11155111",
        "SEPOLIA_RPC_URL": "https://mock-rpc.test/v1",
        "SIGNER_PRIVATE_KEY": "b" * 64,  # Test-only key (never used on real network)
        "OPENAI_API_KEY": "",
        "DATABASE_URL": "sqlite+aiosqlite:///./test_kiteshield.db",
    }
)

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_db_session
from app.main import create_app
from app.models import Base

# ---- Database Fixtures ----


@pytest_asyncio.fixture
async def test_engine():
    """Create a test database engine with in-memory SQLite."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine):
    """Create a test database session."""
    factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session


# ---- App Fixtures ----


@pytest_asyncio.fixture
async def app(test_engine):
    """Create a test FastAPI application with overridden DB."""
    test_app = create_app()

    # Override DB session dependency
    factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_db_session] = override_db

    yield test_app


@pytest_asyncio.fixture
async def client(app):
    """Create an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client):
    """Create an authenticated test client with API key header."""
    client.headers["X-API-Key"] = os.environ["API_KEY"]
    yield client


# ---- Helper Fixtures ----


@pytest.fixture
def sample_proposal_data():
    """Valid sample proposal request data."""
    return {
        "prompt": "Send 0.01 ETH to the test address",
        "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD1e",
        "amount_wei": "10000000000000000",  # 0.01 ETH
        "chain_id": 11155111,
        "asset_type": "NATIVE_ETH",
    }
