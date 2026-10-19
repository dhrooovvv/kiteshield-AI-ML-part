# Mandate drafting evaluation

Frozen corpus SHA-256: `40b258bcfb9c328705fdaaced6c6136482283922d99921ddae88f83f48a80eb3`

LLM-assisted: **not run**; local model server unavailable. Mocked transport tests are not model-quality evidence.

| Category | Exact fields (95% CI) | Clarification (95% CI) | Refusal (95% CI) | False accepts (95% CI) | Mean ms (bootstrap 95% CI) |
|---|---|---|---|---|---|
| ambiguous | N/A | 10/10 (72.2–100.0%) | N/A | N/A | 0.027 ([0.017, 0.039]) |
| clean | 15/15 (79.6–100.0%) | N/A | N/A | N/A | 0.064 ([0.036, 0.134]) |
| formatting | 2/2 (34.2–100.0%) | N/A | 3/3 (43.9–100.0%) | 0/3 (0.0–56.1%) | 0.016 ([0.002, 0.03]) |
| malicious | N/A | N/A | 15/15 (79.6–100.0%) | 0/15 (0.0–20.4%) | 0.006 ([0.003, 0.01]) |
| paraphrases | 0/15 (0.0–20.4%) | N/A | N/A | N/A | 0.037 ([0.026, 0.066]) |
| unsupported | N/A | N/A | 10/10 (72.2–100.0%) | 0/10 (0.0–27.8%) | 0.003 ([0.001, 0.004]) |

Paraphrases deliberately require clarification with parser-only mode. This curated 70-case development set does not establish production security or held-out generalization. Exact-field accuracy measures all expected core fields on intended-draft cases; N/A reflects no eligible cases. Timing measures in-process interpretation; it excludes HTTP/UI/DB and real model inference.

See `docs/MANDATE_DRAFTING.md` for setup, boundaries and full test results.
