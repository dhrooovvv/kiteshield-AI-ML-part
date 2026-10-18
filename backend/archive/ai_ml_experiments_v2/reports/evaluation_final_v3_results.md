# Final v3 Prompt-Injection Evaluation

This is a single-run offline benchmark. It does not authorize transactions or modify production request handling.

Dataset: `evaluation_final_v3.jsonl`; records: `48`; SHA-256: `f418c5a28f19a77b791a0362a4e7be8d684cc6f35072f4376d71cad0f026b055`.
Frozen thresholds: Horizon `0.9352320432662964`; Bastion `0.059`.

## Comparison

| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR | Mean ms | Median ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| horizon_only | 23 | 6 | 18 | 1 | 0.7931 | 0.9583 | 0.8679 | 0.2500 | 0.0417 | 41.379 | 23.671 | 53.075 |
| bastion_only | 19 | 7 | 17 | 5 | 0.7308 | 0.7917 | 0.7600 | 0.2917 | 0.2083 | 7.433 | 7.074 | 11.147 |
| rules_only | 3 | 1 | 23 | 21 | 0.7500 | 0.1250 | 0.2143 | 0.0417 | 0.8750 | 0.039 | 0.030 | 0.093 |
| horizon_or_bastion | 24 | 8 | 16 | 0 | 0.7500 | 1.0000 | 0.8571 | 0.3333 | 0.0000 | 48.851 | 30.712 | 62.720 |
| horizon_and_bastion | 18 | 5 | 19 | 6 | 0.7826 | 0.7500 | 0.7660 | 0.2083 | 0.2500 | 48.851 | 30.712 | 62.720 |
| horizon_first_risk_based | 23 | 6 | 18 | 1 | 0.7931 | 0.9583 | 0.8679 | 0.2500 | 0.0417 | 48.851 | 30.712 | 62.720 |
| disagreement_review | 24 | 8 | 16 | 0 | 0.7500 | 1.0000 | 0.8571 | 0.3333 | 0.0000 | 48.851 | 30.712 | 62.720 |
| three_layer_or | 24 | 8 | 16 | 0 | 0.7500 | 1.0000 | 0.8571 | 0.3333 | 0.0000 | 48.851 | 30.712 | 62.720 |
| horizon_threshold_bastion | 22 | 7 | 17 | 2 | 0.7586 | 0.9167 | 0.8302 | 0.2917 | 0.0833 | 48.851 | 30.712 | 62.720 |

Model-loading time and per-example mean/median/P95 latency are included in the JSON result for each strategy.
The selected experimental strategy is `horizon_threshold_bastion`; model disagreement is not treated as proof of safety.

## Limitations

This synthetic dataset measures synthetic performance only and does not establish real-world generalization.
The dataset is intentionally independent from the audited v1/v2 text corpus, but its coverage remains limited.
