# Review: KiteShield Wallet Technical Whitepaper (2).pdf

Reviewed October 18, 2026. All 12 pages were extracted and visually reviewed. Claims were compared with the current checkout at commit `1ec251005abad80c5b0ce0812fbbce2fb4cb4d05`, plus existing local implementation/evidence reports. No PDF edits, application changes, role-credential use, signing, broadcasting or pushes were performed.

## Verdict

**Improved, but still not ready to submit as an accurate specification of this checkout.** The corrected typehash, baseline/extension distinction, advisory labels and host-compromise caveat address substantive earlier problems. The severe page-7/page-9 clipping is resolved. Remaining errors include incorrect financial approval semantics, nonexistent routes, unsupported Unicode defenses and an invented audit-chain formula.

The Phase-2 vault and research circuit still require a separate actual repository and evidence. This review did not independently establish the claimed Phase-2 contract deployment/receipts. “Unverified here” does not mean nonexistent elsewhere.

## Required technical fixes

### 1. Approval threshold is wrong throughout the baseline description

**Pages 3, 4, 7, 10; critical.** The document claims amounts above 0.0001 ETH become ESCALATED and require reviewer approval. That confuses the automation cap with the financial escalation threshold.

With the stated active policy v6, subject to recipient, budget and all other checks:

| Amount | Policy result | Automation behavior |
|---|---|---|
| Positive and <= 0.0001 ETH | ALLOW | Can auto-execute only when automation is enabled and eligibility checks pass |
| > 0.0001 and < 0.5 ETH | ALLOW | Outside auto-cap; manual execution, not mandatory financial approval |
| >= 0.5 and <= 1 ETH | ESCALATE | Requires a valid human approval; no unattended fast path |
| > 1 ETH | BLOCK | Approval cannot override the block |

At exactly 0.5 ETH, escalation applies. At exactly 1 ETH, the per-payment maximum is not exceeded, though other checks and approval still apply. Fix the table, diagrams, C-09, T-04 and numbered lifecycle consistently.

Sources: `backend/app/services/policy_engine.py`, `backend/app/services/autonomous.py`, `backend/app/core/config.py`.

### 2. Several advertised API endpoints do not exist

**Pages 2, 3, 4, 7.** `/api/v1/proposals/{id}/approve` is not the approval endpoint; `/proposals/{agent,approve,execute}` is not the actual API set.

Relevant implemented routes:

```text
POST /api/v1/proposals/agent
POST /api/v1/proposals/{proposal_id}/evaluate
POST /api/v1/approvals/{approval_id}/decide
POST /api/v1/proposals/{proposal_id}/sign
```

Approval uses an **approval-request ID**, not a proposal ID. Show the current request schema or link to generated OpenAPI for the decision payload. Receipt reconciliation has its own transaction routes; do not assume it is always completed within the initial proposal response.

Sources: `backend/app/api/routes/{proposals,approvals,transactions}.py`.

### 3. Unicode/confusable defenses are not in the current rule screen

**Pages 7, 9, 10, 11; high.** C-02, Mode 1 and T-02 claim NFKC normalization and Cyrillic/Greek confusable mapping. The inspected `injection_screen.py` normalizes CR/LF line endings and horizontal whitespace, then applies regex rules. I found neither NFKC nor the claimed character map in that live screen.

**Correction:** remove those defenses from the implemented baseline. Say: “Normalizes line endings and horizontal whitespace before applying curated regex rules; Unicode-confusable normalization is not claimed.” Do not add new security functionality merely to match the document during submission preparation.

Source: `backend/app/ai_ml/injection_screen.py`.

### 4. Printed audit hash algorithm is not the implemented algorithm

**Page 6, section 3.4; high.** The PDF claims a genesis hash derived from the Phase-2 contract address and hashes timestamp/event/proposal/payload fields. Actual code uses the literal `GENESIS` sentinel when there is no previous hash, then UTF-8 SHA-256 over:

```text
previous_hash_or_GENESIS|event_type|correlation_id|actor|details_json|created_at
```

**Correction:** reproduce the exact implementation and canonical JSON encoding, or label any alternate formula as a proposed extension. Independent validators cannot reproduce the current chain from the PDF formula. Checkpoints are database-persisted; no external-root publication service or automatic periodic scheduler was established. Replace “supports external root anchoring” with “external anchoring would be needed for off-host integrity assurance” unless an actual integration is supplied.

Sources: `backend/app/services/audit.py`, `audit_checkpoint.py`, `audit_integrity.py`.

### 5. Phase-2 status remains internally ambiguous

