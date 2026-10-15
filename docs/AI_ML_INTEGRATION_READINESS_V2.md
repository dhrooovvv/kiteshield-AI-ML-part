# KiteShield AI/ML Integration Readiness v2

This document describes the isolated evaluation work for the prompt-injection
detectors. It is not a production authorization design and does not change
the policy engine, signer, capability tokens, routes, or datasets.

## Verified architecture

- `backend/app/ai_ml/injection_screen.py` is the existing deterministic rules
  detector. It returns a validated `InjectionScreenResult` and fails closed for
  invalid, empty, or oversized input.
- Horizon is loaded by `backend/scripts/benchmark_horizon_guard.py` and exposes
  a local softmax probability for the `INJECTION` class.
- Bastion is loaded through its installed local package by the existing
  benchmark. Its risk score is compared with the development-selected
  threshold `0.059`.
- The existing policy engine and signer remain authoritative. No model output
  can authorize a transaction.

## New isolated evaluation components

- `backend/app/ai_ml/experimental_decision_policy.py` normalizes detector
  outputs and evaluates named experimental strategies. Invalid or unavailable
  outputs produce an error/fail-closed outcome, never benign.
- `backend/scripts/audit_evaluation_dataset_v2.py` mechanically audits the
  development and held-out JSONL splits.
- `backend/scripts/benchmark_advanced_detection_v2.py` evaluates rules,
  Horizon, Bastion, and the experimental strategies. It tunes a Horizon
  threshold on development data only and evaluates the held-out split once the
  threshold is selected.
- `backend/scripts/write_detector_error_reports_v2.py` derives detector error
  reports from the benchmark output without rerunning or tuning models.

## Reproducibility

From `backend/`:

```text
.venv/bin/python scripts/audit_evaluation_dataset_v2.py
HF_HUB_OFFLINE=1 .venv/bin/python scripts/benchmark_advanced_detection_v2.py
.venv/bin/python scripts/write_detector_error_reports_v2.py
```

The benchmark records model initialization time, per-example latency, failed
and skipped counts, threshold candidates, confusion counts, and category,
language, and difficulty breakdowns in
`backend/reports/advanced_detection_evaluation_v2.json`.

## Measured held-out outcome

The development-selected Horizon threshold was `0.935232`. On the existing
303-example held-out split:

| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Horizon default | 132 | 96 | 72 | 3 | 0.5789 | 0.9778 | 0.7273 | 0.5714 | 0.0222 |
| Bastion tuned | 95 | 13 | 155 | 40 | 0.8796 | 0.7037 | 0.7819 | 0.0774 | 0.2963 |
| Horizon threshold OR Bastion | 121 | 24 | 144 | 14 | 0.8345 | 0.8963 | 0.8643 | 0.1429 | 0.1037 |

The thresholded Horizon/Bastion strategy is the best measured compromise in
this experiment, but its FPR and FNR are not production acceptance criteria.
The dataset is synthetic and the held-out split has already been used in prior
experiments, so it is not a blind production validation set.

## Integration contract for a future production adapter

Any future adapter should accept untrusted text and return a bounded,
versioned observation only:

```text
detector_name, predicted_attack, confidence_or_score,
model_version, latency_ms, availability, error_code
```

The adapter must not receive private keys, signing material, or secrets. It
must not call the signer or policy engine. Production code should retain the
existing deterministic policy checks and signer-side verification regardless
of detector output. Timeouts, malformed responses, model exceptions, and
disagreements should route to a conservative review/deny path defined by the
wallet team rather than silently allowing an action.

## Merge boundaries for the four-person team

- AI/ML work should remain under `backend/app/ai_ml/` and isolated benchmark
  scripts/reports under `backend/scripts/` and `backend/reports/`.
- Wallet, policy, signer, and API teammates should consume only a reviewed
  observation interface; they should not import benchmark scripts.
- Before production integration, agree on the timeout budget, error code
  taxonomy, review/deny behavior, model-version provenance, logging redaction,
  and rollback switch.

