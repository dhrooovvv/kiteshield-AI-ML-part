# Final v3 Dataset Audit

Records: `48`; SHA-256: `f418c5a28f19a77b791a0362a4e7be8d684cc6f35072f4376d71cad0f026b055`.
Labels: `{'BENIGN': 24, 'MALICIOUS': 22, 'SUSPICIOUS': 2}`.
Independence supported by this audit: `True`.

## Independence method

Normalized exact comparison plus SequenceMatcher and token-Jaccard screening against available v1/v2 records.

## Category distribution

| Category | BENIGN | MALICIOUS | SUSPICIOUS | Total |
|---|---:|---:|---:|---:|
| chained_attack | 0 | 2 | 0 | 2 |
| difficult_benign | 2 | 0 | 0 | 2 |
| direct_override | 0 | 2 | 0 | 2 |
| educational_security | 2 | 0 | 0 | 2 |
| indirect_document | 1 | 2 | 0 | 3 |
| indirect_email | 0 | 1 | 0 | 1 |
| indirect_webpage | 0 | 1 | 0 | 1 |
| legitimate_code_review | 2 | 0 | 0 | 2 |
| legitimate_email | 2 | 0 | 0 | 2 |
| legitimate_invoice | 2 | 0 | 0 | 2 |
| legitimate_transaction | 4 | 0 | 0 | 4 |
| legitimate_webpage | 2 | 0 | 0 | 2 |
| multilingual_benign | 3 | 0 | 0 | 3 |
| multilingual_injection | 0 | 3 | 0 | 3 |
| policy_bypass | 0 | 2 | 0 | 2 |
| quoted_attack_example | 2 | 1 | 0 | 3 |
| recipient_substitution | 0 | 0 | 2 | 2 |
| secret_exfiltration | 0 | 2 | 0 | 2 |
| security_discussion | 2 | 0 | 0 | 2 |
| spelling_obfuscation | 0 | 1 | 0 | 1 |
| tool_manipulation | 0 | 2 | 0 | 2 |
| unauthorized_transaction | 0 | 1 | 0 | 1 |
| unicode_obfuscation | 0 | 1 | 0 | 1 |
| urgency_authority | 0 | 1 | 0 | 1 |

Exact matches: `0`.
Near matches: `0`.
Schema errors: `0`.
