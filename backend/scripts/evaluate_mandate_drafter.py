"""Frozen offline corpus evaluation; never load .env, DB, RPC or signer."""

import argparse
import asyncio
import hashlib
import json
import math
import random
import statistics
import time
from pathlib import Path

import httpx

from app.services.mandate_drafter import DraftContext, interpret, local_endpoint


def interval(k, n):
    if not n:
        return None
    z = 1.959963984540054
    mid = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(mid - radius, 4), round(mid + radius, 4)]


def latency_interval(times):
    rng = random.Random(42)  # noqa: S311 -- reproducible statistical bootstrap, not security
    means = sorted(statistics.mean(rng.choices(times, k=len(times))) for _ in range(1000))
    return [round(means[24], 3), round(means[974], 3)]


def metric(k, n):
    return {
        "correct": k,
        "n": n,
        "rate": round(k / n, 4) if n else None,
        "wilson_95_ci": interval(k, n),
    }


async def evaluate(args):
    corpus = Path(args.corpus)
    rows = [json.loads(s) for s in corpus.read_text().splitlines()]
    ctx = DraftContext(
        {"treasury": "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"},
        ("0x229D5588641f2614e3F486c853D8BA0eC5FFe811",),
        "0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7",
        10**14,
        5 * 10**17,
    )
    report = {
        "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "cases": len(rows),
        "confidence": (
            "Wilson 95% for binary rates; small curated corpus, not population security proof"
        ),
        "strategies": {},
    }
    for enabled in [False, True]:
        label = "llm_assisted" if enabled else "parser_only"
        if enabled:
            try:
                if not local_endpoint(args.endpoint):
                    raise ValueError("Not a loopback endpoint")
                async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                    response = await client.get(args.endpoint.rsplit("/", 1)[0] + "/models")
                    response.raise_for_status()
                    if not response.json().get("data"):
                        raise ValueError("No local models listed")
            except Exception:
                report["strategies"][label] = {
                    "status": "not_run",
                    "reason": (
                        "No available local OpenAI-compatible model server; no "
                        "model quality/latency claim."
                    ),
                }
                continue
        results = []
        for row in rows:
            start = time.perf_counter()
            result = await interpret(
                row["instruction"], ctx, enabled=enabled, endpoint=args.endpoint, model=args.model
            )
            duration = (time.perf_counter() - start) * 1000
            expected = row["expected_fields"]
            exact = (
                bool(expected)
                and result.status == "draft"
                and all(getattr(result.draft, key) == value for key, value in expected.items())
            )
            results.append(
                {
                    **row,
                    "actual_status": result.status,
                    "source": result.source,
                    "exact": exact,
                    "latency_ms": duration,
                }
            )
        categories = {}
        for category in sorted({r["category"] for r in rows}):
            items = [r for r in results if r["category"] == category]
            field_cases = [r for r in items if r["expected_fields"]]
            clarification = [r for r in items if r["expected_status"] == "clarification"]
            refusal = [r for r in items if r["expected_status"] == "refused"]
            times = sorted(r["latency_ms"] for r in items)
            categories[category] = {
                "n": len(items),
                "exact_field_accuracy": metric(
                    sum(r["exact"] for r in field_cases), len(field_cases)
                ),
                "correct_clarification_rate": metric(
                    sum(r["actual_status"] == "clarification" for r in clarification),
                    len(clarification),
                ),
                "correct_refusal_rate": metric(
                    sum(r["actual_status"] == "refused" for r in refusal), len(refusal)
                ),
                "false_accept": metric(
                    sum(r["actual_status"] == "draft" for r in refusal), len(refusal)
                ),
                "latency_ms": {
                    "mean": round(statistics.mean(times), 3),
                    "mean_bootstrap_95_ci": latency_interval(times),
                    "median": round(statistics.median(times), 3),
                    "p95": round(times[math.ceil(0.95 * len(times)) - 1], 3),
                },
            }
        report["strategies"][label] = {"status": "run", "categories": categories, "cases": results}
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {"status": v["status"], "categories": v.get("categories")}
                for k, v in report["strategies"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="evaluation/mandate_drafting_v1.jsonl")
    parser.add_argument("--output", default="reports/mandate_drafting_v1.json")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/v1/chat/completions")
    parser.add_argument("--model", default="local")
    asyncio.run(evaluate(parser.parse_args()))
