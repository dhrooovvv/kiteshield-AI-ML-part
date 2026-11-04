"""Existing wallet services, in a fresh process with test-only credentials and DB.

This is a simulation adapter, not a new signing implementation. No live mode exists.
"""

import json
import os
import secrets
import sys
from pathlib import Path

import httpx

from demo_autonomy.engine import HumanRequiredError


def bootstrap(directory: Path, model: str):
    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise RuntimeError("Sandbox must bootstrap before all main app imports")
    if not directory.name.startswith("kiteshield-gate"):
        raise RuntimeError("Dedicated demo profile required")
    # Clear inherited secrets before constructing any wallet component.
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "PYTHONPATH") if k in os.environ}
    os.environ.clear()
    os.environ.update(keep)
    os.chdir(directory)
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_DEBUG": "false",
            "APP_LOG_LEVEL": "ERROR",
            "DATABASE_URL": f"sqlite+aiosqlite:///{directory / 'wallet-simulation.sqlite3'}",
            "CAPABILITY_TOKEN_SECRET": "a" * 64,
            "SIGNER_PRIVATE_KEY": "b" * 64,
            "API_KEY": secrets.token_urlsafe(32),
            "APPROVER_API_KEY": secrets.token_urlsafe(32),
            "POLICY_ADMIN_API_KEY": secrets.token_urlsafe(32),
            "EMERGENCY_STOP_ADMIN_API_KEY": secrets.token_urlsafe(32),
            "EXECUTION_MODE": "simulated",
            "CHAIN_ID": "11155111",
            "SEPOLIA_RPC_URL": "http://127.0.0.1:1/rpc-forbidden",
            "AUTO_EXECUTE_ENABLED": "false",
            "INVOICE_INTAKE_ENABLED": "false",
            "INVOICE_LIVE_EXECUTION_ENABLED": "false",
            "TREASURY_MONITOR_ENABLED": "false",
            "INVOICE_LEARNED_SCREENING_ENABLED": "false",
            "LEARNED_SCREENING_ENABLED": "false",
            "INVOICE_MODEL": model,
            "FAUCET_ENABLED": "true",
            "FAUCET_MODE": "simulated",
            "OPENAI_API_KEY": "",
            "CDP_API_KEY_ID": "",
            "CDP_API_KEY_SECRET": "",
        }
    )
    from app.core.config import Settings, get_settings

    Settings.model_config = {**Settings.model_config, "env_file": None}
    get_settings.cache_clear()
    settings = get_settings()
    if settings.execution_mode != "simulated" or settings.signer_private_key != "b" * 64:
        raise RuntimeError("Demo isolation failed")
    from app.services.blockchain import BlockchainService

    def forbidden(*args, **kwargs):
        raise RuntimeError("Network RPC forbidden in isolated demo")

    BlockchainService._get_w3 = forbidden


class WaitingError(Exception):
    def __init__(self, reason, approval=False):
        super().__init__(reason)
        self.approval = approval


