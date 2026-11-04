from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from demo_autonomy.integration import mount_autonomy


def config(tmp_path):
    directory = tmp_path / "kiteshield-gate-main-test"
    return SimpleNamespace(
        execution_mode="simulated",
        app_env="test",
        app_port=8001,
        signer_private_key="b" * 64,
        autonomy_profile_dir=str(directory),
        database_url=f"sqlite+aiosqlite:///{directory / 'wallet-simulation.sqlite3'}",
        autonomy_model="test-model",
        autonomy_model_digest="a" * 64,
        autonomy_ollama_version="test-version",
        autonomy_quarantine_enabled=False,
        policy_admin_api_key="a" * 40,
        api_key="b" * 40,
        approver_api_key="c" * 40,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_mode", "sepolia"),
        ("app_env", "production"),
        ("app_port", 8000),
        ("signer_private_key", "c" * 64),
        ("database_url", "sqlite+aiosqlite:///./kiteshield.db"),
        ("autonomy_profile_dir", "/not-a-demo"),
    ],
)
def test_main_integration_refuses_nonisolated_profiles(tmp_path, field, value):
    settings = config(tmp_path)
    setattr(settings, field, value)
    with pytest.raises(RuntimeError, match="isolated"):
        mount_autonomy(FastAPI(), settings)
    assert not list(tmp_path.rglob("*.sqlite3"))


@pytest.mark.asyncio
async def test_main_mount_uses_existing_role_keys_and_no_new_token_login(tmp_path):
    settings = config(tmp_path)
    app = FastAPI()
    mount_autonomy(app, settings)
    # No lifespan needed: test must not initialize a wallet or sign.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://demo:8001"
    ) as c:
        health = await c.get("/api/v1/autonomy/health")
        assert health.status_code == 200 and health.json()["mode"] == "SIMULATED"
        assert (
            await c.post(
                "/api/v1/autonomy/quarantine/resume", headers={"X-API-Key": settings.api_key}
            )
        ).status_code == 403
        assert (
            await c.post(
                "/api/v1/autonomy/approvals/task/decision",
                json={"decision": "APPROVE"},
                headers={"X-API-Key": settings.api_key},
            )
        ).status_code == 403
        assert (
            await c.post(
                "/api/v1/autonomy/approvals/task/decision",
                json={"decision": "APPROVE"},
                headers={"X-API-Key": settings.policy_admin_api_key},
            )
        ).status_code == 403
    assert not list(tmp_path.rglob("*.sqlite3"))
