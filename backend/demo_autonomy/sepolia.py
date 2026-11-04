"""Real Sepolia observations and bounded calls into the unchanged wallet pipeline.

No raw signing or broadcasting implementation exists here. Unknown delivery is
read-only reconciled; a restart never creates or submits another payment.
"""

import json
import re
import time

import httpx

from demo_autonomy.engine import HumanRequiredError
from demo_autonomy.sandbox import WaitingError, WalletServicesAdapter
from demo_autonomy.workflows import WorkflowEngine

HASH = re.compile(r"0x[0-9a-fA-F]{64}")


class SepoliaWorkflowEngine(WorkflowEngine):
    def __init__(self, settings, authority):
        if settings.mode != "SEPOLIA":
            raise ValueError("Separate Sepolia mode required")
        super().__init__(settings)
        self.authority = authority

    def initialize(self):
        super().initialize()
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fee_claims "
                "(task_id TEXT PRIMARY KEY, amount INTEGER NOT NULL)"
            )
            # A mode marker prevents reuse of simulation evidence or budgets.
            db.execute("CREATE TABLE IF NOT EXISTS profile_mode (mode TEXT PRIMARY KEY)")
            modes = [r[0] for r in db.execute("SELECT mode FROM profile_mode")]
            if (modes and modes != ["SEPOLIA"]) or (
                not modes and db.execute("SELECT id FROM tasks LIMIT 1").fetchone()
            ):
                raise ValueError("Cannot reuse a simulated task database")
            db.execute("INSERT OR IGNORE INTO profile_mode VALUES('SEPOLIA')")

    def configure(self, supplier, recipient, payment_cap, funding_cap):
        a = self.authority
        if (
            not a.payments_enabled
            or recipient.lower() != a.recipient.lower()
            or payment_cap > a.payment_budget_wei
            or funding_cap > a.funding_budget_wei
        ):
            raise HumanRequiredError("PROFILE_ADMIN_LIMITS_REQUIRED")
        super().configure(supplier, recipient, payment_cap, funding_cap)

    def allowed(self, task):
        current, mandate = super().allowed(task)
        a = self.authority
        if (
            not a.payments_enabled
            or mandate["recipient"] != a.recipient.lower()
            or current["amount"] > a.payment_budget_wei
        ):
            raise HumanRequiredError("PROFILE_ADMIN_LIMITS_REQUIRED")
        with self.db() as db:
            payments = db.execute("SELECT coalesce(sum(amount),0) FROM payment_claims").fetchone()[
                0
            ]
            funding = db.execute("SELECT coalesce(sum(amount),0) FROM funding_claims").fetchone()[0]
            fees = db.execute("SELECT coalesce(sum(amount),0) FROM fee_claims").fetchone()[0]
        if (
            payments > a.payment_budget_wei
            or funding > a.funding_budget_wei
            or fees > a.session_fee_budget_wei
        ):
            raise HumanRequiredError("PROFILE_BUDGET_TIGHTENED")
        return current, mandate

    def reserve_payment(self, task):
        # The local ledger is an effects journal, not a chain balance. The adapter
        # reads spendable balance including fees immediately before signing.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT task_id FROM payment_claims WHERE task_id!=? "
                "AND state IN ('RESERVED','UNCERTAIN')",
                (task["id"],),
            ).fetchone():
                raise WaitingError("OTHER_PAYMENT_RECONCILING")
            if db.execute(
                "SELECT task_id FROM payment_claims WHERE task_id=?", (task["id"],)
            ).fetchone():
                return
            used = db.execute("SELECT coalesce(sum(amount),0) FROM payment_claims").fetchone()[0]
            cap = min(json.loads(task["mandate"])["payment_cap"], self.authority.payment_budget_wei)
            if used + task["amount"] > cap:
                raise HumanRequiredError("SESSION_BUDGET_EXCEEDED")
            db.execute(
                "INSERT INTO payment_claims VALUES(?,?,'RESERVED')", (task["id"], task["amount"])
            )

    def reserve_fee(self, task):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT task_id FROM fee_claims WHERE task_id=?", (task["id"],)
            ).fetchone():
                return
            total = db.execute("SELECT coalesce(sum(amount),0) FROM fee_claims").fetchone()[0]
            if total + self.authority.max_payment_fee_wei > self.authority.session_fee_budget_wei:
                raise HumanRequiredError("SESSION_FEE_BUDGET_EXCEEDED")
            db.execute(
                "INSERT INTO fee_claims VALUES(?,?)",
                (task["id"], self.authority.max_payment_fee_wei),
            )

    async def fund(self, task, key, adapter, reconcile):
        link = adapter.link(task["id"])
        # Once requested, always reconcile the exact request, even if the wallet
        # now has enough ETH; otherwise recovery could hide an unknown delivery.
        if not link["funding_started"]:
            balance = await adapter.funding_balance(task)
            required = adapter.funding_requirement(task)
            if balance >= required:
                return {
                    "tool": "fund",
                    "mode": "SEPOLIA",
                    "funded_wei": 0,
                    "skipped": True,
                    "balance_wei": str(balance),
                }
        a = self.authority
        if not a.faucet_enabled:
            raise HumanRequiredError("FAUCET_NOT_CONFIGURED")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            claim = db.execute(
                "SELECT * FROM funding_claims WHERE task_id=?", (task["id"],)
            ).fetchone()
            if not claim:
                claims = db.execute("SELECT * FROM funding_claims").fetchall()
                rules = db.execute("SELECT * FROM workflow_rules WHERE id=1").fetchone()
                if len(claims) >= rules["max_funding_requests"] or any(
                    time.time() - c["created"] < rules["cooldown"] for c in claims
                ):
                    raise HumanRequiredError("FAUCET_COOLDOWN")
                if sum(c["amount"] for c in claims) + a.faucet_grant_ceiling_wei > min(
                    task["funding_cap"], a.funding_budget_wei
                ):
                    raise HumanRequiredError("FUNDING_BUDGET_EXCEEDED")
                db.execute(
                    "INSERT INTO funding_claims VALUES(?,?,?,'RESERVED')",
                    (task["id"], time.time(), a.faucet_grant_ceiling_wei),
                )
        self.allowed(task)
        return await adapter.run(task, "fund", key, reconcile=reconcile)


