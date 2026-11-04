"""Bounded, read-only token/NFT log observer. Logs are data, never authority.

No token metadata, URLs, signing functions, approvals or alternate RPCs are used.
Starts at the current confirmed head, rather than replaying wallet history.
"""

import asyncio
import json
import re

from web3 import Web3

HASH = re.compile(r"0x[0-9a-fA-F]{64}")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")


def topic(signature):
    return "0x" + Web3.keccak(text=signature).hex().removeprefix("0x")


TRANSFER = topic("Transfer(address,address,uint256)")
APPROVAL = topic("Approval(address,address,uint256)")
APPROVAL_ALL = topic("ApprovalForAll(address,address,bool)")
TRANSFER_SINGLE = topic("TransferSingle(address,address,address,uint256,uint256)")
TRANSFER_BATCH = topic("TransferBatch(address,address,address,uint256[],uint256[])")


class IncomingWatcher:
    def __init__(self, engine, rpc, address, confirmations=6):
        self.engine, self.rpc = engine, rpc
        self.wallet_topic = "0x" + address.lower().removeprefix("0x").rjust(64, "0")
        self.confirmations = confirmations

    def initialize(self):
        with self.engine.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS incoming_cursor (
                    id INTEGER PRIMARY KEY CHECK(id=1), block INTEGER,
                    failures INTEGER NOT NULL DEFAULT 0, suspended_epoch INTEGER);
                INSERT OR IGNORE INTO incoming_cursor(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS incoming_events (
                    key TEXT PRIMARY KEY, detail TEXT NOT NULL);
            """)

    def status(self):
        with self.engine.db() as db:
            return dict(db.execute("SELECT * FROM incoming_cursor WHERE id=1").fetchone())

    def parse(self, log, start, end):
        topics = log["topics"]
        if (
            not isinstance(topics, list)
            or not 3 <= len(topics) <= 4
            or any(not isinstance(item, str) or not HASH.fullmatch(item) for item in topics)
            or not ADDRESS.fullmatch(log["address"])
            or not HASH.fullmatch(log["transactionHash"])
            or not HASH.fullmatch(log["blockHash"])
            or log.get("removed", False) is not False
        ):
            raise ValueError("Malformed log")
        first = topics[0].lower()
        if first in {TRANSFER, APPROVAL, APPROVAL_ALL}:
            index = 2
        elif first in {TRANSFER_SINGLE, TRANSFER_BATCH}:
            index = 3
        else:
            raise ValueError("Unexpected event")
        number, offset = int(log["blockNumber"], 16), int(log["logIndex"], 16)
        if (
            len(topics) <= index
            or topics[index].lower() != self.wallet_topic
            or not start <= number <= end
            or offset < 0
        ):
            raise ValueError("Wallet or range mismatch")
        permission = first in {APPROVAL, APPROVAL_ALL}
        detail = {
            "kind": "permission_like" if permission else "token_or_nft_transfer",
            "contract": log["address"].lower(),
            "tx_hash": log["transactionHash"].lower(),
            "block": number,
            "log_index": offset,
            "untrusted": True,
            "authority_changed": False,
        }
        key = f"{log['blockHash'].lower()}:{detail['tx_hash']}:{offset}"
        return key, detail, permission

    async def tick(self):
        state = self.status()
        control = self.engine.control()
        if state["suspended_epoch"] is not None:
            if control["quarantined"] or state["suspended_epoch"] == control["epoch"]:
                return
            with self.engine.db() as db:
                db.execute("UPDATE incoming_cursor SET failures=0,suspended_epoch=NULL WHERE id=1")
        if await self.rpc("eth_chainId", []) != "0xaa36a7":
            raise ValueError("Wrong chain")
        head = int(await self.rpc("eth_blockNumber", []), 16)
        end = max(0, head - self.confirmations)
        if state["block"] is None:
            with self.engine.db() as db:
                db.execute("UPDATE incoming_cursor SET block=?,failures=0 WHERE id=1", (end,))
                self.engine.event(
                    db,
                    "system",
                    "INCOMING_WATCH_STARTED",
                    f"Confirmed block {end}; historical logs not replayed; data only",
                )
            return
        if state["block"] > end:
            raise ValueError("Confirmed head moved backwards")
        start = state["block"] + 1
        if start > end:
            with self.engine.db() as db:
                db.execute("UPDATE incoming_cursor SET failures=0 WHERE id=1")
            return
        end = min(end, start + 23)
        common = {"fromBlock": hex(start), "toBlock": hex(end)}
        logs = []
        for topics in (
            [[TRANSFER, APPROVAL, APPROVAL_ALL], None, self.wallet_topic],
            [[TRANSFER_SINGLE, TRANSFER_BATCH], None, None, self.wallet_topic],
        ):
            batch = await self.rpc("eth_getLogs", [dict(common, topics=topics)])
            if not isinstance(batch, list) or len(logs) + len(batch) > 200:
                raise ValueError("Incoming event limit")
            logs.extend(batch)
        parsed = [self.parse(log, start, end) for log in logs]
        permission_seen = False
        with self.engine.db() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, detail, permission in parsed:
                inserted = db.execute(
                    "INSERT OR IGNORE INTO incoming_events VALUES(?,?)", (key, json.dumps(detail))
                ).rowcount
                if inserted:
                    self.engine.event(db, "system", "INCOMING_DATA_ONLY", json.dumps(detail))
                    permission_seen = permission_seen or permission
            db.execute("UPDATE incoming_cursor SET block=?,failures=0 WHERE id=1", (end,))
        if permission_seen:
            self.engine.issue(None, "UNTRUSTED_ONCHAIN_PERMISSION_EVENT", anomaly=True)

    def failure(self):
        with self.engine.db() as db:
            db.execute("UPDATE incoming_cursor SET failures=failures+1 WHERE id=1")
            count = db.execute("SELECT failures FROM incoming_cursor WHERE id=1").fetchone()[0]
        if count >= 3:
            self.engine.issue(None, "INCOMING_WATCH_UNAVAILABLE_OR_INVALID", anomaly=True)
            with self.engine.db() as db:
                db.execute(
                    "UPDATE incoming_cursor SET suspended_epoch=? WHERE id=1",
                    (self.engine.control()["epoch"],),
                )

    async def run(self, interval):
        while True:
            try:
                await self.tick()
            except Exception:
                self.failure()
            await asyncio.sleep(interval)
