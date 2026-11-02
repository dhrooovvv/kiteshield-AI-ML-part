"""Task integration only. Calls the core vault boundary; owns no signing keys."""

import asyncio
import json
from contextlib import suppress

from demo_autonomy.engine import HumanRequiredError
from demo_autonomy.main_wallet import MainWalletAdapter
from demo_autonomy.sandbox import WaitingError


class VaultWalletAdapter(MainWalletAdapter):
    async def initialize(self):
        await super().initialize()
        if self.settings.vault_quarantine_pause_enabled:
            from demo_autonomy.vault_safety import VaultSafety

            self.vault_safety = VaultSafety(self.engine, self.call)
            self.vault_safety.initialize()
            self.vault_safety_task = asyncio.create_task(self.vault_safety.run())

    async def close(self):
        task = getattr(self, "vault_safety_task", None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await super().close()

    def is_vault(self, task):
        return self.engine.task_context(task["id"])["backend"] == "VAULT"

    async def vault_status_for_task(self, task):
        context = self.engine.task_context(task["id"])
        status = await self.call("GET", "/vault/status")
        if (
            not status.get("payments_enabled")
            or not status.get("configured")
            or status.get("address", "").lower() != context.get("address", "").lower()
            or status.get("epoch") != context.get("epoch")
            or status.get("revision") != context.get("revision")
        ):
            raise HumanRequiredError("ADMIN_VAULT_GRANT_CHANGED")
        chain = status["chain"]
        for key in ("remaining", "perPayment", "balance", "agent_balance"):
            chain[key] = int(chain[key])
        if (
            chain["epoch"] != context["epoch"]
            or chain["paused"]
            or chain["agent"].lower() != status["agent"].lower()
            or chain["recipient"].lower() != self.authority.recipient.lower()
        ):
            raise HumanRequiredError("VAULT_SESSION_UNAVAILABLE")
        return chain

    async def payment_guard(self, task, proposal=None):
        await super().payment_guard(task, proposal)
        if self.is_vault(task):
            await self.vault_status_for_task(task)

    async def payment(self, task, reconcile=False):
        if not self.is_vault(task):
            return await super().payment(task, reconcile)
        await self.payment_guard(task)
        context = self.engine.task_context(task["id"])
        # Repeating a creation request is safe: a unique durable key binds its intent.
        op = await self.call(
            "POST",
            "/vault/payments",
            data={
                "request_key": "vault_goal_" + task["id"],
                "amount_wei": task["amount"],
                "expected_epoch": context["epoch"],
                "expected_revision": context["revision"],
            },
            correlation="goal-" + task["id"],
        )
        proposal = op["proposal_id"]
        self.save(task["id"], "payment_started", 1)
        self.save(task["id"], "proposal_id", proposal)
        await self.proposal_ready(task, proposal)
        answer = await self.call("GET", f"/proposals/{proposal}")
        if answer["status"] == "PROPOSED":
            answer = await self.call("POST", f"/proposals/{proposal}/evaluate")
        if answer["status"] == "ESCALATED":
            if answer["approval"]["status"] in {"REJECTED", "EXPIRED"}:
                raise HumanRequiredError("APPROVAL_" + answer["approval"]["status"])
            raise WaitingError("HUMAN_APPROVAL_REQUIRED", approval=True)
        if answer["status"] in {"BLOCKED", "REJECTED", "EXPIRED_APPROVAL", "TX_FAILED"}:
            raise HumanRequiredError("POLICY_" + answer["status"])
        with self.engine.db() as db:
            link = db.execute("SELECT * FROM chain_links WHERE task_id=?", (task["id"],)).fetchone()
        if not link:
            if op["tx_hash"]:
                raise HumanRequiredError("EXECUTION_LIMITS_REQUIRED")
            op = await self.call("POST", f"/vault/operations/{op['id']}/prepare")
            envelope = op["envelope"]
            limits = dict(
                operation_id=op["id"],
                payload_digest=op["payload_digest"],
                envelope_digest=op["envelope_digest"],
                max_fee_wei=envelope["gas"] * envelope["maxFeePerGas"],
            )
            with self.engine.db() as db:
                db.execute(
                    "INSERT INTO chain_links VALUES(?,?,0)", (task["id"], json.dumps(limits))
                )
        else:
            limits = json.loads(link["limits_json"])
        if not op["tx_hash"]:
            if link and link["sign_started"]:
                raise HumanRequiredError("UNRESOLVED_SIGNING_OUTCOME")
            self.engine.allowed(task)
            self.engine.reserve_fee(task)
            await self.payment_guard(task, proposal)
            with self.engine.db() as db:
                db.execute("UPDATE chain_links SET sign_started=1 WHERE task_id=?", (task["id"],))
            try:
                op = await self.call("POST", f"/vault/operations/{op['id']}/execute", data=limits)
            except Exception:
                raise WaitingError("SIGNING_OUTCOME_RECONCILING") from None
        if not op["tx_hash"]:
            raise HumanRequiredError("UNRESOLVED_PAYMENT")
        with self.engine.db() as db:
            if not db.execute(
                "SELECT id FROM events WHERE task_id=? AND kind='TRANSACTION_OBSERVED'",
                (task["id"],),
            ).fetchone():
                self.engine.event(
                    db,
                    task["id"],
                    "TRANSACTION_OBSERVED",
                    json.dumps(
                        {"mode": "SEPOLIA", "payment_backend": "VAULT", "tx_hash": op["tx_hash"]}
                    ),
                )
        result = await self.verify_payment(task, op["tx_hash"], limits)
        result["proposal_id"] = proposal
        return result

    async def verify_payment(self, task, tx_hash, limits):
        if not self.is_vault(task):
            return await super().verify_payment(task, tx_hash, limits)
        op = await self.call("POST", f"/vault/operations/{limits['operation_id']}/reconcile")
        if (
            op["tx_hash"] != tx_hash
            or op["payload_digest"] != limits["payload_digest"]
            or op["envelope_digest"] != limits["envelope_digest"]
            or op["payload"]["amount_wei"] != task["amount"]
            or op["payload"]["recipient"].lower()
            != json.loads(task["mandate"])["recipient"].lower()
            or op["proposal_id"] != self.link(task["id"])["proposal_id"]
        ):
            self.engine.issue(task["id"], "VAULT_EVIDENCE_MISMATCH", anomaly=True)
            raise HumanRequiredError("VAULT_EVIDENCE_MISMATCH")
        if op["status"] == "REVERTED":
            raise HumanRequiredError("ONCHAIN_PAYMENT_REVERTED")
        if op["status"] != "CONFIRMED" or not op["receipt"]:
            raise WaitingError("PAYMENT_RECEIPT_PENDING")
        receipt = op["receipt"]
        return dict(
            tool="payment",
            mode="SEPOLIA",
            payment_backend="VAULT",
            paid_wei=task["amount"],
            tx_hash=tx_hash,
            receipt_id=tx_hash,
            verified=True,
            recipient=op["payload"]["recipient"],
            confirmations_required=1,
            block_number=receipt["blockNumber"],
            fee_paid_wei=str(receipt["gasUsed"] * receipt["effectiveGasPrice"]),
            explorer_url="https://sepolia.etherscan.io/tx/" + tx_hash,
        )

    async def resume_before_signing(self, task_id):
        if self.is_vault(self.engine.get(task_id)):
            raise HumanRequiredError("VAULT_RECONCILIATION_REQUIRED")
        return await super().resume_before_signing(task_id)

    async def run(self, task, tool, key, *, reconcile=False):
        if tool == "balance" and self.is_vault(task):
            integrity = await self.call("GET", "/audit/integrity/verify?limit=100000")
            if integrity.get("is_valid") is not True:
                raise HumanRequiredError("AUDIT_MISMATCH")
            state = await self.vault_status_for_task(task)
            return dict(
                tool="balance",
                mode="SEPOLIA",
                payment_backend="VAULT",
                balance_wei=str(state["balance"]),
                allowance_wei=str(state["remaining"]),
                agent_gas_balance_wei=str(state["agent_balance"]),
            )
        return await super().run(task, tool, key, reconcile=reconcile)

    async def wallet_status(self):
        result = await super().wallet_status()
        result["vault"] = await self.call("GET", "/vault/status")
        result["new_task_backend"] = (
            "VAULT" if self.settings.autonomy_vault_payments_enabled else "NATIVE"
        )
        return result
