"""Persisted workflow rules and self-quarantine outside financial authority code."""

import json
import re
import time
import uuid

from demo_autonomy.engine import Engine, HumanRequiredError
from demo_autonomy.sandbox import WaitingError


class WorkflowEngine(Engine):
    def initialize(self):
        super().initialize()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY, task_id TEXT, reason TEXT NOT NULL,
                    created REAL NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS workflow_control (
                    id INTEGER PRIMARY KEY CHECK(id=1), quarantined INTEGER NOT NULL DEFAULT 0,
                    epoch INTEGER NOT NULL DEFAULT 0, blocks INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO workflow_control(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS workflow_rules (
                    id INTEGER PRIMARY KEY CHECK(id=1), cooldown REAL NOT NULL,
                    max_funding_requests INTEGER NOT NULL);
                INSERT OR IGNORE INTO workflow_rules VALUES(1,86400,1);
                CREATE TABLE IF NOT EXISTS progress (
                    task_id TEXT NOT NULL, position INTEGER NOT NULL, deadline REAL NOT NULL,
                    PRIMARY KEY(task_id,position));
                CREATE TABLE IF NOT EXISTS payment_claims (
                    task_id TEXT PRIMARY KEY, amount INTEGER NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS funding_claims (
                    task_id TEXT PRIMARY KEY, created REAL NOT NULL, amount INTEGER NOT NULL,
                    state TEXT NOT NULL);
            """)

    def control(self):
        with self.db() as db:
            return dict(db.execute("SELECT * FROM workflow_control WHERE id=1").fetchone())

    def issue(self, task_id, reason, anomaly=False):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT id FROM issues WHERE task_id IS ? AND reason=? AND resolved=0",
                (task_id, reason),
            ).fetchone():
                db.execute(
                    "INSERT INTO issues VALUES(?,?,?,?,0)",
                    (str(uuid.uuid4()), task_id, reason, time.time()),
                )
                self.event(db, task_id or "system", "ISSUE_RAISED", reason)
            db.execute("UPDATE workflow_control SET blocks=blocks+1 WHERE id=1")
            blocks = db.execute("SELECT blocks FROM workflow_control WHERE id=1").fetchone()[0]
            if self.settings.quarantine_enabled and (anomaly or blocks >= 3):
                db.execute("UPDATE workflow_control SET quarantined=1,epoch=epoch+1 WHERE id=1")
                self.event(db, "system", "SELF_QUARANTINED", reason)

    def resume(self):
        # Only reachable through the administrator endpoint. Never an agent tool.
        with self.db() as db:
            db.execute(
                "UPDATE workflow_control SET quarantined=0,blocks=0,epoch=epoch+1 WHERE id=1"
            )
            self.event(db, "system", "ADMIN_RESUMED", "Administrator resumed execution")

    def external_event(self, kind):
        if kind in {"permission_claim", "incoming_token_permission", "incoming_nft_permission"}:
            self.issue(None, "UNTRUSTED_PERMISSION_EVENT", anomaly=True)
        else:
            with self.db() as db:
                self.event(db, "system", "EXTERNAL_DATA_ONLY", kind)

    def create(self, goal, request_key):
        if self.control()["quarantined"]:
            raise HumanRequiredError("SELF_QUARANTINED")
        if re.search(
            r"ignore|override|private key|system prompt|approve (?:yourself|my)|disable", goal, re.I
        ):
            self.issue(None, "INJECTION_FLAGGED", anomaly=True)
            raise HumanRequiredError("INJECTION_FLAGGED")
        # All interpretation of amount and supplier remains deterministic.
        goal = re.sub(
            r"^fund my wallet if needed, then pay ([0-9]+) wei to supplier "
            r"([A-Za-z -]+) and verify[.!]?$",
            lambda m: f"fund if needed, pay supplier {m[2]} {m[1]} wei, verify",
            goal,
            flags=re.I,
        )
        try:
            return super().create(goal, request_key)
        except (HumanRequiredError, ValueError):
            self.issue(None, "GOAL_VALIDATION_BLOCK")
            raise

    def hold(self, task_id, reason):
        super().hold(task_id, reason)
        self.issue(
            task_id,
            reason,
            anomaly=reason
            in {
                "BALANCE_MISMATCH",
                "AUDIT_MISMATCH",
                "PROPOSAL_BINDING_MISMATCH",
                "DUPLICATE_PROPOSAL_ANOMALY",
            },
        )

    def allowed(self, task):
        self.require_enabled()
        with self.db() as db:
            control = db.execute("SELECT * FROM workflow_control WHERE id=1").fetchone()
            current = db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
            mandate = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
            if control["quarantined"]:
                raise HumanRequiredError("SELF_QUARANTINED")
            if not current or current["state"] not in {"READY", "WAITING_APPROVAL"}:
                raise HumanRequiredError("TASK_NOT_EXECUTABLE")
            if not mandate or json.loads(current["mandate"]) != dict(mandate):
                raise HumanRequiredError("MANDATE_CHANGED")
            claim = db.execute(
                "SELECT amount FROM funding_claims WHERE task_id=?", (task["id"],)
            ).fetchone()
            if claim and claim[0] > current["funding_cap"]:
                raise HumanRequiredError("TASK_FUNDING_BUDGET")
            if current["amount"] > current["payment_cap"]:
                raise HumanRequiredError("TASK_BUDGET")
            used = [json.loads(r[0]) for r in db.execute("SELECT result FROM effects")]
            total = sum(r.get("funded_wei", 0) - r.get("paid_wei", 0) for r in used)
            balance = db.execute("SELECT balance FROM ledger WHERE id=1").fetchone()[0]
            if balance != total:
                raise HumanRequiredError("BALANCE_MISMATCH")
            # Outstanding claims count against the mandate, not just finished payments.
            exposure = sum(
                r[0] for r in db.execute("SELECT amount FROM funding_claims WHERE state!='FAILED'")
            )
            if exposure > mandate["funding_cap"]:
                raise HumanRequiredError("FUNDING_BUDGET_EXCEEDED")
        return dict(current), dict(mandate)

    async def tick(self, task_id, adapter):
        task = self.get(task_id)
        if task["state"] not in {"READY", "WAITING_APPROVAL"}:
            return
        if self.control()["quarantined"]:
            return
        try:
            task, mandate = self.allowed(task)
        except HumanRequiredError as exc:
            self.hold(task_id, str(exc))
            return
        owner = str(uuid.uuid4())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            step = db.execute(
                "SELECT * FROM steps WHERE task_id=? AND state!='COMPLETED' "
                "ORDER BY position LIMIT 1",
                (task_id,),
            ).fetchone()
            if not step:
                db.execute("UPDATE tasks SET state='COMPLETED',reason=NULL WHERE id=?", (task_id,))
                self.event(db, task_id, "TASK_COMPLETED", "SIMULATED")
                return
            if step["lease"] and step["lease"] > time.time():
                return
            progress = db.execute(
                "SELECT deadline FROM progress WHERE task_id=? AND position=?",
                (task_id, step["position"]),
            ).fetchone()
            if progress and time.time() > progress[0]:
                # Close after leaving this transaction to avoid nested SQLite writer locks.
                expired = True
            else:
                expired = False
                db.execute(
                    "INSERT OR IGNORE INTO progress VALUES(?,?,?)",
                    (task_id, step["position"], time.time() + 300),
                )
                db.execute(
                    "UPDATE steps SET owner=?,lease=?,state='RUNNING' "
                    "WHERE task_id=? AND position=?",
                    (owner, time.time() + self.settings.lease_seconds, task_id, step["position"]),
                )
                self.event(db, task_id, "STEP_STARTED", step["tool"])
        if expired:
            self.hold(task_id, "STEP_DEADLINE_EXCEEDED")
            return
        key = f"{task_id}:{step['position']}"
        try:
            with self.db() as db:
                prior = db.execute("SELECT result FROM effects WHERE key=?", (key,)).fetchone()
            if prior:
                result = json.loads(prior[0])
            else:
                reconcile = step["state"] in {"RUNNING", "UNCERTAIN", "WAITING"}
                if step["tool"] == "fund":
                    result = await self.fund(task, key, adapter, reconcile)
                elif step["tool"] == "balance":
                    with self.db() as db:
                        value = db.execute("SELECT balance FROM ledger WHERE id=1").fetchone()[0]
                    result = {"tool": "balance", "balance_wei": value, "mode": "SIMULATED"}
                else:
                    # Every payment is bound to the original task; adapter rechecks again
                    # immediately before requesting existing coordinator execution.
                    self.allowed(task)
                    if step["tool"] == "payment":
                        self.reserve_payment(task)
                    result = await adapter.run(task, step["tool"], key, reconcile=reconcile)
                if result is None:
                    raise HumanRequiredError("UNRESOLVED_OUTCOME")
                with self.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if not db.execute("SELECT key FROM effects WHERE key=?", (key,)).fetchone():
                        result["mandate_version"] = mandate["version"]
                        delta = result.get("funded_wei", 0) - result.get("paid_wei", 0)
                        db.execute("UPDATE ledger SET balance=balance+? WHERE id=1", (delta,))
                        db.execute("INSERT INTO effects VALUES(?,?)", (key, json.dumps(result)))
                        if step["tool"] == "payment":
                            db.execute(
                                "UPDATE payment_claims SET state='COMMITTED' WHERE task_id=?",
                                (task_id,),
                            )
                        if step["tool"] == "fund":
                            db.execute(
                                "UPDATE funding_claims SET state='VERIFIED' WHERE task_id=?",
                                (task_id,),
                            )
            with self.db() as db:
                db.execute(
                    "UPDATE steps SET state='COMPLETED',result=?,lease=NULL WHERE task_id=? "
                    "AND position=? AND owner=?",
                    (json.dumps(result), task_id, step["position"], owner),
                )
                db.execute("UPDATE tasks SET state='READY',reason=NULL WHERE id=?", (task_id,))
                self.event(db, task_id, "STEP_COMPLETED", json.dumps(result))
        except WaitingError as exc:
            with self.db() as db:
                if exc.approval:
                    db.execute(
                        "DELETE FROM payment_claims WHERE task_id=? AND state='RESERVED'",
                        (task_id,),
                    )
                db.execute(
                    "UPDATE steps SET state='WAITING',lease=? "
                    "WHERE task_id=? AND position=? AND owner=?",
                    (time.time() + 2, task_id, step["position"], owner),
                )
                db.execute(
                    "UPDATE tasks SET state=?,reason=? WHERE id=?",
                    ("WAITING_APPROVAL" if exc.approval else "READY", str(exc), task_id),
                )
                self.event(
                    db,
                    task_id,
                    "APPROVAL_REQUESTED" if exc.approval else "WAITING_RECEIPT",
                    str(exc),
                )
        except HumanRequiredError as exc:
            with self.db() as db:
                if str(exc) in {"POLICY_BLOCKED", "POLICY_REJECTED", "APPROVAL_EXPIRED"}:
                    db.execute(
                        "DELETE FROM payment_claims WHERE task_id=? AND state='RESERVED'",
                        (task_id,),
                    )
                else:
                    db.execute(
                        "UPDATE payment_claims SET state='UNCERTAIN' "
                        "WHERE task_id=? AND state='RESERVED'",
                        (task_id,),
                    )
            self.hold(task_id, str(exc))
        except Exception:
            with self.db() as db:
                db.execute(
                    "UPDATE payment_claims SET state='UNCERTAIN' "
                    "WHERE task_id=? AND state='RESERVED'",
                    (task_id,),
                )
            if step["state"] == "UNCERTAIN":
                self.hold(task_id, "RECONCILIATION_UNAVAILABLE")
            else:
                with self.db() as db:
                    db.execute(
                        "UPDATE steps SET state='UNCERTAIN',lease=NULL "
                        "WHERE task_id=? AND position=?",
                        (task_id, step["position"]),
                    )
                    self.event(db, task_id, "STEP_UNCERTAIN", step["tool"])

    def reserve_payment(self, task):
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
            balance = db.execute("SELECT balance FROM ledger WHERE id=1").fetchone()[0]
            if balance < task["amount"]:
                raise HumanRequiredError("INSUFFICIENT_FUNDS")
            used = db.execute("SELECT coalesce(sum(amount),0) FROM payment_claims").fetchone()[0]
            mandate = json.loads(task["mandate"])
            if used + task["amount"] > mandate["payment_cap"]:
                raise HumanRequiredError("SESSION_BUDGET_EXCEEDED")
            db.execute(
                "INSERT INTO payment_claims VALUES(?,?,'RESERVED')", (task["id"], task["amount"])
            )

    async def fund(self, task, key, adapter, reconcile):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            balance = db.execute("SELECT balance FROM ledger WHERE id=1").fetchone()[0]
            if balance >= task["amount"]:
                return {"tool": "fund", "mode": "SIMULATED", "funded_wei": 0, "skipped": True}
            claim = db.execute(
                "SELECT * FROM funding_claims WHERE task_id=?", (task["id"],)
            ).fetchone()
            if not claim:
                rules = db.execute("SELECT * FROM workflow_rules WHERE id=1").fetchone()
                claims = db.execute("SELECT * FROM funding_claims").fetchall()
                spent = sum(c["amount"] for c in claims)
                allocation = task["funding_cap"] - spent
                if allocation < task["amount"] - balance:
                    raise HumanRequiredError("FUNDING_BUDGET_EXCEEDED")
                if len(claims) >= rules["max_funding_requests"] or any(
                    time.time() - c["created"] < rules["cooldown"] for c in claims
                ):
                    raise HumanRequiredError("FAUCET_COOLDOWN")
                db.execute(
                    "INSERT INTO funding_claims VALUES(?,?,?,'RESERVED')",
                    (task["id"], time.time(), allocation),
                )
                amount = allocation
            else:
                amount = claim["amount"]
        self.allowed(task)
        result = await adapter.run(task, "fund", key, reconcile=reconcile)
        result["funded_wei"] = amount
        return result
