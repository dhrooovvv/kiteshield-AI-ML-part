# Prompt-injection evaluation v2

This directory contains synthetic evaluation data, separate from production
detection logic. `evaluation_dataset_v2.jsonl` contains 1,212 unique records;
the existing v1 dataset is unchanged.

Each record contains `id`, `text`, `label`, `category`, `language`,
`difficulty`, `rationale`, and `scenario_group`. Labels are `BENIGN`,
`SUSPICIOUS`, or `MALICIOUS`. Binary metrics treat `BENIGN` as negative and
the other two labels as positive.

The generator uses fixed seed `20261014`. It creates ten scenario families per
category and assigns whole families to either development or held-out test
split. The resulting files are `evaluation_dev_v2.jsonl` (909 records) and
`evaluation_test_v2.jsonl` (303 records). Categories are represented in both
splits and no scenario family crosses the split boundary.

The evaluated configurations are frozen:

- Rules: the existing `InjectionScreen` implementation, unchanged.
- Horizon: `Horizon-Labs/prompt-injection-guard-base`, with configuration
  labels `SAFE=0` and `INJECTION=1`. Its config has no explicit threshold; the
  benchmark uses `argmax(logits)`.
- Combined: flag when either rules or Horizon predicts positive.

Commands, from `backend`:

```bash
.venv/bin/python scripts/generate_evaluation_v2.py --output-dir app/ai_ml
.venv/bin/python scripts/benchmark_evaluation_v2.py --rules-only
.venv/bin/python scripts/benchmark_evaluation_v2.py
.venv/bin/python scripts/benchmark_evaluation_v2.py --json
```

The Horizon run requires the already configured local Transformers, PyTorch,
Accelerate, and Hugging Face Hub packages plus locally cached model weights.
The rules-only run does not require ML dependencies or internet access.

The dataset is synthetic and therefore subject to template, language,
distribution, and label-judgment bias. Its results are a reproducible baseline,
not a claim about production traffic or universal detector quality. No v2
result changes production authorization, policy, capability-token, or signer
behavior.
