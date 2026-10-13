# KiteShield Wallet — Security Invariants & Threat Model

## Security Invariants

These invariants MUST hold at all times. Each is enforced by code, database constraints, and tests.

| # | Invariant | Enforcement | Test |
|---|---|---|---|
| SI-1 | Model output is untrusted | Pydantic validation on all agent input | `test_normalization.py` |
| SI-2 | Invalid/ambiguous proposals cannot be signed | State machine: only ALLOWED/APPROVED → AUTHORIZED | `test_policy_engine.py` |
| SI-3 | BLOCK never leads to signing | No state transition from BLOCKED to AUTHORIZED | `test_policy_engine.py` |
| SI-4 | ESCALATE requires valid approval | Capability service checks approval record | `test_approval.py` |
| SI-5 | Approval bound to exact action | action_digest in approval matches proposal | `test_parameter_tampering.py` |
| SI-6 | Tokens are single-use | DB consumption record + UNIQUE constraint | `test_replay.py` |
| SI-7 | Signer independently verifies | Signer re-verifies JWT + all claims | `test_signer.py` |
| SI-8 | Parameter changes invalidate auth | tx_digest in JWT must match actual params | `test_parameter_tampering.py` |
| SI-9 | Expired tokens rejected | exp claim checked with clock skew | `test_token_attacks.py` |
| SI-10 | Keys never sent to browser/LLM | Key only in signer module; not in responses | Code review + grep |
| SI-11 | No secrets in logs | Structured logger filters SENSITIVE_FIELDS | `test_logging.py` |
| SI-12 | Fail-closed on missing auth | Default deny; every check explicit | `test_signer.py` |

## Threat Scenarios

| # | Attack | Mitigation | Status |
|---|---|---|---|
| T-01 | Prompt injection overriding policy | Structured output; policy ignores free text | Planned |
| T-02 | Recipient substitution after token | tx_digest in JWT binds recipient | Planned |
| T-03 | Amount manipulation after token | tx_digest in JWT binds amount | Planned |
| T-04 | Chain ID substitution | chain_id claim in JWT; config restricts to Sepolia | Planned |
| T-05 | Token forgery | HS256 signature; secret not exposed | Planned |
| T-06 | Token replay | DB consumption record; jti uniqueness | Planned |
| T-07 | Expired token use | exp claim; 30s clock skew tolerance | Planned |
| T-08 | Approval spoofing | Separate auth; agent has no approval privilege | Planned |
| T-09 | Approval reuse for different tx | action_digest binding | Planned |
| T-10 | Duplicate signing | Atomic token consumption in DB transaction | Planned |
| T-11 | Key leakage in logs | SENSITIVE_FIELDS filter in logger | Planned |
| T-12 | Policy bypass via direct signer | Signer requires valid JWT | Planned |
| T-13 | Database tampering | Audit hash chain (informational) | Planned |
| T-14 | Stale policy version | policy_version in JWT claims | Planned |
| T-15 | Concurrent over-spending | Spending reservation with DB transaction | Planned |

## Trust Model Limitations

1. **SQLite audit log** is not cryptographically tamper-proof. An attacker with database access can modify both events and hash chain. The hash chain provides detection against accidental corruption, not against a motivated attacker.
2. **HS256 JWT** uses a symmetric key. If the key is compromised, tokens can be forged. This is acceptable for a single-service MVP where the key never leaves the server process.
3. **Module isolation** is logical, not process-level. All modules share the same process memory. A code vulnerability in one module could theoretically access the signing key. For production, the signer would need process or hardware isolation.
