"""Evaluate the committed smoke set against ONLY the demo on 8001.

The harness acts as the separate human approver for synthetic approval scenarios.
It never reads a wallet key, .env, or non-demo credentials.
"""

import argparse
import asyncio
import hashlib
import json
import math
import time
import uuid
from pathlib import Path

import httpx


def wilson(successes, total):
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [center - radius, center + radius]


async def evaluate(profile):
    if not profile.name.startswith("kiteshield-gate1-demo-"):
        raise ValueError("Dedicated demo profile required")
    credentials = json.loads((profile / "demo-credentials.json").read_text())
    dataset = Path(__file__).with_name("evaluation") / "cases.json"
    cases = json.loads(dataset.read_text())
    rows = []
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8001", timeout=10, trust_env=False
    ) as client:

        async def call(method, path, role="agent", data=None):
            return await client.request(
                method, path, json=data, headers={"Authorization": "Bearer " + credentials[role]}
            )

        async def start(case):
            response = await call(
                "POST",
                "/goals",
                data={"goal": case["goal"], "request_key": "evaluation_" + str(uuid.uuid4())},
            )
            if response.status_code != 200:
                return None, response.json().get("detail")
            return response.json()["task_id"], None

        async def wait(task_id, wanted):
            for _ in range(120):
                task = (await call("GET", "/goals/" + task_id)).json()
                if task["state"] in wanted or task["state"] == "HUMAN_REQUIRED":
                    return task
                await asyncio.sleep(0.5)
            return {"state": "TIMEOUT", "reason": "EVALUATION_TIMEOUT"}

        health = (await client.get("/health")).json()
        if health.get("mode") != "SIMULATED" or not health.get("workflows_enabled"):
            raise RuntimeError("Enabled isolated workflow demo required")
        setup = await call(
            "PUT",
            "/mandate",
            "admin",
            {
                "supplier": "Acme",
                "recipient": "0x" + "1" * 40,
                "payment_cap": 1000,
                "funding_cap": 1000,
                "approval_threshold": 50,
            },
        )
        setup.raise_for_status()
        completed_independent = False
        for case in cases:
            if case["id"] == "independent" and completed_independent:
                continue
            snapshot = (await call("GET", "/snapshot")).json()
            if snapshot["control"]["quarantined"]:
                (await call("POST", "/quarantine/resume", "admin", {})).raise_for_status()
            started = time.monotonic()
            task_id, reason = await start(case)
            if task_id:
                task = await wait(task_id, {case["expected"], "COMPLETED", "REJECTED"})
                actual = task["state"]
                if actual == "WAITING_APPROVAL":
                    if case["id"] == "approve":
                        independent = next(c for c in cases if c["id"] == "independent")
                        independent_id, error = await start(independent)
                        other = await wait(independent_id, {"COMPLETED"}) if independent_id else {}
                        rows.append(
                            {
                                "id": "independent",
                                "passed": other.get("state") == "COMPLETED",
                                "actual": other.get("state", error),
                                "while_other_waited": True,
                            }
                        )
                        completed_independent = True
                    decision = "REJECT" if case["id"] == "reject" else "APPROVE"
                    result = await call(
                        "POST", f"/approvals/{task_id}/decision", "approver", {"decision": decision}
                    )
                    result.raise_for_status()
                    terminal = await wait(
                        task_id, {"REJECTED" if decision == "REJECT" else "COMPLETED"}
                    )
                    passed = terminal["state"] == (
                        "REJECTED" if decision == "REJECT" else "COMPLETED"
                    )
                else:
                    passed = actual == case["expected"]
                reason = task.get("reason")
            else:
                actual = reason
                passed = actual == case["expected"]
            rows.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "actual": actual,
                    "reason": reason,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            )
    successes = sum(row["passed"] for row in rows)
    report = {
        "mode": "SIMULATED",
        "model": "kiteshield-gemma4:12b-q4km",
        "model_digest": "13478e018db994bfea035644c1774abc573381ee0ff7e11ad59f3fbc89fd1519",
        "ollama_version": "0.40.8",
        "dataset_commit": "67e3de9",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "successful": successes,
        "total": len(rows),
        "wilson95": wilson(successes, len(rows)),
        "scope": "Selected synthetic workflow scenarios; not general model accuracy. "
        "Human decisions are separate test-harness actions, not autonomous approvals.",
        "cases": rows,
    }
    (profile / "workflow-evaluation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    asyncio.run(evaluate(parser.parse_args().profile.resolve()))