class SepoliaAdapter(WalletServicesAdapter):
    def __init__(self, engine, core_app, authority, address):
        self.authority, self.address = authority, address
        super().__init__(engine, core_app)

    def validate_profile(self):
        from pathlib import Path

        from eth_account import Account

        directory = self.engine.settings.directory.resolve()
        expected = f"sqlite+aiosqlite:///{directory / 'wallet-sepolia.sqlite3'}"
        if (
            self.settings.execution_mode != "sepolia"
            or self.settings.chain_id != 11155111
            or self.settings.app_port != 8001
            or self.settings.database_url != expected
            or not directory.name.startswith("kiteshield-sepolia-")
            or Path.cwd().resolve() != directory
            or Account.from_key(self.settings.signer_private_key).address != self.address
        ):
            raise RuntimeError("Separate Sepolia profile isolation failed")

    async def initialize(self):
        await super().initialize()
        with self.engine.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS chain_links (task_id TEXT PRIMARY KEY, "
                "limits_json TEXT NOT NULL, sign_started INTEGER NOT NULL DEFAULT 0)"
            )

    async def rpc(self, method, params):
        from app.core.live_rpc import validate_live_rpc_url

        if method not in {
            "eth_chainId",
            "eth_getBalance",
            "eth_getTransactionCount",
            "eth_getTransactionByHash",
            "eth_getTransactionReceipt",
            "eth_getBlockByNumber",
            "eth_blockNumber",
            "eth_getLogs",
        }:
            raise ValueError("Read-only RPC method required")
        validate_live_rpc_url(self.settings.sepolia_rpc_url)
        try:
            async with httpx.AsyncClient(
                timeout=10, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.settings.sepolia_rpc_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                response.raise_for_status()
                data = response.json()
            if (
                data.get("jsonrpc") != "2.0"
                or type(data.get("id")) is not int
                or data["id"] != 1
                or "error" in data
                or "result" not in data
            ):
                raise ValueError("Malformed RPC")
            return data["result"]
        except Exception:
            raise HumanRequiredError("SEPOLIA_RPC_UNAVAILABLE") from None

    async def require_chain(self):
        if await self.rpc("eth_chainId", []) != "0xaa36a7":
            raise HumanRequiredError("RPC_CHAIN_MISMATCH")

    async def balance(self):
        await self.require_chain()
        return int(await self.rpc("eth_getBalance", [self.address, "pending"]), 16)

    async def wallet_status(self):
        return {
            "mode": "SEPOLIA",
            "chain_id": 11155111,
            "address": self.address,
            "balance_wei": str(await self.balance()),
            "payments_enabled": self.authority.payments_enabled,
            "faucet_enabled": self.authority.faucet_enabled,
            "recipient": self.authority.recipient,
            "payment_budget_wei": str(self.authority.payment_budget_wei),
            "max_payment_fee_wei": str(self.authority.max_payment_fee_wei),
            "session_fee_budget_wei": str(self.authority.session_fee_budget_wei),
        }

    async def configure(self, recipient, cap, threshold):
        a = self.authority
        if (
            not a.payments_enabled
            or recipient.lower() != a.recipient.lower()
            or cap > a.payment_budget_wei
        ):
            raise HumanRequiredError("PROFILE_ADMIN_LIMITS_REQUIRED")
        await super().configure(recipient, cap, threshold)

    async def limits(self, task):
        from app.schemas import ExecutionLimits

        a = self.authority
        if (
            not a.payments_enabled
            or json.loads(task["mandate"])["recipient"] != a.recipient.lower()
            or task["amount"] > a.payment_budget_wei
        ):
            raise HumanRequiredError("PROFILE_ADMIN_LIMITS_REQUIRED")
        if a.max_gas_units * a.max_fee_per_gas_wei > a.max_payment_fee_wei:
            raise HumanRequiredError("PAYMENT_FEE_BUDGET_TOO_SMALL")
        if await self.balance() < task["amount"] + a.max_payment_fee_wei:
            raise HumanRequiredError("INSUFFICIENT_FUNDS_INCLUDING_GAS")
        nonce = int(await self.rpc("eth_getTransactionCount", [self.address, "pending"]), 16)
        return ExecutionLimits(
            sender=self.address,
            recipient=a.recipient,
            amount_wei=str(task["amount"]),
            chain_id=11155111,
            nonce=nonce,
            max_gas_units=a.max_gas_units,
            max_fee_per_gas_wei=a.max_fee_per_gas_wei,
            max_priority_fee_per_gas_wei=a.max_priority_fee_per_gas_wei,
            max_total_cost_wei=str(task["amount"] + a.max_payment_fee_wei),
        ).model_dump()

    async def verify_payment(self, task, tx_hash, limits):
        if not isinstance(tx_hash, str) or not HASH.fullmatch(tx_hash):
            raise HumanRequiredError("UNRESOLVED_PAYMENT")
        await self.require_chain()
        tx = await self.rpc("eth_getTransactionByHash", [tx_hash])
        receipt = await self.rpc("eth_getTransactionReceipt", [tx_hash])
        if tx is None or receipt is None:
            raise WaitingError("PAYMENT_RECEIPT_PENDING")
        if tx.get("blockHash") is None or tx.get("blockNumber") is None:
            # The two RPC observations may straddle the mining boundary.
            raise WaitingError("PAYMENT_BLOCK_EVIDENCE_PENDING")
        try:
            block = await self.rpc("eth_getBlockByNumber", [receipt["blockNumber"], False])
            if block is None:
                raise WaitingError("PAYMENT_BLOCK_EVIDENCE_PENDING")
            if (
                tx["hash"].lower() != tx_hash.lower()
                or receipt["transactionHash"].lower() != tx_hash.lower()
                or tx["from"].lower() != self.address.lower()
                or (tx.get("to") or "").lower() != limits["recipient"].lower()
                or int(tx["value"], 16) != task["amount"]
                or tx.get("input") != "0x"
                or int(tx["chainId"], 16) != 11155111
                or int(tx["nonce"], 16) != limits["nonce"]
                or int(tx["gas"], 16) > limits["max_gas_units"]
                or int(tx["maxFeePerGas"], 16) > limits["max_fee_per_gas_wei"]
                or int(tx["maxPriorityFeePerGas"], 16) > limits["max_priority_fee_per_gas_wei"]
                or int(receipt["gasUsed"], 16) > int(tx["gas"], 16)
                or int(receipt["effectiveGasPrice"], 16) > int(tx["maxFeePerGas"], 16)
                or tx["blockHash"] != receipt["blockHash"]
                or tx["blockNumber"] != receipt["blockNumber"]
                or block["hash"] != receipt["blockHash"]
                or int(receipt["blockNumber"], 16) <= 0
                or not HASH.fullmatch(receipt["blockHash"])
            ):
                raise ValueError("Mismatch")
            status = receipt["status"]
            if status not in {"0x0", "0x1"}:
                raise ValueError("Invalid status")
        except (KeyError, TypeError, ValueError):
            self.engine.issue(task["id"], "CHAIN_EVIDENCE_MISMATCH", anomaly=True)
            raise HumanRequiredError("CHAIN_EVIDENCE_MISMATCH") from None
        if status == "0x0":
            raise HumanRequiredError("ONCHAIN_PAYMENT_REVERTED")
        return {
            "tool": "payment",
            "mode": "SEPOLIA",
            "paid_wei": task["amount"],
            "tx_hash": tx_hash,
            "receipt_id": tx_hash,
            "verified": True,
            "recipient": limits["recipient"],
            "confirmations_required": 1,
            "block_number": int(receipt["blockNumber"], 16),
            "fee_paid_wei": str(
                int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16)
            ),
            "explorer_url": "https://sepolia.etherscan.io/tx/" + tx_hash,
        }

    async def reconcile_existing_payment(self, task_id):
        """Observe a saved hash while paused; never evaluates, signs or sends."""
        task = self.engine.get(task_id)
        if len(task["steps"]) != 4 or any(
            step["state"] != "COMPLETED" for step in task["steps"][:2]
        ):
            raise HumanRequiredError("WORKFLOW_PREREQUISITES_REQUIRED")
        link = self.link(task_id)
        if not link["proposal_id"]:
            raise HumanRequiredError("BOUND_PROPOSAL_REQUIRED")
        with self.engine.db() as db:
            row = db.execute(
                "SELECT limits_json FROM chain_links WHERE task_id=?", (task_id,)
            ).fetchone()
        if not row:
            raise HumanRequiredError("EXECUTION_LIMITS_REQUIRED")
        proposal = await self.call("GET", f"/proposals/{link['proposal_id']}")
        tx = proposal.get("transaction")
        if not tx or tx.get("execution_mode") != "sepolia":
            raise HumanRequiredError("EXISTING_SEPOLIA_TRANSACTION_REQUIRED")
        payment = await self.verify_payment(task, tx.get("tx_hash"), json.loads(row[0]))
        core = await self.call("GET", f"/transactions/{tx['id']}")
        if core.get("execution_outcome") != "CONFIRMED":
            raise WaitingError("PAYMENT_RECEIPT_PENDING")
        payment.update(
            proposal_id=link["proposal_id"], mandate_version=json.loads(task["mandate"])["version"]
        )
        receipt = {**payment, "tool": "receipt"}
        receipt.pop("paid_wei")
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for position, result in ((2, payment), (3, receipt)):
                key = f"{task_id}:{position}"
                inserted = db.execute(
                    "INSERT OR IGNORE INTO effects VALUES(?,?)", (key, json.dumps(result))
                ).rowcount
                if inserted:
                    db.execute(
                        "UPDATE ledger SET balance=balance-? WHERE id=1",
                        (result.get("paid_wei", 0),),
                    )
                    self.engine.event(db, task_id, "STEP_COMPLETED", json.dumps(result))
                db.execute(
                    "UPDATE steps SET state='COMPLETED',result=?,lease=NULL,owner=NULL "
                    "WHERE task_id=? AND position=?",
                    (json.dumps(result), task_id, position),
                )
            db.execute("UPDATE payment_claims SET state='COMMITTED' WHERE task_id=?", (task_id,))
            db.execute("UPDATE tasks SET state='COMPLETED',reason=NULL WHERE id=?", (task_id,))
            db.execute(
                "UPDATE issues SET resolved=1 WHERE task_id=? AND reason IN "
                "('CHAIN_EVIDENCE_MISMATCH','RECONCILIATION_UNAVAILABLE')",
                (task_id,),
            )
            self.engine.event(
                db,
                task_id,
                "TASK_RECONCILED",
                "Existing mined hash verified; no signing or broadcast; quarantine unchanged",
            )
        return {
            "task_id": task_id,
            "state": "COMPLETED",
            "tx_hash": payment["tx_hash"],
            "explorer_url": payment["explorer_url"],
            "read_only_reconciliation": True,
        }

    async def payment_guard(self, task, proposal=None):
        """Optional extra restrictions from a main-wallet integration."""

    async def proposal_ready(self, task, proposal):
        """Main-wallet integration may attach an existing vendor binding."""

    async def payment(self, task, reconcile=False):
        await self.payment_guard(task)
        link = self.link(task["id"])
        proposal = link["proposal_id"] or await self.find_proposal(task)
        if not proposal:
            if reconcile or link["payment_started"]:
                raise HumanRequiredError("UNRESOLVED_PAYMENT")
            self.save(task["id"], "payment_started", 1)
            recipient = json.loads(task["mandate"])["recipient"]
            answer = await self.call(
                "POST",
                "/proposals",
                data={
                    "prompt": f"Send {task['amount']} wei to {recipient}",
                    "recipient": recipient,
                    "amount_wei": str(task["amount"]),
                    "chain_id": 11155111,
                    "asset_type": "NATIVE_ETH",
                },
                correlation="goal-" + task["id"],
            )
            proposal = answer["id"]
        self.save(task["id"], "proposal_id", proposal)
        await self.proposal_ready(task, proposal)
        answer = await self.call("GET", f"/proposals/{proposal}")
        if answer["status"] == "PROPOSED":
            answer = await self.call("POST", f"/proposals/{proposal}/evaluate")
        if answer["status"] == "ESCALATED":
            status = answer["approval"]["status"]
            if status in {"EXPIRED", "REJECTED"}:
                raise HumanRequiredError("APPROVAL_" + status)
            raise WaitingError("HUMAN_APPROVAL_REQUIRED", approval=True)
        if answer["status"] in {"BLOCKED", "REJECTED", "EXPIRED_APPROVAL"}:
            raise HumanRequiredError("POLICY_" + answer["status"])
        with self.engine.db() as db:
            chain_link = db.execute(
                "SELECT * FROM chain_links WHERE task_id=?", (task["id"],)
            ).fetchone()
        if not chain_link:
            limits = await self.limits(task)
            with self.engine.db() as db:
                db.execute(
                    "INSERT INTO chain_links VALUES(?,?,0)", (task["id"], json.dumps(limits))
                )
        else:
            limits = json.loads(chain_link["limits_json"])
        tx = answer.get("transaction")
        if not tx and answer["status"] in {"ALLOWED", "APPROVED"}:
            # A lost response or crash after this persisted marker NEVER retries
            # the sign route. Only the same durable transaction may be observed.
            if chain_link and chain_link["sign_started"]:
                raise HumanRequiredError("UNRESOLVED_SIGNING_OUTCOME")
            self.engine.allowed(task)
            await self.payment_guard(task, proposal)
            a = self.authority
            if (
                limits["max_gas_units"] > a.max_gas_units
                or limits["max_fee_per_gas_wei"] > a.max_fee_per_gas_wei
                or limits["max_priority_fee_per_gas_wei"] > a.max_priority_fee_per_gas_wei
                or int(limits["max_total_cost_wei"]) > task["amount"] + a.max_payment_fee_wei
            ):
                raise HumanRequiredError("PROFILE_FEE_LIMITS_TIGHTENED")
            self.engine.reserve_fee(task)
            with self.engine.db() as db:
                db.execute("UPDATE chain_links SET sign_started=1 WHERE task_id=?", (task["id"],))
            try:
                answer = await self.call("POST", f"/proposals/{proposal}/sign", data=limits)
            except Exception:
                raise WaitingError("SIGNING_OUTCOME_RECONCILING") from None
            tx = answer.get("transaction")
        if not tx or tx.get("execution_mode") != "sepolia":
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
                        {
                            "mode": "SEPOLIA",
                            "tx_hash": tx.get("tx_hash"),
                        }
                    ),
                )
        result = await self.verify_payment(task, tx.get("tx_hash"), limits)
        # Existing read-only reconciler records confirmation in the core audit.
        await self.call("GET", f"/transactions/{tx['id']}")
        result["proposal_id"] = proposal
        return result

    async def funding_balance(self, task):
        return await self.balance()

    def funding_requirement(self, task):
        return task["amount"] + self.authority.max_payment_fee_wei

    def funding_address(self, task):
        return self.address

    async def fund(self, task, reconcile=False):
        link = self.link(task["id"])
        if not link["funding_id"]:
            if reconcile or link["funding_started"]:
                raise HumanRequiredError("UNRESOLVED_FUNDING")
            self.save(task["id"], "funding_started", 1)
            answer = await self.call(
                "POST",
                "/funding/plan",
                data={
                    "prompt": "Fund my wallet with Sepolia test ETH",
                    "address": self.funding_address(task),
                },
            )
            self.save(task["id"], "funding_id", answer["id"])
            link = self.link(task["id"])
        answer = await self.call("POST", f"/funding/{link['funding_id']}/request")
        # The existing adapter owns one POST, cooldown, and unknown-delivery lock.
        answer = await self.call("GET", f"/funding/{link['funding_id']}")
        if (answer.get("address") or "").lower() != self.funding_address(task).lower():
            self.engine.issue(task["id"], "FUNDING_TARGET_MISMATCH", anomaly=True)
            raise HumanRequiredError("FUNDING_TARGET_MISMATCH")
        if answer["state"] == "SUBMITTED":
            raise WaitingError("FUNDING_RECEIPT_PENDING")
        if answer["state"] != "CONFIRMED" or answer["mode"] != "sepolia":
            raise HumanRequiredError("FUNDING_" + answer["state"])
        amount = int(answer["amount_wei"])
        if amount <= 0 or amount > min(
            task["funding_cap"], self.authority.faucet_grant_ceiling_wei
        ):
            self.engine.issue(task["id"], "UNEXPECTED_FUNDING_AMOUNT", anomaly=True)
            raise HumanRequiredError("UNEXPECTED_FUNDING_AMOUNT")
        return {
            "tool": "fund",
            "mode": "SEPOLIA",
            "funded_wei": amount,
            "funding_request_id": answer["id"],
            "receipt_id": answer["tx_hash"],
            "tx_hash": answer["tx_hash"],
            "explorer_url": answer["explorer_url"],
            "provider": "existing_faucet_adapter",
        }

    async def run(self, task, tool, key, *, reconcile=False):
        integrity = await self.call("GET", "/audit/integrity/verify?limit=100000")
        if integrity.get("is_valid") is not True:
            raise HumanRequiredError("AUDIT_MISMATCH")
        if tool == "balance":
            return {"tool": tool, "mode": "SEPOLIA", "balance_wei": str(await self.balance())}
        if tool == "payment":
            return await self.payment(task, reconcile)
        if tool == "fund":
            return await self.fund(task, reconcile)
        if tool == "receipt":
            with self.engine.db() as db:
                paid = db.execute(
                    "SELECT result FROM effects WHERE key=?", (task["id"] + ":2",)
                ).fetchone()
                link = db.execute(
                    "SELECT limits_json FROM chain_links WHERE task_id=?", (task["id"],)
                ).fetchone()
            if not paid or not link:
                raise HumanRequiredError("PAYMENT_NOT_VERIFIED")
            result = await self.verify_payment(
                task, json.loads(paid[0])["tx_hash"], json.loads(link[0])
            )
            result.pop("paid_wei")  # Verification must never debit the journal twice.
            result["tool"] = "receipt"
            return result
        raise HumanRequiredError("UNKNOWN_TOOL")
