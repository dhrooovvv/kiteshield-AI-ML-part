# Submission review: KiteShield Wallet Technical Doc..pdf

Reviewed October 18, 2026. Scope: all 10 PDF pages, rendered-page inspection, current repository implementation and existing evidence reports. Original PDF was not edited. No signing, broadcasting, credential use or application mutations were performed.

## Verdict

**Do not submit this version as the technical specification of the current checkout.** Its central execution architecture differs from this implementation, it contains a reproducibly incorrect cryptographic constant, and several sections are physically clipped. If it documents another team's newer implementation, reconcile it against that exact repository and release commit rather than treating these differences as automatically nonexistent everywhere.

The linked Sourcify metadata and sample Etherscan transaction could not be retrieved through the web tool. Therefore this review does **not** establish whether the claimed contract and three receipts exist on-chain. They remain unverified here, rather than disproved.

## Submission blockers

### 1. Different custody and execution architecture — pages 1–5, 9–10

The PDF claims a deployed KiteShieldWallet.sol vault, EIP-712 authority signer, funded gas relayer and hardware isolation. This checkout implements backend-issued HS256 JWT capabilities and an EOA signer sending native ETH payments. No Solidity, Circom or Hardhat project, relayer implementation or claimed contract integration was found in the searched project files, including the nested KiteShield-main snapshot. The similarly named calldata utility does not establish the larger architecture.

**Correction:** describe the modular-monolith/EOA architecture, or supply the actual contract/backend integration repository and identify which release the document describes. Do not mix evidence from two implementations under one architecture.

Source: `backend/app/services/{capability,signer,blockchain,execution}.py`; `backend/app/core/config.py`.

### 2. Incorrect EIP-712 typehash — page 5, section 3.2.1

For the exact printed string:

```text
ActionCapability(bytes32 proposalId,address target,uint256 value,bytes32 dataHash,uint256 nonce,uint256 deadline)
```

Ethereum Keccak-256 computed locally with eth_utils yields:

```text
0xb9dbe593b63c313ea8c4493f133d2cfbbb75310c327a1143ffe56e99df0f6f5c
```

The document instead prints:

```text
0x2967676e1a49a888c3a7f8582b13c38f192b42918841b9ffbbf49a0319dfaa4c
```

**Correction:** establish the actual deployed type string and constant, then publish a cross-language test vector: domain separator, complete typed message, struct hash, digest, signature and recovered signer. Changing only the PDF constant is insufficient if deployed/source implementations differ.

### 3. Claimed security engines are not substantiated by the current application — pages 2, 4, 6–7, 9

The document describes OAuth2 login, secure cookies, PBKDF2 password storage, exponential lockout, UUIDv7 mandate registry, idempotency response caching, threat intelligence, state-diff simulation, anti-structuring detection, hourly quotas, counterfactual solver, timelock, M-of-N approvals, allowance revocation and automatic intrusion shutdown. Many cited paths (`backend/auth.py`, `backend/app.py`, `backend/database.py`, `backend/services/...`) are not this application's layout. Current services are under `backend/app/services/`.

Current authentication is distinct runtime API keys in `X-API-Key`, with constant-time comparisons. It is not the described browser-cookie/OAuth2 flow. Current financial approvals do not establish a 2-of-N quorum or 30-minute timelock.

**Correction:** replace the 19-layer catalog with an implementation/status table. Each retained claim needs an actual path, reachable entry point, enforcement point and named test. Distinguish implemented utilities, integrated enforcement and future work.

### 4. AI execution placement and activation are wrong — pages 2–4, 8

The diagrams put screening in the frontend before POST /api/intent. Actual screening runs in the backend agent-proposal route. The current API uses `/api/v1/...`; the agent endpoint is `/api/v1/proposals/agent`. The inspected local configuration has learned screening disabled and no OpenAI key configured; extraction and screening therefore use deterministic/rule-based paths.

“Production ensemble active” and a mandatory two-model live path are unsupported for that configuration.

**Correction:** distinguish implemented optional model paths, benchmark configuration and active demonstration configuration. Record config flags without exposing keys.

### 5. Benchmark strategy is misidentified — page 8

The reported 942-row confusion matrices match the existing offline report. Its combined strategy is thresholded Horizon OR Bastion, with Horizon threshold **0.9352320432662964** and Bastion **0.059**. It is not evidence for the PDF's full rules OR Horizon OR Bastion production gate.

The optional learned live path currently blocks positive rules or two-model positives, routes model disagreement to REVIEW, and permits all-negative results to continue. The legacy strategy name `three_layer_or` does not accurately describe its present semantics.