**Pages 1–5, 8, 10–12; high.** Some sections call it a specification; others assert deployed on-chain enforcement, 16 tests and approval-bound scenario evidence. “Phase-2 Contract Repo” is not a repository URL, and no release commit or source artifact is identified. The diagram also draws JWT and EIP-712 as alternatives inside the current capability service, which does not demonstrate that integration.

**Correction:** either:

- Supply the actual contract repository, commit, contract source/ABI, deployment transaction and source-verification evidence, test commands/logs and backend integration status; or
- Label the entire Phase-2 path **proposed / not integrated / not independently verified**, and remove production-style enforcement assertions.

Likewise, the Circom file is still described as an existing research artifact, but no corresponding circuit was found in this checkout. “Research” is not evidence that an artifact exists. Provide its actual location or call it a design proposal.

### 6. Evidence matrix omits the implemented baseline’s real payment evidence

**Page 2; high.** Section 1.3 contains the three Phase-2 hashes rather than the five baseline EOA payment confirmations recorded in this project. The scenario-demo policy column helps explain different thresholds, but it does not establish which implementation produced those receipts.

**Correction:** split evidence into baseline and extension tables. Include baseline receipt/export evidence and explain its chain, sender, recipient, amount and approval scope. For Phase-2 scenario B, publish the actual referenced approval record and its binding to action, signature, transaction and policy version. Include decoded execution events to show an intended payment actually happened; top-level status 1 alone does not establish the claimed business result. Status 0 does not identify a specific revert reason. `debug_traceTransaction` availability depends on provider/client retention; it is not guaranteed by any ordinary RPC endpoint.

Baseline example: `docs/evidence/sepolia-payment1-02437c8d60cfc3ec.json` and `docs/PAYMENT1_CONFIRMATION_2026-10-18.md`.

### 7. “Cross-language reference test vector” is incomplete

**Page 5; high.** The corrected typehash matches the exact printed string. The empty-calldata hash is also correct. But the table supplies no concrete domain separator, struct hash, final digest, 65-byte signature or actual recovered-address result, and shows no Solidity test output. It is a partial input example, not a demonstrated cross-language vector.

**Correction:** include all intermediate hashes and an independently verifiable signature generated from a documented **public test fixture**, not a production/authority secret. Link Python and Solidity tests asserting the same output. Nonce-increment/rotation invalidation also needs actual callable functions and access controls; the displayed execute function does not demonstrate those administrative mechanisms.

### 8. Learned runtime threshold is confused with offline benchmark threshold

**Page 9.** The optional runtime diagram fixes Horizon at 0.9352320432662964. In the current code, the default classification method is `argmax`; threshold mode is optional and its configured default threshold is 0.5. The 0.935232... threshold belongs to the offline report.

**Correction:** put the frozen threshold only in the benchmark section. In the runtime diagram, say “classification method and threshold selected by configuration.” Models are lazily loaded when required, not necessarily at startup. Replace “all-negative → ALLOW” with “BENIGN → continue validation”; screening cannot grant financial ALLOW. REVIEW halts proposal creation and records a security review; it is not the existing financial approval workflow. Retain the accurate disclosure that the benchmark evaluates a different OR strategy.

Sources: `backend/app/core/config.py`, `backend/app/ai_ml/ensemble_screen.py`, `experimental_decision_policy.py`, `backend/app/api/routes/proposals.py`.

### 9. The verification guide is neither fully read-only nor zero-signing

**Pages 11–12; high.** Backend tests sign with public test fixtures; the right claim is **no funded-key signing or live broadcast**, not zero signing. Server startup can initialize/migrate the configured database. A blocked prompt POST persists a screening audit event, so it writes local state. Setting only `LEARNED_SCREENING_ENABLED=false` does not force simulation or disable automation; an existing `.env` can leave the server live.

The rendered code blocks collapse commands and `#` comments into dense paragraphs. Copied comments may swallow commands; backslashes need real line breaks. Uvicorn runs in the foreground, so the following curl requires a second terminal. Dependency installation, venv, secret setup and database/profile isolation are missing.

**Correction:** separate pure read-only RPC/hash checks from stateful local simulation tests. Use an isolated simulation profile with a public test signer, separate DB, automation off and OpenAI off; preserve any existing live backend rather than restarting/replacing it. Present executable multiline code blocks with actual newline characters. Never expose real API keys in published command output. Shell variables such as `$SEPOLIA_RPC_URL` must be supplied explicitly; Python dotenv loading does not export them into the shell.

### 10. Receipt/bytecode inspection step does not inspect bytecode

**Page 12, section 7.3.** The only command shown is `eth_getTransactionReceipt`. There is no `eth_chainId`, `eth_getCode`, expected code comparison, receipt validation or behavior when the receipt is null. A contract address or successful JSON response alone is insufficient verification.

