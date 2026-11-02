"""Optional restriction-only on-chain pause after local self-quarantine."""

import asyncio
import json
import time
import uuid


class VaultSafety:
    def __init__(self, engine, call):
        self.engine, self.call = engine, call

    def initialize(self):
        with self.engine.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS vault_safety_actions "
                "(epoch INTEGER PRIMARY KEY, state TEXT NOT NULL, operation_id TEXT)"
            )

    async def tick(self):
        control = self.engine.control()
        if not control["quarantined"]:
            return
        epoch = control["epoch"]
        with self.engine.db() as db:
            prior = db.execute(
                "SELECT * FROM vault_safety_actions WHERE epoch=?", (epoch,)
            ).fetchone()
            if prior:
                return  # One bounded attempt per quarantine; no endless RPC retries.
            db.execute("INSERT INTO vault_safety_actions VALUES(?,'STARTED',NULL)", (epoch,))
            self.engine.event(db, "system", "VAULT_PAUSE_REQUESTED", str(epoch))
        try:
            status = await self.call("GET", "/vault/status")
            if not status.get("configured") or status["chain"]["paused"]:
                state, operation_id = "ALREADY_RESTRICTED", None
            else:
                op = await self.call(
                    "POST",
                    "/vault/pause",
                    data={
                        "kind": "PAUSE",
                        "request_key": f"self_quarantine_pause_{epoch}",
                        "amount_wei": 0,
                    },
                )
                operation_id = op["id"]
                op = await self.call("POST", f"/vault/operations/{operation_id}/execute")
                state = op["status"]
            with self.engine.db() as db:
                db.execute(
                    "UPDATE vault_safety_actions SET state=?,operation_id=? WHERE epoch=?",
                    (state, operation_id, epoch),
                )
                self.engine.event(
                    db,
                    "system",
                    "VAULT_QUARANTINE_PAUSE",
                    json.dumps(
                        {"state": state, "operation_id": operation_id, "quarantine_epoch": epoch}
                    ),
                )
        except Exception:
            with self.engine.db() as db:
                db.execute(
                    "UPDATE vault_safety_actions SET state='HUMAN_REQUIRED' WHERE epoch=?", (epoch,)
                )
                self.engine.event(
                    db,
                    "system",
                    "VAULT_PAUSE_REVIEW_REQUIRED",
                    "Local quarantine remains active. Reconcile any saved pause operation "
                    "as administrator.",
                )
                # Already quarantined: adding an issue must not advance the quarantine
                # epoch and accidentally cause a retry loop.
                if not db.execute(
                    "SELECT id FROM issues WHERE reason='VAULT_PAUSE_REVIEW_REQUIRED' "
                    "AND resolved=0"
                ).fetchone():
                    db.execute(
                        "INSERT INTO issues VALUES(?,NULL,?,?,0)",
                        (str(uuid.uuid4()), "VAULT_PAUSE_REVIEW_REQUIRED", time.time()),
                    )

    async def run(self):
        while True:
            await self.tick()
            await asyncio.sleep(2)
