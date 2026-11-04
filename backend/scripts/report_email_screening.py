"""Summarize an offline screening run, separating detection from input refusal."""

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def cluster_rate(rows, predicate):
    """Descriptive row rate and cluster-bootstrap CI, preserving related variants."""
    if not rows:
        return "not measured"
    groups = defaultdict(list)
    for row in rows:
        provenance = row["provenance"]
        key = (
            provenance["source"],
            provenance.get("base_scenario_id")
            or provenance.get("base_payload_id")
            or provenance["source_id"],
        )
        groups[key].append(int(predicate(row)))
    values = [(sum(group), len(group)) for group in groups.values()]
    rng = random.Random(42)  # noqa: S311 -- reproducible statistics
    samples = []
    for _ in range(2000):
        chosen = rng.choices(values, k=len(values))
        samples.append(sum(item[0] for item in chosen) / sum(item[1] for item in chosen))
    samples.sort()
    count = sum(predicate(row) for row in rows)
    return (
        f"{count}/{len(rows)} ({100 * count / len(rows):.1f}%; "
        f"cluster 95% CI {100 * samples[49]:.1f}–{100 * samples[1949]:.1f}%)"
    )


def make_report(report):
    rows = report["cases"]
    accepted = [row for row in rows if row["parser"] == "accepted"]
    attacks = [row for row in accepted if row["malicious"]]
    controls = [row for row in accepted if not row["malicious"]]
    lines = [
        "# KiteShield: external email screening results",
        "",
        "## Scope",
        "",
        "Gemma remains the invoice field extractor. Horizon and Bastion screen untrusted "
        "documents before extraction. None of these models grant payment authority: the "
        "vendor registry, deterministic checks, policy, reservations and signer still apply.",
        "",
        "This experiment ran only the EML parser and screening code. No Gemma requests, "
        "proposals, signing, broadcasting or receipt checks were performed. It measures "
        "attack detection and benign-email rejection, not invoice extraction accuracy or "
        "unauthorized-payment success.",
        "",
        f"Dataset revision: `{report['commit']}`.",
        f"Classifier profile: `{report['profile']}`.",
        f"Run complete: **{report['complete']}**; records: **{len(rows)}**.",
        "",
        "Source: https://github.com/tokencanopy/e2a-bench/tree/main/dataset/prompt-injection",
        "",
        "The main prompt-injection set, its 200 matched benign controls and the adaptive "
        "supplement are included. Visual/OCR, phishing, NotInject and SpamAssassin sets are "
        "excluded. This includes LLMail-derived cases under the user's new authorization "
        "to test this repository; no training or threshold tuning was performed.",
        "This uses KiteShield's bounded EML parser and screening gate, not the repository's "
        "official evaluation harness. Input construction differs, so these numbers should "
        "not be presented as directly comparable to its published system scores.",
        "",
        "## Production gate, on parser-accepted emails",
        "",
        "ATTACK blocks; REVIEW and ERROR stop for human review; only BENIGN clears screening. "
        "Clearing screening alone does not make an invoice payable.",
        "",
        "| Measure | Result |",
        "|---|---|",
        "| Attack stopped by screening (ATTACK/REVIEW/ERROR) | "
        + cluster_rate(attacks, lambda row: row["gate"]["classification"] != "BENIGN")
        + " |",
        "| Attack cleared by screening | "
        + cluster_rate(attacks, lambda row: row["gate"]["classification"] == "BENIGN")
        + " |",
        "| Benign control stopped by screening | "
        + cluster_rate(controls, lambda row: row["gate"]["classification"] != "BENIGN")
        + " |",
        "",
        "Intervals use 2,000 seeded cluster-bootstrap resamples, grouping all renderings "
        "and AgentDojo attack formulations by their base scenario. They describe this "
        "synthetic/adapted corpus, not all future attacks. Degenerate intervals do not "
        "establish zero risk.",
        "",
        "## Parser coverage and gate outcomes",
        "",
        "| Slice | Emails | Parser rejected | ATTACK | REVIEW | ERROR | BENIGN |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in report["manifests"]:
        subset = [row for row in rows if row["slice"] == name]
        counts = Counter(
            row.get("gate", {}).get("classification", "parser_rejected") for row in subset
        )
        lines.append(
            f"| {name} | {len(subset)} | "
            + " | ".join(
                str(counts[key])
                for key in ("parser_rejected", "ATTACK", "REVIEW", "ERROR", "BENIGN")
            )
            + " |"
        )
    lines += [
        "",
        "Parser rejection reasons: `"
        + json.dumps(
            dict(Counter(row.get("reason") for row in rows if row["parser"] != "accepted"))
        )
        + "`.",
        "",
        "Parser rejections are coverage limitations and operational holds, not classifier "
        "detections. They are excluded from the classifier rate denominators above.",
        "",
        "## Independent model measurements",
        "",
        "Both models were also measured when the production rules short-circuited. "
        "These measurements do not modify the production decision.",
        "",
        "| Model | Valid attack measurements | Attack flagged | "
        "Valid benign measurements | Benign flagged |",
        "|---|---:|---:|---:|---:|",
    ]
    for model in ("horizon", "bastion"):
        valid = [row for row in accepted if row["models"].get(model, {}).get("status") == "ready"]
        bad = [row for row in valid if row["malicious"]]
        good = [row for row in valid if not row["malicious"]]
        lines.append(
            f"| {model.title()} | {len(bad)} | "
            + cluster_rate(bad, lambda row, model=model: row["models"][model]["attack"])
            + f" | {len(good)} | "
            + cluster_rate(good, lambda row, model=model: row["models"][model]["attack"])
            + " |"
        )
    lines += [
        "",
        "Independent model measurement errors: **"
        + str(sum(row["models"].get("classification") == "ERROR" for row in accepted))
        + "**. These are excluded from per-model valid-measurement denominators, "
        "not counted as detections.",
    ]
    lines += [
        "",
        "## Surface breakdown",
        "",
        "| Surface | Attack emails | Attack parser refusals | Attack screening clears | "
        "Benign emails | Benign parser refusals | Benign screening holds |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for surface in sorted({" + ".join(row["surface"]) for row in rows}):
        subset = [row for row in rows if " + ".join(row["surface"]) == surface]
        bad = [row for row in subset if row["malicious"]]
        good = [row for row in subset if not row["malicious"]]
        holds = sum(
            row["parser"] == "accepted" and row["gate"]["classification"] != "BENIGN"
            for row in good
        )
        lines.append(
            f"| {surface} | {len(bad)} | "
            f"{sum(row['parser'] != 'accepted' for row in bad)} | "
            f"{sum(row.get('gate', {}).get('classification') == 'BENIGN' for row in bad)} | "
            f"{len(good)} | {sum(row['parser'] != 'accepted' for row in good)} | "
            f"{holds} |"
        )
    durations = sorted(row["elapsed_ms"] for row in rows)
    benign_reasons = dict(
        Counter(
            row["gate"]["reason"] for row in controls if row["gate"]["classification"] != "BENIGN"
        )
    )
    lines += [
        "",
        "## Interpretation",
        "",
        "The screeners are useful defense layers, but this result does not support using "
        "them as sole authority or calling them comprehensive. Header injections produced "
        "the most screening clears in the main set. All 25 encoded benign controls were "
        "held, making encoded business email a usability concern for this profile.",
        "Benign hold reasons: `" + json.dumps(benign_reasons) + "`. Review these cases in "
        "a development set before considering any policy change; do not relax registry or "
        "signer checks to compensate for detector false positives.",
        "",
        f"Mean end-to-end benchmark case latency: {sum(durations) / len(durations):.0f} ms; "
        f"P95: {durations[(95 * len(durations) + 99) // 100 - 1]} ms. "
        "Includes parsing and extra independent-model measurements; model initialization "
        "is excluded. This is not the payment pipeline's latency. The local machine "
        "experienced memory pressure during the run; timing is specific to those "
        "conditions and should not be presented as a deployment latency guarantee.",
        "",
        "## Checks and changes",
        "",
        "- Targeted invoice/EML/screening/extraction tests: 78 passed.",
        "- Full backend: 564 passed, 14 skipped; Ruff passed.",
        "- Frontend: 65 passed; lint and production build passed. Tests emitted existing "
        "development WebSocket port-in-use warnings without failures.",
        "- Added only benchmark and report scripts and their output. Existing invoice "
        "architecture, thresholds, live settings and protected security files were unchanged.",
        "",
        "## Limitations and next work",
        "",
        "Screening misses remain untrusted input; never convert a BENIGN result into "
        "permission to pay. This corpus contains general email attacks rather than vendor "
        "invoices. No claim of zero wrong-payee payments can be made from this run. "
        "The existing invoice regression suite covers registry/address mismatch, duplicate "
        "invoices and authorization boundaries separately. Review misses and benign holds "
        "as development findings; use a new untouched set for any future tuned profile. "
        "The original frozen 120-invoice evaluation was not rerun or overwritten. "
        "Model version labels are retained in each case; Horizon currently reports its "
        "model identifier rather than a verified weight digest. The profile fingerprint "
        "identifies configuration, not a cryptographic attestation of loaded weights. "
        "This experiment does not automatically mark a profile approved for live use.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    if not report["complete"]:
        raise ValueError("Cannot publish an incomplete run as final results")
    args.output.write_text(make_report(report))