**Correction:** include read-only checks for network identity, deployment code, receipt fields and decoded events. Explain expected values and block provenance. Do not claim a deployed-bytecode/source match from mere nonempty code.

### 11. Runtime versus policy provenance is still conflated

**Pages 1, 3, 7, 12.** `AUTO_EXECUTE_MAX_ETH` is application configuration, not a field of policy v6. Amount thresholds and recipients come from the active database policy, not `core/config.py`. Policy version 6 is a local database snapshot, not a universal version installed by every checkout.

**Correction:** document the policy export, timestamp, source commit and separate config flags. Explain that fresh setup needs an initial policy; do not imply code checkout guarantees the same version or limits.

### 12. Budget/headroom semantics are incomplete or unsupported

**Pages 3, 7, 8.** The daily-budget formula uses “reserved + amount,” omitting committed spending. Current accounting is committed principal for the current UTC day **plus all outstanding reservations**, even from previous days; execution revalidation handles the current proposal carefully to avoid double counting. Gas is excluded and separately bounded. In C-04, the auto-cap is incorrectly attributed to the financial policy engine.

C-14 claims escalated/rejected policy responses report daily and per-tx headroom. I found no corresponding headroom/recommended-value response implementation in the searched policy/proposal code. Portfolio budget display is a separate feature.

**Correction:** specify exact accounting, boundaries and release conditions; remove C-14 or link the actual response schema and enforcement path.

## Additional completeness and wording fixes

- Include a real repository URL, branch/tag and full commit on page 1. “KiteShield-main” is a directory/snapshot label, not enough provenance.
- C-01 should reference `backend/app/core/security.py` for auth, with config.py only as credential configuration.
- Use actual policy reason codes and states instead of invented `MAX_SPEND_EXCEEDED` / `DAILY_BUDGET_EXCEEDED` and generic `REJECTED` mappings. Current policy reasons include `AMOUNT_EXCEEDS_LIMIT` and `DAILY_LIMIT_EXCEEDED`; persisted policy outcomes are BLOCK/ALLOW/ESCALATE.
- Describe the full JWT bindings: issuer/audience, chain/action, action/envelope digest, policy version, approval reference, expiry and single-use database consumption. Recipient/amount matching alone understates the implemented controls.
- Explain durable signed-byte persistence, identical-transaction retries, uncertain reservations, one-receipt confirmation versus finality, no reorg monitor, and no automatic fee-bumping/restart worker. These are more material to this baseline than speculative ZK content.
- Include live startup fail-closed validation, real HTTPS RPC requirement and chain/block checks. Explain simulation/live labels and default versus active automation flag.
- C-13 understates emergency stop as pausing autonomous execution; the shared signing/capability path checks it as well. Specify its separate credential and actual reach.
- Range comparators do not themselves prove all inputs are properly 64-bit constrained. Page 6's first sentence suggests LessEqThan enforces bounds, then correctly says explicit bit checks are needed. State that bounds are required constraints, not an automatic guarantee. Call the polynomial an algebraic expression rather than a proven binding commitment.
- “Novel paraphrases require learned screening and human review” is too strong: neither guarantees detection. State residual limitations.
- Add dataset/model revisions, dataset split/tuning provenance, inference hardware and whether loading/tokenization are included in timing. Current benchmark accuracy does not apply to the live tri-state or rules-only policy.
- The table's test prose cannot establish constant-time behavior empirically by ordinary unit tests; tests exercise authentication behavior, while constant-time comparison is an implementation property of the selected primitive.
- Status 1 indicates successful top-level execution plus inclusion when the matching receipt is validated. Inclusion by itself does not prove finality or all internal calls succeeded as intended.

## Visual review

The earlier severe clipping is fixed across the rendered 12 pages. Current concerns are usability rather than major overflow:

- Page 2's scorecard and page 4's Solidity function are flattened into dense blocks; preserve logical lines and indentation.
- Page 12's terminal blocks need real newlines and separate commands/comments, not visual wrapping.
- Diagrams and table text remain small in places, especially pages 4 and 9; increase text size or use separate figures.
- Large unused lower-page areas could accommodate larger figures and tables.
- Long identifiers break across words, making source paths and labels harder to copy/read.

## Revision order

1. Correct auto-cap versus escalation semantics everywhere.
2. Fix routes, Unicode claims, audit formula and response/state descriptions from code.
3. Establish Phase-2/circuit provenance or move them to clearly proposed future work.
4. Add baseline live evidence and complete any retained cryptographic vectors.
5. Rewrite the isolated verification guide and format real code lines.
6. Re-render and check all pages, then freeze the exact release commit for submission.

Do not solve documentation mismatches by adding rushed security features. Make the submission accurate for the implementation being judged.
