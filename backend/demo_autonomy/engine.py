"""Durable demo workflow. Plans are suggestions; administrator mandates are authority."""

import asyncio
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

TOOLS = ["balance", "fund", "payment", "receipt"]
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "string", "enum": TOOLS},
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    steps: list[Literal["balance", "fund", "payment", "receipt"]]


@dataclass(frozen=True)
class Settings:
    directory: Path
    enabled: bool = False
    planner_enabled: bool = False
    model: str = "gemma3:4b"
    timeout: float = 20
    lease_seconds: float = 30
    model_digest: str = ""
    ollama_version: str = ""
    workflows_enabled: bool = False
    quarantine_enabled: bool = False
    wallet_services_enabled: bool = False
    mode: Literal["SIMULATED", "SEPOLIA"] = "SIMULATED"
    wallet_source: Literal["isolated-demo", "separate-sepolia", "existing-main"] = "isolated-demo"


class HumanRequiredError(Exception):
    pass


async def gemma_plan(settings: Settings):
    if not settings.planner_enabled:
        raise HumanRequiredError("PLANNER_DISABLED")
    if not re.fullmatch(r"[0-9a-f]{64}", settings.model_digest) or not settings.ollama_version:
        raise HumanRequiredError("PLANNER_VERSION_PIN_REQUIRED")
    # No prompt, addresses, keys, documents, or tool bindings go to the model.
    async with httpx.AsyncClient(timeout=settings.timeout, trust_env=False) as client:
        version = await client.get("http://127.0.0.1:11434/api/version")
        version.raise_for_status()
        tags = await client.get("http://127.0.0.1:11434/api/tags")
        tags.raise_for_status()
        if version.json().get("version") != settings.ollama_version or not any(
            m.get("name") == settings.model and m.get("digest") == settings.model_digest
            for m in tags.json().get("models", [])
        ):
            raise HumanRequiredError("PLANNER_VERSION_MISMATCH")
        response = await client.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": settings.model,
                "stream": False,
                "format": PLAN_SCHEMA,
                "think": False,
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 128},
                "messages": [
                    {
                        "role": "user",
                        "content": "Plan: check balance, fund only if needed, pay the saved "
                        "supplier, verify receipt. Return JSON steps using the given schema.",
                    }
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("done") or payload["message"].get("tool_calls"):
            raise HumanRequiredError("PLANNER_INCOMPLETE_OR_TOOL_CALL")
        return json.loads(payload["message"]["content"])


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.directory / "goals.sqlite3"

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def initialize(self):
        self.settings.directory.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS task_backend (
                    task_id TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mandates (
                    id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
                    supplier TEXT NOT NULL, recipient TEXT NOT NULL,
                    payment_cap INTEGER NOT NULL, funding_cap INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    goal TEXT NOT NULL, mandate TEXT NOT NULL, amount INTEGER NOT NULL,
                    payment_cap INTEGER NOT NULL, funding_cap INTEGER NOT NULL,
                    state TEXT NOT NULL, reason TEXT, plan TEXT);
                CREATE TABLE IF NOT EXISTS steps (
                    task_id TEXT NOT NULL REFERENCES tasks(id), position INTEGER NOT NULL,
                    tool TEXT NOT NULL, state TEXT NOT NULL, owner TEXT, lease REAL,
                    result TEXT, PRIMARY KEY(task_id,position));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS effects (
                    key TEXT PRIMARY KEY, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY CHECK(id=1), balance INTEGER NOT NULL);
                INSERT OR IGNORE INTO ledger VALUES (1,0);
            """)

    @staticmethod
    def event(db, task_id, kind, detail):
        db.execute(
            "INSERT INTO events(task_id,kind,detail) VALUES (?,?,?)", (task_id, kind, detail)
        )

    def configure(self, supplier, recipient, payment_cap, funding_cap):
        # Called exclusively by the administrator endpoint. No model-selected recipient.
        if not re.fullmatch(r"[A-Za-z][A-Za-z -]{0,39}", supplier):
            raise ValueError("INVALID_SUPPLIER")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", recipient):
            raise ValueError("INVALID_RECIPIENT")
        if (
            type(payment_cap) is not int
            or not 0 < payment_cap <= 10**15
            or type(funding_cap) is not int
            or not (0 if self.settings.mode == "SEPOLIA" else 1)
            <= funding_cap
            <= (10**18 if self.settings.mode == "SEPOLIA" else 10**15)
        ):
            raise ValueError("INVALID_BUDGET")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO mandates VALUES(1,1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET version=version+1,supplier=excluded.supplier,
                recipient=excluded.recipient,payment_cap=excluded.payment_cap,
                funding_cap=excluded.funding_cap""",
                (supplier, recipient.lower(), payment_cap, funding_cap),
            )

    def create(self, goal, request_key):
        self.require_enabled()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_key):
            raise ValueError("INVALID_REQUEST_KEY")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM tasks WHERE request_key=?", (request_key,)).fetchone()
            if prior:
                if prior["goal"] != goal:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return prior["id"]
            mandate = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
            if not mandate:
                raise HumanRequiredError("ADMIN_MANDATE_REQUIRED")
            # Exact public grammar. Voice/documents/events are not alternate authority channels.
            pattern = (
                r"fund if needed, pay supplier "
                + re.escape(mandate["supplier"])
                + r" ([0-9]+) wei, verify"
            )
            match = re.fullmatch(pattern, goal, re.I)
            if not match:
                raise HumanRequiredError("EXPLICIT_GOAL_REQUIRED")
            amount = int(match[1])
            if not 0 < amount <= mandate["payment_cap"]:
                raise HumanRequiredError("PAYMENT_BUDGET_EXCEEDED")
            task_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    request_key,
                    goal,
                    json.dumps(dict(mandate)),
                    amount,
                    mandate["payment_cap"],
                    mandate["funding_cap"],
                    "PLANNING",
                    None,
                    None,
                ),
            )
            db.execute(
                "INSERT INTO task_backend VALUES(?,?)",
                (task_id, json.dumps(self.context_for_new_task())),
            )
            self.event(
                db, task_id, "GOAL_ACCEPTED", self.settings.mode + "; administrator mandate bound"
            )
            return task_id

    def context_for_new_task(self):
        return {"backend": "NATIVE"}

    def task_context(self, task_id):
        with self.db() as db:
            row = db.execute(
                "SELECT value FROM task_backend WHERE task_id=?", (task_id,)
            ).fetchone()
        # Historical tasks predate the vault feature and remain native forever.
        return json.loads(row[0]) if row else {"backend": "NATIVE"}

    def require_enabled(self):
        if not self.settings.enabled:
            raise HumanRequiredError("AUTONOMY_DISABLED")

    def hold(self, task_id, reason):
        with self.db() as db:
            db.execute(
                "UPDATE tasks SET state='HUMAN_REQUIRED',reason=? WHERE id=?", (reason, task_id)
            )
            self.event(db, task_id, "HUMAN_REQUIRED", reason)

    async def plan(self, task_id, planner=gemma_plan):
        self.require_enabled()
        task = self.get(task_id)
        if task["state"] != "PLANNING":
            return
        try:
            raw = await asyncio.wait_for(planner(self.settings), self.settings.timeout)
            parsed = Plan.model_validate(raw)
            if parsed.steps != TOOLS:
                raise ValueError("INVALID_PLAN")
        except Exception:
            self.hold(task_id, "PLANNER_INVALID_OR_UNAVAILABLE")
            return
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
            if current["state"] != "PLANNING":
                return
            db.executemany(
                "INSERT INTO steps VALUES(?,?,?,'READY',NULL,NULL,NULL)",
                [(task_id, n, tool) for n, tool in enumerate(parsed.steps)],
            )
            db.execute(
                "UPDATE tasks SET state='READY',plan=? WHERE id=?",
                (json.dumps(parsed.model_dump()), task_id),
            )
            self.event(db, task_id, "PLAN_VALIDATED", "Fixed tools, order and mandate verified")

    def tighten(self, task_id, payment_cap, funding_cap):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            if any(type(x) is not int or x < 0 for x in (payment_cap, funding_cap)):
                raise ValueError("INVALID_BUDGET")
            if payment_cap > row["payment_cap"] or funding_cap > row["funding_cap"]:
                raise ValueError("CANNOT_LOOSEN_AUTHORITY")
            db.execute(
                "UPDATE tasks SET payment_cap=?,funding_cap=? WHERE id=?",
                (payment_cap, funding_cap, task_id),
            )
            self.event(db, task_id, "LIMITS_TIGHTENED", json.dumps([payment_cap, funding_cap]))

    def get(self, task_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            result = dict(row)
            context = db.execute(
                "SELECT value FROM task_backend WHERE task_id=?", (task_id,)
            ).fetchone()
            result["payment_backend"] = json.loads(context[0])["backend"] if context else "NATIVE"
            result["steps"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM steps WHERE task_id=? ORDER BY position", (task_id,)
                )
            ]
            result["events"] = [
                dict(r)
                for r in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))
            ]
            return result

    async def tick(self, task_id, adapter):
        self.require_enabled()
        owner = str(uuid.uuid4())
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["state"] != "READY":
                return
            mandate = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
            if not mandate or json.loads(task["mandate"]) != dict(mandate):
                db.execute(
                    "UPDATE tasks SET state='HUMAN_REQUIRED',reason='MANDATE_CHANGED' WHERE id=?",
                    (task_id,),
                )
                self.event(db, task_id, "HUMAN_REQUIRED", "MANDATE_CHANGED")
                return
            if task["amount"] > task["payment_cap"]:
                db.execute(
                    "UPDATE tasks SET state='HUMAN_REQUIRED',reason='TASK_BUDGET' WHERE id=?",
                    (task_id,),
                )
                self.event(db, task_id, "HUMAN_REQUIRED", "TASK_BUDGET")
                return
            step = db.execute(
                "SELECT * FROM steps WHERE task_id=? AND state!='COMPLETED' "
                "ORDER BY position LIMIT 1",
                (task_id,),
            ).fetchone()
            if not step:
                db.execute("UPDATE tasks SET state='COMPLETED' WHERE id=?", (task_id,))
                self.event(db, task_id, "TASK_COMPLETED", "SIMULATED")
                return
            if step["state"] == "RUNNING" and step["lease"] > time.time():
                return
            reconcile = step["state"] in ("RUNNING", "UNCERTAIN")
            db.execute(
                "UPDATE steps SET state='RUNNING',owner=?,lease=? WHERE task_id=? AND position=?",
                (owner, time.time() + self.settings.lease_seconds, task_id, step["position"]),
            )
            self.event(
                db, task_id, "STEP_RECONCILING" if reconcile else "STEP_STARTED", step["tool"]
            )
        key = f"{task_id}:{step['position']}"
        try:
            result = await adapter.run(dict(task), step["tool"], key, reconcile=reconcile)
            if result is None:
                raise HumanRequiredError("UNRESOLVED_OUTCOME")
        except HumanRequiredError as exc:
            self.hold(task_id, str(exc))
            return
        except Exception:
            if reconcile:
                self.hold(task_id, "RECONCILIATION_UNAVAILABLE")
                return
            with self.db() as db:
                db.execute(
                    "UPDATE steps SET state='UNCERTAIN' WHERE task_id=? AND position=? AND owner=?",
                    (task_id, step["position"], owner),
                )
                self.event(db, task_id, "STEP_UNCERTAIN", step["tool"])
            return
        with self.db() as db:
            changed = db.execute(
                "UPDATE steps SET state='COMPLETED',result=? "
                "WHERE task_id=? AND position=? AND owner=?",
                (json.dumps(result), task_id, step["position"], owner),
            ).rowcount
            if changed:
                self.event(db, task_id, "STEP_COMPLETED", json.dumps(result))


