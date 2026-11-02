"""Explicit administrator provisioning over the existing local API; never signs.

Prepare preserves the funded wallet and all existing settings. Execution uses
stable request keys, and a lost response is reconciled without a replacement.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from eth_account import Account

BACKEND = Path(__file__).resolve().parents[1]
PRIVATE = Path.home() / ".local/share/kiteshield/main-existing-20261102"
BASE = "http://127.0.0.1:8128/api/v1"
EVIDENCE = BACKEND / "demo_autonomy/reports/guarded-vault-sepolia-2026-11-02.json"


def update_env(changes):
    path = BACKEND / ".env"
    original = path.read_text()
    result = original
    for key, value in changes.items():
        line = key + "=" + json.dumps(str(value))
        pattern = r"^" + re.escape(key) + r"=.*$"
        result = (
            re.sub(pattern, lambda _, replacement=line: replacement, result, flags=re.M)
            if re.search(pattern, result, re.M)
            else result.rstrip() + "\n" + line + "\n"
        )
    if path.read_text() != original:
        raise RuntimeError("Configuration changed during preparation; retry without overwriting it")
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    with os.fdopen(fd, "w") as handle:
        handle.write(result)
    path.chmod(0o600)


def prepare():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = dotenv_values(BACKEND / ".env")
    if env.get("EXECUTION_MODE") != "sepolia":
        raise RuntimeError("Existing profile is not live Sepolia")
    backup = PRIVATE / "before-guarded-vault.env"
    if not backup.exists():
        backup.write_bytes((BACKEND / ".env").read_bytes())
        backup.chmod(0o600)
    database = BACKEND / env.get(
        "DATABASE_URL", "sqlite+aiosqlite:///./kiteshield.db"
    ).removeprefix("sqlite+aiosqlite:///")
    db_backup = PRIVATE / "before-guarded-vault.sqlite3"
    if not db_backup.exists():
        with sqlite3.connect(database) as source, sqlite3.connect(db_backup) as target:
            source.backup(target)
        db_backup.chmod(0o600)
    keyfile = PRIVATE / "vault-agent.key"
    if not keyfile.exists():
        with os.fdopen(
            os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
        ) as output:
            output.write(Account.create().key.hex())
    agent = Account.from_key(keyfile.read_text().strip()).address
    owner = Account.from_key(env["SIGNER_PRIVATE_KEY"]).address
    if agent == owner or keyfile.stat().st_mode & 0o077:
        raise RuntimeError("A separate private agent identity is required")
    if env.get("VAULT_AGENT_ADDRESS"):
        if env["VAULT_AGENT_ADDRESS"].lower() != agent.lower():
            raise RuntimeError("Prepared agent identity changed; administrator review required")
        current_pin = hashlib.sha256(
            (BACKEND / "app/contracts/guarded_vault.json").read_bytes()
        ).hexdigest()
        if env.get("VAULT_ARTIFACT_SHA256") != current_pin:
            raise RuntimeError("Prepared artifact changed; administrator migration required")
        print(json.dumps({"already_prepared": True, "owner": owner, "restricted_agent": agent}))
        return
    directory = Path(env["AUTONOMY_PROFILE_DIR"])
    with sqlite3.connect(directory / "goals.sqlite3") as journal:
        allocated = journal.execute(
            "SELECT coalesce(sum(amount),0) FROM payment_claims"
        ).fetchone()[0]
    unspent = int(env["AUTONOMY_PAYMENT_BUDGET_WEI"]) - allocated
    if not 0 < unspent <= 10**15:
        raise RuntimeError("No unallocated workflow budget remains")
    artifact = BACKEND / "app/contracts/guarded_vault.json"
    changes = dict(
        VAULT_ENABLED="true",
        AUTONOMY_VAULT_PAYMENTS_ENABLED="false",
        VAULT_QUARANTINE_PAUSE_ENABLED="true",
        VAULT_AGENT_KEY_FILE=str(keyfile),
        VAULT_AGENT_ADDRESS=agent,
        VAULT_ARTIFACT_SHA256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        VAULT_MAX_GAS_UNITS="1000000",
        VAULT_OWNER_MAX_GAS_UNITS="8000000",
        VAULT_FEE_BUDGET_WEI=env["AUTONOMY_SESSION_FEE_BUDGET_WEI"],
        VAULT_ESCROW_BUDGET_WEI=str(unspent),
        VAULT_AGENT_GAS_BUDGET_WEI="1000000000",
        VAULT_SESSION_TTL_SECONDS="3600",
    )
    update_env(changes)
    print(
        json.dumps(
            {
                "owner": owner,
                "restricted_agent": agent,
                "escrow_budget_wei": str(unspent),
                "payments_enabled": False,
            }
        )
    )


def call(client, method, path, body=None):
    response = client.request(method, BASE + path, json=body)
    if response.status_code >= 400:
        # Do not print credential-bearing URLs or raw exception details.
        try:
            message = response.json().get("error", {}).get("message", "Request rejected")
        except ValueError:
            message = "Local API unavailable"
        raise RuntimeError(f"{response.status_code}: {message}")
    return response.json()["data"]


def provision(kind):
    env = dotenv_values(BACKEND / ".env")
    with httpx.Client(
        timeout=45, follow_redirects=False, headers={"X-API-Key": env["POLICY_ADMIN_API_KEY"]}
    ) as client:
        amount = {
            "DEPOSIT": int(env["VAULT_ESCROW_BUDGET_WEI"]),
            "GAS_FUND": int(env["VAULT_AGENT_GAS_BUDGET_WEI"]),
        }.get(kind, 0)
        op = call(
            client,
            "POST",
            "/vault/owner-intents",
            {
                "request_key": "main_guarded_vault_" + kind.lower() + "_20261102",
                "kind": kind,
                "amount_wei": amount,
            },
        )
        # If the response was lost, the same key returns this operation and hash.
        if not op["tx_hash"]:
            op = call(client, "POST", f"/vault/operations/{op['id']}/execute")
        for _ in range(20):
            op = call(client, "POST", f"/vault/operations/{op['id']}/reconcile")
            if op["status"] in ("CONFIRMED", "REVERTED"):
                break
            time.sleep(2)
        report = (
            json.loads(EVIDENCE.read_text())
            if EVIDENCE.exists()
            else {"mode": "SEPOLIA", "operations": {}}
        )
        report["operations"][kind] = op
        report["status"] = call(client, "GET", "/vault/status")
        EVIDENCE.write_text(json.dumps(report, indent=2))
        print(
            json.dumps(
                {
                    "kind": kind,
                    "status": op["status"],
                    "tx_hash": op["tx_hash"],
                    "vault": report["status"].get("address"),
                }
            )
        )
        if op["status"] != "CONFIRMED":
            raise RuntimeError("Stop provisioning; reconcile this same operation before continuing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=["prepare", "DEPLOY", "CONFIGURE", "DEPOSIT", "GAS_FUND", "enable"]
    )
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    elif args.stage == "enable":
        env = dotenv_values(BACKEND / ".env")
        with httpx.Client(timeout=30, headers={"X-API-Key": env["POLICY_ADMIN_API_KEY"]}) as client:
            status = call(client, "GET", "/vault/status")
        chain = status.get("chain", {})
        if (
            not status.get("configured")
            or chain.get("paused")
            or int(chain.get("remaining", 0)) <= 0
            or int(chain.get("balance", 0)) <= 0
            or int(chain.get("agent_balance", 0)) <= 0
            or chain.get("expires", 0) <= time.time()
        ):
            raise RuntimeError("Vault is not ready for autonomous tasks")
        update_env({"AUTONOMY_VAULT_PAYMENTS_ENABLED": "true"})
        print("New vault tasks enabled in configuration; restart the owned backend to apply")
    else:
        provision(args.stage)


if __name__ == "__main__":
    main()
