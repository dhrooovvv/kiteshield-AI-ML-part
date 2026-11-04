"""Opt-in durable tasks for the EXISTING wallet, policies, roles and database.

This module only adds restrictions and proposal artifacts. It does not implement
signing, authorization, capability issuance or transaction execution.
"""

import asyncio
import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from demo_autonomy.engine import HumanRequiredError, Settings
from demo_autonomy.sandbox import WaitingError
from demo_autonomy.sepolia import SepoliaAdapter, SepoliaWorkflowEngine
from demo_autonomy.server import create_demo


@dataclass(frozen=True)
class MainAuthority:
    payments_enabled: bool
    recipient: str
    payment_budget_wei: int
    max_payment_fee_wei: int
    session_fee_budget_wei: int
    funding_budget_wei: int
    faucet_grant_ceiling_wei: int
    max_gas_units: int
    max_fee_per_gas_wei: int
    max_priority_fee_per_gas_wei: int
    faucet_enabled: bool

    @classmethod
    def from_settings(cls, settings):
        if (
            not settings.autonomy_live_enabled
            or settings.execution_mode != "sepolia"
            or settings.chain_id != 11155111
            or not re.fullmatch(r"0x[0-9a-fA-F]{40}", settings.autonomy_recipient)
            or int(settings.autonomy_recipient, 16) == 0
            or not 0 < settings.autonomy_payment_budget_wei <= 10**15
            or settings.autonomy_session_fee_budget_wei <= 0
        ):
            raise ValueError("Explicit main-wallet autonomy scope and budgets required")
        maximum = int(settings.auto_execute_max_eth * 10**18)
        if settings.autonomy_payment_budget_wei > maximum:
            raise ValueError("Autonomy budget cannot exceed the existing automatic payment limit")
        funding = settings.autonomy_funding_budget_wei
        ceiling = settings.autonomy_faucet_grant_ceiling_wei
        faucet = (
            settings.faucet_enabled
            and settings.faucet_mode == "sepolia"
            and bool(settings.cdp_api_key_id and settings.cdp_api_key_secret)
            and 0 < ceiling <= funding
        )
        return cls(
            settings.auto_execute_enabled,
            settings.autonomy_recipient.lower(),
            settings.autonomy_payment_budget_wei,
            settings.max_gas_units * settings.max_fee_per_gas_wei,
            settings.autonomy_session_fee_budget_wei,
            funding,
            ceiling,
            settings.max_gas_units,
            settings.max_fee_per_gas_wei,
            settings.max_priority_fee_per_gas_wei,
            faucet,
        )


class MainWorkflowEngine(SepoliaWorkflowEngine):
    def create(self, goal, request_key):
        # Deterministic decimal conversion; Gemma never chooses executable amounts.
        match = re.fullmatch(
            r"fund my wallet if needed, then pay ([0-9]+(?:\.[0-9]{1,18})?) ETH "
            r"to supplier ([A-Za-z -]+) and verify[.!]?",
            goal,
            re.I,
        )
        if match:
            amount = int(Decimal(match[1]) * 10**18)
            goal = f"fund if needed, pay supplier {match[2]} {amount} wei, verify"
        return super().create(goal, request_key)

    def initialize(self):
        super().initialize()
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS main_scope "
                "(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
            )

    def context_for_new_task(self):
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.autonomy_vault_payments_enabled:
            return {"backend": "NATIVE"}
        import sqlite3

        path = Path(settings.database_url.removeprefix("sqlite+aiosqlite:///")).resolve()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as core:
            row = core.execute(
                "SELECT address,epoch,revision,configured FROM vault_registry WHERE id='global'"
            ).fetchone()
        if not row or not row[0] or not row[3]:
            raise HumanRequiredError("ADMIN_VAULT_SESSION_REQUIRED")
        return {"backend": "VAULT", "address": row[0], "epoch": row[1], "revision": row[2]}

    async def fund(self, task, key, adapter, reconcile):
        if self.task_context(task["id"])["backend"] != "VAULT":
            return await super().fund(task, key, adapter, reconcile)
        # Owner deposits and gas grants are administrator actions, not funding tools.
        state = await adapter.vault_status_for_task(task)
        if state["remaining"] < task["amount"]:
            raise HumanRequiredError("ADMIN_VAULT_ALLOWANCE_REQUIRED")
        if state["agent_balance"] <= 0:
            raise HumanRequiredError("ADMIN_AGENT_GAS_REQUIRED")
        if adapter.link(task["id"])["funding_started"] or state["balance"] < task["amount"]:
            await adapter.require_vault_funding_target(task)
            return await super().fund(task, key, adapter, reconcile)
        return {
            "tool": "fund",
            "mode": "SEPOLIA",
            "funded_wei": 0,
            "skipped": True,
            "payment_backend": "VAULT",
            "balance_wei": str(state["balance"]),
        }

    def reserve_fee(self, task):
        # Reserve the exact bounded preflight envelope, within the administrator's
        # session fee budget. Do not reserve the old wallet's worst-case fee for
        # every task; those outer gas bounds still apply at the existing signer.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT amount FROM fee_claims WHERE task_id=?", (task["id"],)
            ).fetchone()
            if prior:
                return
            link = db.execute(
                "SELECT limits_json FROM chain_links WHERE task_id=?", (task["id"],)
            ).fetchone()
            if not link:
                raise HumanRequiredError("EXECUTION_LIMITS_REQUIRED")
            limits = json.loads(link[0])
            amount = (
                limits["max_fee_wei"]
                if self.task_context(task["id"])["backend"] == "VAULT"
                else int(limits["max_total_cost_wei"]) - task["amount"]
            )
            spent = db.execute("SELECT coalesce(sum(amount),0) FROM fee_claims").fetchone()[0]
            if (
                not 0 < amount <= self.authority.max_payment_fee_wei
                or spent + amount > self.authority.session_fee_budget_wei
            ):
                raise HumanRequiredError("SESSION_FEE_BUDGET_EXCEEDED")
            db.execute("INSERT INTO fee_claims VALUES(?,?)", (task["id"], amount))


