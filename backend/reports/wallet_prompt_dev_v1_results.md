# Wallet prompt screening development evaluation

Dataset: `/Users/dhruv/Desktop/backend projects/ai wallet agent/backend/app/ai_ml/wallet_prompt_dev_v1.jsonl` (20 synthetic examples)
Bastion threshold: `0.059`; ensemble: `Rules OR Horizon OR Bastion`.

| Strategy | TP | FP | TN | FN | Precision | Recall | F1 | FPR | FNR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules_only | 8 | 0 | 10 | 2 | 1.000 | 0.800 | 0.889 | 0.000 | 0.200 |
| horizon_only | 9 | 1 | 9 | 1 | 0.900 | 0.900 | 0.900 | 0.100 | 0.100 |
| bastion_only | 7 | 5 | 5 | 3 | 0.583 | 0.700 | 0.636 | 0.500 | 0.300 |
| three_layer_or | 10 | 5 | 5 | 0 | 0.667 | 1.000 | 0.800 | 0.500 | 0.000 |

Results are synthetic development evidence and do not establish real-world security.
