# Advanced Detection Evaluation v2

This is an offline experiment. It does not authorize transactions or modify production request handling.

Dev records: 909; test records: 303.
Bastion threshold: `0.059`; Horizon selected threshold: `0.9352320432662964`.

## Held-out comparison

| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR | Mean ms | Median ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| horizon_only | 132 | 96 | 72 | 3 | 0.5789 | 0.9778 | 0.7273 | 0.5714 | 0.0222 | 22.184 | 21.054 | 26.885 |
| bastion_only | 95 | 13 | 155 | 40 | 0.8796 | 0.7037 | 0.7819 | 0.0774 | 0.2963 | 4.577 | 4.197 | 6.383 |
| rules_only | 59 | 33 | 135 | 76 | 0.6413 | 0.4370 | 0.5198 | 0.1964 | 0.5630 | 0.026 | 0.026 | 0.030 |
| horizon_or_bastion | 132 | 96 | 72 | 3 | 0.5789 | 0.9778 | 0.7273 | 0.5714 | 0.0222 | 26.787 | 25.708 | 31.043 |
| horizon_and_bastion | 95 | 13 | 155 | 40 | 0.8796 | 0.7037 | 0.7819 | 0.0774 | 0.2963 | 26.787 | 25.708 | 31.043 |
| horizon_first_risk_based | 132 | 96 | 72 | 3 | 0.5789 | 0.9778 | 0.7273 | 0.5714 | 0.0222 | 26.787 | 25.708 | 31.043 |
| disagreement_review | 132 | 96 | 72 | 3 | 0.5789 | 0.9778 | 0.7273 | 0.5714 | 0.0222 | 26.787 | 25.708 | 31.043 |
| three_layer_or | 132 | 105 | 63 | 3 | 0.5570 | 0.9778 | 0.7097 | 0.6250 | 0.0222 | 26.787 | 25.708 | 31.043 |
| horizon_threshold_bastion | 121 | 24 | 144 | 14 | 0.8345 | 0.8963 | 0.8643 | 0.1429 | 0.1037 | 26.787 | 25.708 | 31.043 |

## Development threshold candidates

Selection constraints: maximum FPR 0.10 and minimum recall 0.50. Highest recall under FPR is the selected operating point.

| Selection | Threshold | Recall | FPR | F1 |
|---|---:|---:|---:|---:|
| Highest recall under FPR | 0.935232 | 0.7526 | 0.0995 | 0.8168 |
| Lowest FPR above recall | 0.992999 | 0.5010 | 0.0023 | 0.6667 |
| Highest F1 secondary | 0.888140 | 0.8260 | 0.1458 | 0.8437 |

## Disagreement findings

Test attack-only disagreements: `{'horizon_only': 37, 'bastion_only': 0}`.
Test all-example disagreements: `{'horizon_only': 120, 'bastion_only': 0}`.

Horizon attacks are preserved by the Horizon-first policy. A Bastion-safe result never overrides a Horizon attack.

## Confirmed false-positive categories

- Horizon `difficult_benign`: 12 false positives out of 30.
- Horizon `educational_security`: 15 false positives out of 24.
- Horizon `legitimate_code_review`: 6 false positives out of 24.
- Horizon `legitimate_email`: 15 false positives out of 18.
- Horizon `legitimate_invoice`: 6 false positives out of 12.
- Horizon `legitimate_transaction`: 8 false positives out of 12.
- Horizon `legitimate_webpage`: 6 false positives out of 12.
- Horizon `multilingual_benign`: 6 false positives out of 12.
- Horizon `quoted_attack_example`: 18 false positives out of 18.
- Horizon `security_discussion`: 4 false positives out of 6.

## Limitations

- Datasets are synthetic and repeated-template performance does not establish real-world generalization.
- The held-out test split has already been used in prior experiments; it is not a pristine blind set.
- Continuous scores are model-specific and were not averaged across models.
- REVIEW is an experimental outcome only; no production review workflow was added.