**Correction:** label these as offline experimental results; include both frozen thresholds, model revisions, dataset revision, hardware, timing scope and tuning/split provenance. Do not transfer those metrics to another strategy or rules-only mode. Parameter count and fine-tuning claims need a model card/config citation; the ID alone is insufficient.

Source: `backend/reports/horizon_bastion_public_final.md`; `backend/app/ai_ml/{ensemble_screen,experimental_decision_policy}.py`.

### 6. On-chain scorecard does not prove its stated conclusions — pages 1–3, 10

A status-1 receipt proves a transaction succeeded, not that backend approval checks ran. A status-0 receipt proves a transaction reverted, not that expiry was the reason. Source verification demonstrates a source/bytecode relationship, not correctness of every invariant. Three scenarios cannot support “all cryptographic assertions” or universal invariant correctness.

The claimed authority/relayer addresses and scenario hashes differ from the EOA payment evidence in this repository. That difference needs explicit provenance, not an assumption they refer to the same release.

**Correction:** provide deployment transaction, exact repository commit, compiler/optimizer settings, ABI, source verification evidence, decoded calldata/events, receipt block/hash and reproducible revert-reason evidence at the relevant state. Bind scenario B to a persisted approval and scenario C to a demonstrated expiry check. Mark evidence unverified until independently checked.

### 7. Reproduction commands and tests do not match the checkout — pages 1–2, 9–10

`npm run judge-verify`, `npm run test:all`, the referenced Hardhat suite and `/api/security/self-test` are not provided by this project's inspected package/API definitions. The PDF names different test files. Its 170 backend category counts do add to 170; the issue is provenance and reproducibility, not arithmetic.

**Correction:** state repository URL, branch/tag and commit; runtime/dependency prerequisites; working directory for each command; environment template and startup instructions; exact test commands; date, pass/fail/skip totals and logs. Separate offline fake-RPC tests from actual live evidence. Do not publish “0 warnings” without a clean run supporting its defined scope. Avoid a verifier that signs, funds or broadcasts by default.

## Technical and security corrections

### 8. Zero balance is not hardware isolation — pages 1–5

Separate authority and relayer keys can separate responsibilities, but do not prove physical/hardware isolation. An authority address with zero ETH may still sign a capability authorizing vault spending if that is the vault's trust model. Anyone can transfer ETH to an address; zero balance is a snapshot, not generally an enforceable eternal invariant.

**Correction:** describe actual key location, process boundaries, access controls, signer API and compromise assumptions. Replace “cannot be drained” with a bounded statement about authority-account gas funds. Analyze compromise of the authority key, not only the relayer.

### 9. Solidity gate claims need precision — pages 3–4

`executedProposals` is described as a bitmask although the shown syntax suggests keyed state. “L1” and “L2” are ambiguous because they are used for replay checks rather than network layers. Page 3 says nonce increments before external interaction; page 4 step 20 places it after the external call. The ordering matters for CEI/reentrancy analysis.

**Correction:** show actual source ordering, replay-state update timing and revert behavior. Specify zero-address signer validation, signature canonicality/library version, relayer replay/front-running assumptions, signer rotation/revocation and capability invalidation. Explain that a revert rolls state back but still consumes gas.

### 10. Thresholds conflict and leave undefined behavior — pages 2, 4, 7

The PDF variously uses an autonomous cap of 0.001 ETH, a >0.005 ETH timelock, >0.05 ETH high-value escalation and a scenario B 0.005 ETH human approval. Scenario B's escalation is unexplained under the stated rules; the range above 0.001 through 0.05 ETH lacks a complete decision description unless a distinct risk rule applies.

The current local implementation instead has a 0.0001 ETH automation cap; active policy v6 uses 0.5 ETH escalation, 1 ETH per-payment max and 5 ETH UTC daily principal budget.

**Correction:** publish one authoritative table with exact inequalities, precedence, configuration provenance and examples at boundaries. Distinguish automation cap, approval threshold, absolute max, daily budget and timelock rules.

### 11. ZK statement does not establish the claimed compliance — page 5

The displayed circuit description has no demonstrated enforcement in this checkout. Even considered independently, amount <= daily_limit <= max_allowed_spend proves neither cumulative daily spending nor treasury solvency. There is no shown trusted balance input, spending-state binding, recipient non-membership proof or use of the denylist root. A private limit can be chosen by the prover unless bound to authenticated policy.

