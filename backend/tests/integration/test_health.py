"""
KiteShield Wallet — Health Endpoint Integration Test

Verifies that the application starts and the health endpoint responds.
"""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health endpoint should return 200 with service info."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "kiteshield-wallet"


@pytest.mark.asyncio
async def test_readiness_endpoint(client):
    """Readiness endpoint should return 200."""
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_correlation_id_in_response(client):
    """Responses should include X-Correlation-ID header."""
    response = await client.get("/api/v1/health")
    assert "X-Correlation-ID" in response.headers
    # UUID format
    cid = response.headers["X-Correlation-ID"]
    assert len(cid) == 36  # UUID with dashes


@pytest.mark.asyncio
async def test_custom_correlation_id_preserved(client):
    """Custom correlation ID from request should be preserved in response."""
    custom_cid = "my-custom-correlation-id"
    response = await client.get(
        "/api/v1/health",
        headers={"X-Correlation-ID": custom_cid},
    )
    assert response.headers["X-Correlation-ID"] == custom_cid


@pytest.mark.asyncio
async def test_openapi_docs_available(client):
    """OpenAPI documentation should be accessible."""
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "KiteShield Wallet API"
