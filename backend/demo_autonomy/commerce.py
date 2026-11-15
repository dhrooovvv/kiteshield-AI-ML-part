"""One bounded digital purchase, attached to the existing durable vault workflow.

The local demo merchant supplies a synthetic report. No external shop code or
wallet SDK is used. Invoices here are evidence, never a second payment producer.
"""

import hashlib
import json
import re
import time
import uuid
from contextlib import suppress

from demo_autonomy.engine import HumanRequiredError

PRICE = 10_000_000_000_000
GOAL = (
    "Buy the developer report from the approved shop for at most 0.00001 ETH and save the invoice."
)
PRODUCT = {
    "id": "developer-report",
    "name": "Developer field guide",
    "description": "A downloadable guide to bounded autonomous payments. Demo digital product.",
    "price_wei": str(PRICE),
    "currency": "ETH",
}
REPORT = """# Developer field guide

A demo digital product delivered by KiteShield's local merchant.

## Bounded autonomous payments

1. Save an immutable merchant quote and an explicit spending mandate.
2. Validate the exact merchant, item, amount, network and quote expiry.
3. Associate one order with one durable payment operation.
4. Verify the guarded-vault payment before fulfilling the order.
5. Reuse persisted payment evidence after a retry or restart.

This educational artifact is synthetic. Its delivery demonstrates software
fulfillment and does not represent a third-party commercial purchase.
"""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Commerce:
    def __init__(self, engine):
        self.engine = engine

    def initialize(self):
        with self.engine.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS commerce_orders (
                    id TEXT PRIMARY KEY, goal TEXT NOT NULL, scenario TEXT NOT NULL,
                    quote TEXT NOT NULL, mandate TEXT NOT NULL, created REAL NOT NULL,
                    task_id TEXT UNIQUE, state TEXT NOT NULL, reason TEXT,
                    tx_hash TEXT UNIQUE, delivered REAL);
                CREATE TABLE IF NOT EXISTS commerce_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL
                    REFERENCES commerce_orders(id), kind TEXT NOT NULL, detail TEXT NOT NULL);
            """)

    def require_enabled(self):
        if not self.engine.settings.commerce_enabled:
            raise HumanRequiredError("COMMERCE_DISABLED")
        self.engine.require_enabled()

    @staticmethod
    def event(db, order_id, kind, detail):
        db.execute(
            "INSERT INTO commerce_events(order_id,kind,detail) VALUES(?,?,?)",
            (order_id, kind, detail),
        )

    def mandate(self):
        with self.engine.db() as db:
            row = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
        if row is None:
            raise HumanRequiredError("ADMIN_MANDATE_REQUIRED")
        return dict(row)

    def catalog(self):
        self.require_enabled()
        reason = None
        merchant = None
        try:
            mandate = self.mandate()
            merchant = {"name": mandate["supplier"], "recipient": mandate["recipient"]}
            if mandate["payment_cap"] < PRICE:
                raise HumanRequiredError("PAYMENT_BUDGET_EXCEEDED")
            if (
                self.engine.settings.mode == "SEPOLIA"
                and self.engine.context_for_new_task().get("backend") != "VAULT"
            ):
                raise HumanRequiredError("COMMERCE_VAULT_REQUIRED")
            if hasattr(self.engine, "control") and self.engine.control()["quarantined"]:
                raise HumanRequiredError("SELF_QUARANTINED")
        except (HumanRequiredError, ValueError) as exc:
            reason = str(exc)
        return {
            "enabled": True,
            "mode": self.engine.settings.mode,
            "product": PRODUCT,
            "merchant": merchant,
            "ready": reason is None,
            "reason": reason,
            "goal": GOAL,
        }

    def create(self, order_id, goal, scenario="standard"):
        self.require_enabled()
        try:
            if str(uuid.UUID(order_id)) != order_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("INVALID_ORDER_ID") from exc
        if goal.strip().casefold() != GOAL.casefold():
            raise HumanRequiredError("EXPLICIT_PURCHASE_GOAL_REQUIRED")
        if scenario not in {"standard", "tampered"}:
            raise ValueError("INVALID_CHECKOUT_SCENARIO")
        with self.engine.db() as db:
            previous = db.execute(
                "SELECT * FROM commerce_orders WHERE id=?", (order_id,)
            ).fetchone()
        if previous:
            if previous["goal"] != goal or previous["scenario"] != scenario:
                raise ValueError("ORDER_IDEMPOTENCY_CONFLICT")
            if (
                previous["task_id"] is None
                and previous["state"] in {"QUOTED", "ON_HOLD"}
                and scenario == "standard"
            ):
                saved = json.loads(previous["quote"])
                return self.checkout(
                    order_id, saved["digest"], saved["total_wei"], saved["recipient"]
                )
            return self.get(order_id)
        mandate = self.mandate()
        if mandate["payment_cap"] < PRICE:
            raise HumanRequiredError("PAYMENT_BUDGET_EXCEEDED")
        now = time.time()
        quote = {
            "order_id": order_id,
            "merchant": mandate["supplier"],
            "recipient": mandate["recipient"],
            "mandate_version": mandate["version"],
            "product_id": PRODUCT["id"],
            "total_wei": str(PRICE),
            "currency": "ETH",
            "chain_id": 11155111,
            "expires_at": now + 600,
            "line_items": [{"name": PRODUCT["name"], "amount_wei": str(PRICE)}],
        }
        quote["digest"] = digest(quote)
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute(
                "INSERT OR IGNORE INTO commerce_orders "
                "VALUES(?,?,?,?,?,?,NULL,'QUOTED',NULL,NULL,NULL)",
                (order_id, goal, scenario, json.dumps(quote), json.dumps(mandate), now),
            ).rowcount
            if inserted:
                self.event(
                    db, order_id, "QUOTE_RECEIVED", "Exact ETH quote from local demo merchant"
                )
                self.event(
                    db,
                    order_id,
                    "INVOICE_SAVED",
                    "Invoice bound to this order; no separate payment",
                )
            else:
                previous = db.execute(
                    "SELECT * FROM commerce_orders WHERE id=?", (order_id,)
                ).fetchone()
                if previous["goal"] != goal or previous["scenario"] != scenario:
                    raise ValueError("ORDER_IDEMPOTENCY_CONFLICT")
                quote = json.loads(previous["quote"])
        try:
            return self.checkout(
                order_id,
                quote["digest"],
                str(PRICE + 1 if scenario == "tampered" else PRICE),
                quote["recipient"],
            )
        except HumanRequiredError:
            return self.get(order_id)

    def checkout(self, order_id, quote_digest, total_wei, recipient):
        self.require_enabled()
        with self.engine.db() as db:
            row = db.execute("SELECT * FROM commerce_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise KeyError(order_id)
        quote = json.loads(row["quote"])
        reason = None
        if quote_digest != quote["digest"]:
            reason = "QUOTE_DIGEST_MISMATCH"
        elif str(total_wei) != quote["total_wei"]:
            reason = "CHECKOUT_TOTAL_CHANGED"
        elif recipient.lower() != quote["recipient"].lower():
            reason = "CHECKOUT_RECIPIENT_CHANGED"
        # Existing orders remain recoverable after expiry; no fresh payment is initiated.
        elif row["task_id"] is None and time.time() > quote["expires_at"]:
            reason = "QUOTE_EXPIRED"
        if reason:
            with self.engine.db() as db:
                self.event(db, order_id, "CHECKOUT_BLOCKED", reason)
                db.execute(
                    "UPDATE commerce_orders SET state='BLOCKED',reason=? "
                    "WHERE id=? AND task_id IS NULL",
                    (reason, order_id),
                )
            raise HumanRequiredError(reason)
        if row["scenario"] == "tampered" or row["state"] == "BLOCKED":
            raise HumanRequiredError(row["reason"] or "CHECKOUT_BLOCKED")
        if row["task_id"]:
            return self.get(order_id)
        mandate = json.loads(row["mandate"])
        canonical_goal = f"fund if needed, pay supplier {mandate['supplier']} {PRICE} wei, verify"
        try:
            task_id = self.engine.create(
                canonical_goal,
                "purchase_" + order_id,
                expected_mandate=mandate,
                required_backend="VAULT" if self.engine.settings.mode == "SEPOLIA" else None,
            )
        except (HumanRequiredError, ValueError) as exc:
            with self.engine.db() as db:
                db.execute(
                    "UPDATE commerce_orders SET state='ON_HOLD',reason=? WHERE id=?",
                    (str(exc), order_id),
                )
                self.event(db, order_id, "PURCHASE_HELD", str(exc))
            raise
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE commerce_orders SET task_id=?,state='RUNNING',reason=NULL "
                "WHERE id=? AND task_id IS NULL",
                (task_id, order_id),
            ).rowcount
            if changed:
                self.event(
                    db, order_id, "CHECKOUT_VALIDATED", "Merchant, item, total and mandate bound"
                )
                self.event(db, order_id, "TASK_LINKED", task_id)
        return self.get(order_id)

    def _bound_task(self, task, row):
        mandate = json.loads(row["mandate"])
        return (
            task["goal"]
            == f"fund if needed, pay supplier {mandate['supplier']} {PRICE} wei, verify"
            and task["amount"] == PRICE
            and json.loads(task["mandate"]) == mandate
            and (self.engine.settings.mode != "SEPOLIA" or task.get("payment_backend") == "VAULT")
        )

    def _recover_link(self, order_id):
        # Reattach the exact task after a crash between the two durable commits.
        with self.engine.db() as db:
            row = db.execute("SELECT * FROM commerce_orders WHERE id=?", (order_id,)).fetchone()
            prior = db.execute(
                "SELECT id FROM tasks WHERE request_key=?", ("purchase_" + order_id,)
            ).fetchone()
        if row and not row["task_id"] and row["scenario"] == "standard" and prior:
            task = self.engine.get(prior["id"])
            if not self._bound_task(task, row):
                return
            with self.engine.db() as db:
                db.execute(
                    "UPDATE commerce_orders SET task_id=?,state='RUNNING',reason=NULL "
                    "WHERE id=? AND task_id IS NULL",
                    (task["id"], order_id),
                )

    def resume_pending(self):
        with self.engine.db() as db:
            rows = db.execute(
                "SELECT id,quote FROM commerce_orders WHERE state='QUOTED' "
                "AND task_id IS NULL AND scenario='standard'"
            ).fetchall()
        for row in rows:
            quote = json.loads(row["quote"])
            # checkout persists its blocked/held reason and will not loop.
            with suppress(HumanRequiredError, ValueError):
                self.checkout(row["id"], quote["digest"], quote["total_wei"], quote["recipient"])

    def get(self, order_id):
        self.require_enabled()
        self._recover_link(order_id)
        with self.engine.db() as db:
            row = db.execute("SELECT * FROM commerce_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise KeyError(order_id)
        quote = json.loads(row["quote"])
        task = self.engine.get(row["task_id"]) if row["task_id"] else None
        if task:
            task["funding_cap"] = str(task["funding_cap"])
        receipt = None
        state, reason = row["state"], row["reason"]
        if task:
            state = task["state"]
            reason = task["reason"]
            if not self._bound_task(task, row):
                state, reason = "ON_HOLD", "ORDER_TASK_BINDING_MISMATCH"
            elif task["state"] == "COMPLETED":
                if self.engine.settings.mode != "SEPOLIA":
                    state = "SIMULATED"
                else:
                    receipt = self._receipt(task, quote)
                    if receipt is None:
                        state, reason = "ON_HOLD", "PAYMENT_EVIDENCE_MISMATCH"
                    else:
                        with self.engine.db() as db:
                            db.execute("BEGIN IMMEDIATE")
                            claimed = db.execute(
                                "SELECT id FROM commerce_orders WHERE tx_hash=? AND id<>?",
                                (receipt["tx_hash"], order_id),
                            ).fetchone()
                            if claimed:
                                receipt = None
                                state, reason = "ON_HOLD", "PAYMENT_ALREADY_CLAIMED"
                                updated = 0
                            else:
                                updated = db.execute(
                                    "UPDATE commerce_orders "
                                    "SET state='DELIVERED',tx_hash=?,delivered=? "
                                    "WHERE id=? AND delivered IS NULL",
                                    (receipt["tx_hash"], time.time(), order_id),
                                ).rowcount
                            if updated:
                                self.event(db, order_id, "PAYMENT_VERIFIED", receipt["tx_hash"])
                                self.event(
                                    db,
                                    order_id,
                                    "PRODUCT_DELIVERED",
                                    "Developer field guide unlocked",
                                )
                        if receipt is not None:
                            state = "DELIVERED"
        with self.engine.db() as db:
            events = [
                dict(event)
                for event in db.execute(
                    "SELECT id,kind,detail FROM commerce_events WHERE order_id=? ORDER BY id",
                    (order_id,),
                )
            ]
        delivered = state == "DELIVERED"
        return {
            "id": order_id,
            "mode": self.engine.settings.mode,
            "state": state,
            "reason": reason,
            "created_at": row["created"],
            "merchant": {"name": quote["merchant"], "recipient": quote["recipient"]},
            "product": PRODUCT,
            "quote": quote,
            "task_id": row["task_id"],
            "task": task,
            "invoice": {
                "number": "KS-" + order_id.replace("-", "").upper(),
                "total_wei": str(PRICE),
                "status": "PAID"
                if delivered
                else "SIMULATED"
                if state == "SIMULATED"
                else "UNPAID",
            },
            "events": events,
            "receipt": receipt,
            "delivered": delivered,
            "artifact": {
                "name": "developer-field-guide.md",
                "content": REPORT,
                "mime_type": "text/markdown",
            }
            if delivered
            else None,
        }

    @staticmethod
    def _receipt(task, quote):
        if task.get("payment_backend") != "VAULT" or task["amount"] != int(quote["total_wei"]):
            return None
        try:
            results = {
                step["tool"]: json.loads(step["result"] or "{}")
                for step in task["steps"]
                if step["tool"] in {"payment", "receipt"} and step["state"] == "COMPLETED"
            }
            payment, receipt = results["payment"], results["receipt"]
            for evidence in (payment, receipt):
                if (
                    evidence.get("mode") != "SEPOLIA"
                    or evidence.get("payment_backend") != "VAULT"
                    or evidence.get("verified") is not True
                    or evidence.get("recipient", "").lower() != quote["recipient"].lower()
                    or not re.fullmatch(r"0x[0-9a-fA-F]{64}", evidence.get("tx_hash", ""))
                ):
                    return None
            if payment["tx_hash"] != receipt["tx_hash"] or payment.get("paid_wei") != int(
                quote["total_wei"]
            ):
                return None
            return {
                "tx_hash": payment["tx_hash"],
                "explorer_url": "https://sepolia.etherscan.io/tx/" + payment["tx_hash"],
            }
        except (KeyError, TypeError, ValueError):
            return None

    def list(self):
        self.require_enabled()
        with self.engine.db() as db:
            ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM commerce_orders ORDER BY created DESC LIMIT 30"
                )
            ]
        return {"orders": [self.get(order_id) for order_id in ids]}