The quadratic expression `(31*a+s)*(17*d+s)+42` is not established as a secure cryptographic commitment. Merely naming a public denylist root does not enforce its use. Comparator use also requires explicit integer range constraints; 64-bit wei supports only about 18.4467 ETH and needs justification for the intended domain. Eighteen-decimal ETH arithmetic is not automatically safe in unconstrained field arithmetic.

**Correction:** remove the production claim or label it research. Supply circuit, public-signal order, trusted policy/state commitments, membership/non-membership construction, range constraints, proof artifacts, verifier integration and negative tests. Explain trusted setup assumptions if Groth16 is retained.

### 12. Privacy and security language is absolute — pages 5–6, 8, 10

Local inference is not an air gap. `local_files_only=True` controls model loading behavior, not all outbound networking. The application uses blockchain RPC and supports optional OpenAI extraction. A browser accepting API credentials is not literally secret-free. HttpOnly reduces direct cookie access but does not make a session impervious to XSS-driven actions.

“Zero-leak,” “mathematically unforgeable,” “complete physical isolation,” “all invariants sound,” “institutional benchmark” and “without ever putting ... assets at risk” exceed the demonstrated evidence. NFKC also does not alone map all Cyrillic/Greek confusables; custom mapping needs tests and coverage limits.

**Correction:** use conditional claims, state deployment scope and document residual risk. Say what has been tested rather than claiming universal safety. Avoid an unsupported generalization that a compromised ERC-4337 bundler necessarily controls wallet funds.

### 13. Audit signing and enforcement semantics are overstated — pages 5–7

The current implementation has hash-chain and Merkle checkpoint utilities stored in the same database, not demonstrated EIP-191 authority-signed roots anchored to a vault. A privileged attacker able to rewrite the database may recompute the chain unless a root is independently protected. Page 5 introduces section 3.4 without its promised explanatory body.

The current calldata decoder returns structured facts and does not itself authorize or clamp signed payments; no application integration call was found outside that utility. The gas-economics service is advisory, not a DEX swap/slippage enforcement pipeline; >50% produces a warning, whereas a fee greater than the transfer value makes its advice non-viable. Neither advice alone proves transaction denial. An emergency-stop feature is not proof of automatic “three attacks” shutdown.

**Correction:** specify the actual enforced call path and root custody; label unused utilities and advisory output accurately. Do not silently clamp a signed payload: any changed amount needs reauthorization.

## PDF presentation defects

- **Page 1:** bottom executive-summary paragraph runs into the footer/clipping region; recover the full sentence.
- **Page 2:** rightmost transaction status values are clipped. Long addresses/URLs wrap awkwardly; the tier description continues without a clean continuation.
- **Page 3:** contract-gate section is highly compressed; use readable code and precise execution order.
- **Page 4:** eight-participant sequence diagram is too small for convenient reading at normal scale; expand it and reconcile with the numbered sequence.
- **Page 5:** section 3.4 is an orphan heading without the promised explanation. Small cryptographic diagram text needs enlargement.
- **Page 7:** severe right-column overflow clips file paths, sentences and descriptions of layers 15–19. Content is genuinely unreadable, not just a text-extraction artifact.
- **Page 8:** model and performance diagrams need readable labels and mode-qualified captions.
- **Page 9:** rightmost verification column is clipped; “Part 1” of the test breakdown appears as a heading without its content.
- **Page 10:** “1-Command” contradicts the three verification steps, and one step is an HTTP call. Long monospace output is hard to scan. Replace staged-looking output with linked raw logs and concise evidence tables.
- **Whole document:** add repository/release identification, author/team, version/date, references, limitations and a clear implemented/experimental/planned legend. Exact source line numbers without a commit are unstable references.

## Recommended revision order

1. Identify the submitted implementation and release commit. If a separate vault implementation exists, review it before retaining those claims.
2. Align architecture, auth, model execution and feature status to that release.
3. Fix the EIP-712 typehash and threshold/nonce contradictions.
4. Rebuild the evidence table and reproduction guide from actual scripts, receipts and test logs.
5. Remove or qualify ZK, hardware, privacy, audit and universal-security claims.
6. Repair page overflow and re-render all 10 pages before submission.

A defensible opening for the current checkout is: “KiteShield is a constrained Sepolia wallet prototype. Explicit payment instructions pass screening and deterministic policy checks; short-lived backend capabilities authorize an independently revalidating logical signer. Durable reservations and transaction reconciliation support controlled execution and retry recovery. The signer shares the backend host; on-chain session-key enforcement and hardware isolation are not claimed.”