class WalletServicesAdapter:
    def __init__(self, engine, core_app=None):
        from app.core.config import get_settings
        from app.main import create_app

        self.engine = engine
        self.settings = get_settings()
        self.validate_profile()
        self.app = core_app if core_app is not None else create_app()
        self.main_integrated = core_app is not None
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://isolated-demo:8001"
        )

    def validate_profile(self):
        if (
            self.settings.execution_mode != "simulated"
            or self.settings.signer_private_key != "b" * 64
        ):
            raise RuntimeError("Demo isolation failed")

    async def initialize(self):
        from app.db import init_db

        if not self.main_integrated:
            await init_db()
        with self.engine.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS wallet_links ("
                "task_id TEXT PRIMARY KEY, proposal_id TEXT, funding_id TEXT, "
                "payment_started INTEGER DEFAULT 0, funding_started INTEGER DEFAULT 0)"
            )

    async def close(self):
        from app.db import get_engine

        await self.client.aclose()
        await get_engine().dispose()

    async def call(self, method, path, *, role="agent", data=None, correlation=None):
        token = {
            "agent": self.settings.api_key,
            "admin": self.settings.policy_admin_api_key,
            "approver": self.settings.approver_api_key,
        }[role]
        headers = {"X-API-Key": token}
        if correlation:
            headers["X-Correlation-ID"] = correlation
        result = await self.client.request(method, "/api/v1" + path, json=data, headers=headers)
        if result.status_code >= 400:
            # Do not expose exception text or return provider-controlled messages.
            raise HumanRequiredError(f"WALLET_SERVICE_{result.status_code}")
        return result.json()["data"]

    async def configure(self, recipient, cap, threshold):
        await self.call(
            "POST",
            "/policies",
            role="admin",
            data={
                "max_amount_wei": str(cap),
                "daily_limit_wei": str(cap),
                "allowed_recipients": [recipient],
                "escalation_threshold_wei": str(threshold),
            },
        )

    def link(self, task_id):
        with self.engine.db() as db:
            db.execute("INSERT OR IGNORE INTO wallet_links(task_id) VALUES(?)", (task_id,))
            return dict(
                db.execute("SELECT * FROM wallet_links WHERE task_id=?", (task_id,)).fetchone()
            )

    def save(self, task_id, field, value):
        if field not in {"proposal_id", "funding_id", "payment_started", "funding_started"}:
            raise ValueError("Invalid link field")
        with self.engine.db() as db:
            db.execute(  # noqa: S608 -- field is restricted to the literal allowlist above
                f"UPDATE wallet_links SET {field}=? WHERE task_id=?",  # noqa: S608 -- allowlisted column
                (value, task_id),
            )

    async def find_proposal(self, task):
        from sqlalchemy import select

        from app.db import get_session_factory
        from app.models import Proposal

        async with get_session_factory()() as session:
            rows = (
                await session.scalars(
                    select(Proposal).where(Proposal.correlation_id == "goal-" + task["id"])
                )
            ).all()
            if len(rows) > 1:
                raise HumanRequiredError("DUPLICATE_PROPOSAL_ANOMALY")
            if rows:
                mandate = json.loads(task["mandate"])
                if (
                    rows[0].recipient.lower() != mandate["recipient"]
                    or int(rows[0].amount_wei) != task["amount"]
                ):
                    raise HumanRequiredError("PROPOSAL_BINDING_MISMATCH")
                return rows[0].id

    async def payment(self, task, reconcile=False):
        link = self.link(task["id"])
        proposal = link["proposal_id"] or await self.find_proposal(task)
        if not proposal:
            if reconcile or link["payment_started"]:
                raise HumanRequiredError("UNRESOLVED_PAYMENT")
            self.save(task["id"], "payment_started", 1)
            recipient = json.loads(task["mandate"])["recipient"]
            answer = await self.call(
                "POST",
                "/proposals/agent",
                data={"prompt": f"Send {task['amount']} wei to {recipient}"},
                correlation="goal-" + task["id"],
            )
            proposal = answer["id"]
        self.save(task["id"], "proposal_id", proposal)
        answer = await self.call("GET", f"/proposals/{proposal}")
        if answer["status"] == "PROPOSED":
            answer = await self.call("POST", f"/proposals/{proposal}/evaluate")
        if answer["status"] == "ESCALATED":
            approval = answer["approval"]
            if approval["status"] in {"EXPIRED", "REJECTED"}:
                raise HumanRequiredError("APPROVAL_" + approval["status"])
            raise WaitingError("HUMAN_APPROVAL_REQUIRED", approval=True)
        if answer["status"] in {"BLOCKED", "REJECTED", "EXPIRED_APPROVAL"}:
            raise HumanRequiredError("POLICY_" + answer["status"])
        if answer["status"] in {"ALLOWED", "APPROVED"}:
            self.engine.allowed(task)
            # Reuses original coordinator/capability/signer. Only test key, simulated mode.
            answer = await self.call("POST", f"/proposals/{proposal}/sign")
        tx = answer.get("transaction")
        if not tx or tx.get("execution_outcome") != "SIMULATED":
            raise HumanRequiredError("UNRESOLVED_PAYMENT")
        return {
            "tool": "payment",
            "mode": "SIMULATED",
            "paid_wei": task["amount"],
            "proposal_id": proposal,
            "receipt_id": "simulation:" + tx["id"],
            "recipient": json.loads(task["mandate"])["recipient"],
        }

    async def decide(self, task_id, decision):
        proposal = self.link(task_id)["proposal_id"]
        answer = await self.call("GET", f"/proposals/{proposal}")
        approval = answer.get("approval")
        if not approval:
            raise HumanRequiredError("APPROVAL_NOT_FOUND")
        return await self.call(
            "POST",
            f"/approvals/{approval['id']}/decide",
            role="approver",
            data={"decision": decision},
        )

    async def fund(self, task, reconcile=False):
        link = self.link(task["id"])
        if not link["funding_id"]:
            if link["funding_started"] or reconcile:
                raise HumanRequiredError("UNRESOLVED_FUNDING")
            self.save(task["id"], "funding_started", 1)
            from app.services.funding import wallets

            target = wallets()[0]["address"]
            answer = await self.call(
                "POST",
                "/funding/plan",
                data={"prompt": "Fund my wallet with Sepolia test ETH", "address": target},
            )
            self.save(task["id"], "funding_id", answer["id"])
            link = self.link(task["id"])
        answer = await self.call("POST", f"/funding/{link['funding_id']}/request")
        if answer["state"] != "SIMULATED":
            raise HumanRequiredError("FUNDING_" + answer["state"])
        receipt = await self.call("GET", f"/funding/{link['funding_id']}")
        if receipt["state"] != "SIMULATED":
            raise HumanRequiredError("FUNDING_RECEIPT_MISMATCH")
        return {
            "tool": "fund",
            "mode": "SIMULATED",
            "provider": "existing_faucet_adapter",
            "funding_request_id": answer["id"],
            "receipt_id": "simulation:" + answer["id"],
        }

    async def run(self, task, tool, key, *, reconcile=False):
        # The workflow engine reserves and checks the demo ledger; this layer delegates
        # financial decisions to the unchanged wallet services, never to a model.
        integrity = await self.call("GET", "/audit/integrity/verify?limit=100000")
        if integrity.get("is_valid") is not True:
            raise HumanRequiredError("AUDIT_MISMATCH")
        if tool == "fund":
            return await self.fund(task, reconcile)
        if tool == "payment":
            return await self.payment(task, reconcile)
        if tool == "receipt":
            proposal = self.link(task["id"])["proposal_id"]
            answer = await self.call("GET", f"/proposals/{proposal}")
            tx = answer.get("transaction")
            if not tx or tx.get("execution_outcome") != "SIMULATED":
                raise HumanRequiredError("RECEIPT_UNVERIFIED")
            return {
                "tool": tool,
                "mode": "SIMULATED",
                "verified": True,
                "receipt_id": "simulation:" + tx["id"],
            }
        return {"tool": "balance", "mode": "SIMULATED"}