class SimulatedAdapter:
    """Atomic local ledger; NO signer, RPC, real faucet, network or wallet dependency."""

    def __init__(self, engine):
        self.engine = engine

    async def run(self, task, tool, key, *, reconcile=False):
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT result FROM effects WHERE key=?", (key,)).fetchone()
            if prior:
                return json.loads(prior[0])
            if reconcile:
                # An unknown external result must never turn into a new payment.
                return None
            current = db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
            mandate = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
            if not mandate or dict(mandate) != json.loads(current["mandate"]):
                raise HumanRequiredError("MANDATE_CHANGED")
            if current["amount"] > current["payment_cap"]:
                raise HumanRequiredError("TASK_BUDGET")
            balance = db.execute("SELECT balance FROM ledger WHERE id=1").fetchone()[0]
            used = [json.loads(r[0]) for r in db.execute("SELECT result FROM effects")]
            used = [r for r in used if r.get("mandate_version") == mandate["version"]]
            result = {"tool": tool, "mode": "SIMULATED", "mandate_version": mandate["version"]}
            if tool == "balance":
                result["balance_wei"] = balance
            elif tool == "fund":
                needed = max(0, current["amount"] - balance)
                funded = sum(r.get("funded_wei", 0) for r in used)
                if needed > current["funding_cap"] or funded + needed > mandate["funding_cap"]:
                    raise HumanRequiredError("FUNDING_BUDGET_EXCEEDED")
                db.execute("UPDATE ledger SET balance=balance+? WHERE id=1", (needed,))
                result["funded_wei"] = needed
            elif tool == "payment":
                spent = sum(r.get("paid_wei", 0) for r in used)
                if spent + current["amount"] > mandate["payment_cap"]:
                    raise HumanRequiredError("SESSION_BUDGET_EXCEEDED")
                if balance < current["amount"]:
                    raise HumanRequiredError("INSUFFICIENT_FUNDS")
                db.execute("UPDATE ledger SET balance=balance-? WHERE id=1", (current["amount"],))
                result.update(
                    {
                        "paid_wei": current["amount"],
                        "recipient": mandate["recipient"],
                        "receipt_id": "simulation:" + key,
                    }
                )
            elif tool == "receipt":
                paid = db.execute(
                    "SELECT result FROM effects WHERE key=?", (task["id"] + ":2",)
                ).fetchone()
                if not paid:
                    raise HumanRequiredError("PAYMENT_NOT_VERIFIED")
                result["receipt_id"] = json.loads(paid[0])["receipt_id"]
                result["verified"] = True
            else:
                raise HumanRequiredError("UNKNOWN_TOOL")
            db.execute("INSERT INTO effects VALUES(?,?)", (key, json.dumps(result)))
            return result