class MainWalletAdapter(SepoliaAdapter):
    def validate_profile(self):
        from eth_account import Account

        s = self.settings
        database = s.database_url.removeprefix("sqlite+aiosqlite:///")
        if (
            not s.autonomy_enabled
            or not s.autonomy_live_enabled
            or s.execution_mode != "sepolia"
            or s.chain_id != 11155111
            or not s.database_url.startswith("sqlite+aiosqlite:///")
            or s.signer_private_key == "b" * 64
            or Account.from_key(s.signer_private_key).address != self.address
            or self.engine.settings.directory.resolve() != Path(s.autonomy_profile_dir).resolve()
            or self.engine.path.resolve() == Path(database).resolve()
        ):
            raise RuntimeError("Existing main-wallet autonomy configuration mismatch")

    async def initialize(self):
        await super().initialize()
        identity = json.dumps(
            {
                "address": self.address.lower(),
                "database": str(
                    Path(self.settings.database_url.removeprefix("sqlite+aiosqlite:///")).resolve()
                ),
            },
            sort_keys=True,
        )
        with self.engine.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS wallet_identity "
                "(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)"
            )
            prior = db.execute("SELECT value FROM wallet_identity WHERE id=1").fetchone()
            if prior and prior[0] != identity:
                raise RuntimeError("Task state belongs to another wallet or database")
            db.execute("INSERT OR IGNORE INTO wallet_identity VALUES(1,?)", (identity,))
        if self.settings.autonomy_incoming_watch_enabled:
            from demo_autonomy.incoming import IncomingWatcher

            self.incoming_watcher = IncomingWatcher(
                self.engine, self.rpc, self.address, self.settings.autonomy_incoming_confirmations
            )
            self.incoming_watcher.initialize()
            self.incoming_task = asyncio.create_task(
                self.incoming_watcher.run(self.settings.autonomy_incoming_poll_seconds)
            )

    async def close(self):
        task = getattr(self, "incoming_task", None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await super().close()

    async def scope(self, recipient):
        from sqlalchemy import select

        from app.db import get_session_factory
        from app.models import Policy
        from app.models.invoices import Vendor

        async with get_session_factory()() as session:
            policy = await session.scalar(
                select(Policy)
                .where(Policy.is_active.is_(True))
                .order_by(Policy.version.desc())
                .limit(1)
            )
            if not policy:
                raise HumanRequiredError("ACTIVE_POLICY_REQUIRED")
            allowed = {x.lower() for x in json.loads(policy.allowed_recipients or "[]")}
            blocked = {x.lower() for x in json.loads(policy.blocked_recipients or "[]")}
            vendors = (await session.scalars(select(Vendor).where(Vendor.active.is_(True)))).all()
            matches = [v for v in vendors if v.payout_address.lower() == recipient.lower()]
            if (
                recipient.lower() not in allowed
                or recipient.lower() in blocked
                or len(matches) != 1
            ):
                raise HumanRequiredError("EXACT_APPROVED_VENDOR_REQUIRED")
            vendor = matches[0]
            return {
                "policy_version": policy.version,
                "vendor_id": vendor.id,
                "vendor_version": vendor.version,
                "supplier": vendor.name,
                "recipient": recipient.lower(),
                "vendor_maximum_wei": vendor.maximum_wei,
                "policy_maximum_wei": policy.max_amount_wei,
                "approval_threshold_wei": policy.escalation_threshold_wei,
            }

    def saved_scope(self):
        with self.engine.db() as db:
            row = db.execute("SELECT value FROM main_scope WHERE id=1").fetchone()
        if not row:
            raise HumanRequiredError("ADMIN_MANDATE_REQUIRED")
        return json.loads(row[0])

    async def configure(self, recipient, cap, threshold):
        # Saving a workflow mandate MUST NOT rewrite the existing core policy.
        current = await self.scope(recipient)
        if (
            recipient.lower() != self.authority.recipient
            or not self.authority.payments_enabled
            or cap
            > min(
                self.authority.payment_budget_wei,
                int(current["vendor_maximum_wei"]),
                int(current["policy_maximum_wei"]),
            )
            or threshold != int(current["approval_threshold_wei"] or 10**24)
        ):
            raise HumanRequiredError("EXISTING_POLICY_LIMITS_REQUIRED")
        with self.engine.db() as db:
            db.execute(
                "INSERT INTO main_scope VALUES(1,?) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value",
                (json.dumps(current, sort_keys=True),),
            )

    async def payment_guard(self, task, proposal=None):
        from sqlalchemy import select

        from app.db import get_session_factory
        from app.models import ExecutionAttempt

        bound = self.saved_scope()
        if bound != await self.scope(json.loads(task["mandate"])["recipient"]):
            raise HumanRequiredError("MAIN_AUTHORITY_CHANGED")
        if task["amount"] > int(bound["vendor_maximum_wei"]):
            raise HumanRequiredError("VENDOR_LIMIT_EXCEEDED")
        own = proposal or self.link(task["id"])["proposal_id"]
        async with get_session_factory()() as session:
            query = select(ExecutionAttempt.id).where(
                ExecutionAttempt.execution_mode == "sepolia",
                ExecutionAttempt.sender == self.address.lower(),
                ExecutionAttempt.status.in_(("PREPARED", "SIGNED", "UNCERTAIN", "SUBMITTED")),
            )
            if own:
                query = query.where(ExecutionAttempt.proposal_id != own)
            if await session.scalar(query.limit(1)):
                raise WaitingError("OTHER_MAIN_PAYMENT_RECONCILING")

    async def proposal_ready(self, task, proposal):
        from app.db import get_session_factory
        from app.models.assistant import AssistantPaymentDraft, AssistantVendorBinding
        from app.services.execution_lock import lock_execution

        bound = self.saved_scope()
        prompt = f"Pay {bound['supplier']} {task['amount']} wei"
        async with get_session_factory()() as session:
            await lock_execution(session)
            draft = await session.get(AssistantPaymentDraft, task["id"])
            if draft:
                binding = await session.get(AssistantVendorBinding, draft.id)
                if (
                    draft.proposal_id != proposal
                    or draft.recipient.lower() != bound["recipient"]
                    or int(draft.amount_wei) != task["amount"]
                    or not binding
                    or binding.vendor_id != bound["vendor_id"]
                    or binding.vendor_version != bound["vendor_version"]
                ):
                    raise HumanRequiredError("PROPOSAL_BINDING_MISMATCH")
                return
            session.add(
                AssistantPaymentDraft(
                    id=task["id"],
                    prompt=prompt,
                    prompt_digest=hashlib.sha256(prompt.encode()).hexdigest(),
                    actor="durable_orchestrator",
                    recipient=bound["recipient"],
                    amount_wei=str(task["amount"]),
                    mode="sepolia",
                    proposal_id=proposal,
                )
            )
            await session.flush()
            session.add(
                AssistantVendorBinding(
                    draft_id=task["id"],
                    vendor_id=bound["vendor_id"],
                    vendor_version=bound["vendor_version"],
                    original_request=prompt,
                )
            )
            await session.commit()

    async def limits(self, task):
        from web3 import Web3

        from app.db import get_session_factory
        from app.exceptions import RPCError, TransactionSubmissionError
        from app.schemas import ExecutionLimits, NormalizedAction
        from app.services.blockchain import BlockchainService

        await self.payment_guard(task)
        proposal = self.link(task["id"])["proposal_id"]
        action = NormalizedAction(
            proposal_id=proposal,
            correlation_id="goal-" + task["id"],
            recipient=Web3.to_checksum_address(self.authority.recipient),
            amount_wei=task["amount"],
            chain_id=11155111,
        )
        try:
            async with get_session_factory()() as session:
                envelope = await BlockchainService().prepare_transaction(
                    session, self.address, action
                )
        except RPCError:
            raise HumanRequiredError("PREFLIGHT_UNAVAILABLE") from None
        except TransactionSubmissionError:
            raise HumanRequiredError("PREFLIGHT_LIMIT_BLOCK") from None
        # The unchanged coordinator preflights again before signing. Allow bounded
        # movement between those reads instead of failing on a one-block fee rise.
        # Every ceiling remains at or below the existing wallet configuration.
        gas_limit = min(self.authority.max_gas_units, (envelope["gas"] * 120 + 99) // 100)
        fee_limit = min(self.authority.max_fee_per_gas_wei, envelope["maxFeePerGas"] * 2)
        priority_limit = min(
            self.authority.max_priority_fee_per_gas_wei, envelope["maxPriorityFeePerGas"] * 2
        )
        fee = gas_limit * fee_limit
        if fee > self.authority.max_payment_fee_wei or await self.balance() < task["amount"] + fee:
            raise HumanRequiredError("INSUFFICIENT_FUNDS_INCLUDING_GAS")
        return ExecutionLimits(
            sender=self.address,
            recipient=self.authority.recipient,
            amount_wei=str(task["amount"]),
            chain_id=11155111,
            nonce=envelope["nonce"],
            max_gas_units=gas_limit,
            max_fee_per_gas_wei=fee_limit,
            max_priority_fee_per_gas_wei=priority_limit,
            max_total_cost_wei=str(task["amount"] + fee),
        ).model_dump()

    async def resume_before_signing(self, task_id):
        """Administrator recovery of the same proposal, only with proven no execution.

        Never clears a sign marker, changes a proposal, increases a budget,
        approves an escalation or retries an uncertain signed transaction.
        """
        from sqlalchemy import select

        from app.db import get_session_factory
        from app.models import ExecutionAttempt, Proposal, Transaction
        from app.services.execution_lock import lock_execution

        task = self.engine.get(task_id)
        if task["state"] != "HUMAN_REQUIRED" or task["reason"] not in {
            "RECONCILIATION_UNAVAILABLE",
            "PREFLIGHT_UNAVAILABLE",
            "PREFLIGHT_LIMIT_BLOCK",
        }:
            raise HumanRequiredError("TASK_NOT_RETRYABLE_BEFORE_SIGNING")
        if self.engine.control()["quarantined"]:
            raise HumanRequiredError("SELF_QUARANTINED")
        link = self.link(task_id)
        if not link["proposal_id"]:
            raise HumanRequiredError("BOUND_PROPOSAL_REQUIRED")
        with self.engine.db() as db:
            marker = db.execute(
                "SELECT sign_started FROM chain_links WHERE task_id=?", (task_id,)
            ).fetchone()
            mandate = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
        if marker and marker[0]:
            raise HumanRequiredError("SIGNED_OUTCOME_RECONCILE_REQUIRED")
        if (
            not mandate
            or dict(mandate) != json.loads(task["mandate"])
            or task["amount"] > min(task["payment_cap"], self.authority.payment_budget_wei)
            or not self.authority.payments_enabled
        ):
            raise HumanRequiredError("MANDATE_CHANGED")
        if link["funding_started"] and not any(
            step["tool"] == "fund" and step["state"] == "COMPLETED" for step in task["steps"]
        ):
            raise HumanRequiredError("UNRESOLVED_FUNDING")
        try:
            await self.payment_guard(task, link["proposal_id"])
        except WaitingError:
            raise HumanRequiredError("OTHER_MAIN_PAYMENT_RECONCILING") from None
        integrity = await self.call("GET", "/audit/integrity/verify?limit=100000")
        if integrity.get("is_valid") is not True:
            raise HumanRequiredError("AUDIT_MISMATCH")
        async with get_session_factory()() as session:
            await lock_execution(session)
            proposal = await session.get(Proposal, link["proposal_id"])
            attempt = await session.scalar(
                select(ExecutionAttempt.id).where(
                    ExecutionAttempt.proposal_id == link["proposal_id"]
                )
            )
            transaction = await session.scalar(
                select(Transaction.id).where(Transaction.proposal_id == link["proposal_id"])
            )
            if attempt or transaction:
                raise HumanRequiredError("SIGNED_OUTCOME_RECONCILE_REQUIRED")
            if (
                not proposal
                or proposal.status not in {"PROPOSED", "ALLOWED"}
                or proposal.correlation_id != "goal-" + task_id
                or proposal.recipient.lower() != json.loads(task["mandate"])["recipient"]
                or int(proposal.amount_wei) != task["amount"]
                or proposal.chain_id != 11155111
            ):
                raise HumanRequiredError("PROPOSAL_BINDING_MISMATCH")
            with self.engine.db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "UPDATE tasks SET state='READY',reason=NULL "
                    "WHERE id=? AND state='HUMAN_REQUIRED'",
                    (task_id,),
                )
                db.execute(
                    "UPDATE steps SET state='READY',lease=NULL,owner=NULL "
                    "WHERE task_id=? AND state!='COMPLETED'",
                    (task_id,),
                )
                db.execute(
                    "DELETE FROM progress WHERE task_id=? AND position IN "
                    "(SELECT position FROM steps WHERE task_id=? AND state!='COMPLETED')",
                    (task_id, task_id),
                )
                db.execute(
                    "UPDATE payment_claims SET state='RESERVED' "
                    "WHERE task_id=? AND state='UNCERTAIN'",
                    (task_id,),
                )
                db.execute(
                    "UPDATE issues SET resolved=1 WHERE task_id=? AND reason=?",
                    (task_id, task["reason"]),
                )
                self.engine.event(
                    db,
                    task_id,
                    "ADMIN_PRE_SIGN_RETRY",
                    "Original proposal retained; no execution exists; budgets unchanged",
                )
            await session.rollback()
        return {"resumed": True, "task_id": task_id, "proposal_id": link["proposal_id"]}

    async def wallet_status(self):
        result = await super().wallet_status()
        current = await self.scope(self.authority.recipient)
        result.update(
            wallet_source="existing-main",
            supplier=current["supplier"],
            policy_managed=True,
            approval_threshold_wei=current["approval_threshold_wei"],
            vendor_maximum_wei=current["vendor_maximum_wei"],
        )
        watcher = getattr(self, "incoming_watcher", None)
        result["incoming_watch"] = (
            {"enabled": True, **watcher.status()} if watcher else {"enabled": False}
        )
        return result


def mount_main_wallet(app, settings):
    from eth_account import Account

    authority = MainAuthority.from_settings(settings)
    if (
        not settings.autonomy_profile_dir
        or not settings.autonomy_model_digest
        or not settings.autonomy_ollama_version
    ):
        raise ValueError("Durable task directory and pinned local planner required")
    directory = Path(settings.autonomy_profile_dir).expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("Durable task directory must be private")
    address = Account.from_key(settings.signer_private_key).address
    from demo_autonomy.vault_adapter import VaultWalletAdapter

    adapter_class = VaultWalletAdapter if settings.vault_enabled else MainWalletAdapter
    child = create_demo(
        Settings(
            directory,
            enabled=True,
            planner_enabled=True,
            model=settings.autonomy_model,
            model_digest=settings.autonomy_model_digest,
            ollama_version=settings.autonomy_ollama_version,
            workflows_enabled=True,
            quarantine_enabled=settings.autonomy_quarantine_enabled,
            wallet_services_enabled=True,
            mode="SEPOLIA",
            wallet_source="existing-main",
        ),
        settings.policy_admin_api_key,
        settings.api_key,
        settings.approver_api_key,
        core_app=app,
        engine_factory=lambda config: MainWorkflowEngine(config, authority),
        adapter_factory=lambda engine, core: adapter_class(engine, core, authority, address),
    )
    app.state.autonomy_app = child
    app.state.main_wallet_autonomy = True
    app.mount("/api/v1/autonomy", child)
