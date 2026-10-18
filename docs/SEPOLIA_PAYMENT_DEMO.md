# Sepolia payment execution: implementation and handoff

Date: October 17, 2026. No live transaction was signed or broadcast in this task.
Organizer acceptance of Sepolia/testnet evidence remains to be confirmed.
This work does not implement session keys or account abstraction or claim a bonus.

## What changed

- Existing proposal/evaluation/approval/capability/signer flow remains the only payment path.
- Matching Sepolia receipts now reconcile signed, uncertain, and submitted executions.
  Confirmation is observation of a past side effect, not a fresh authorization.
- Persist full JSON receipts, outcome, block/gas data, explorer link (derived), and
  confirmation/reversion audit references. Concurrent refresh records one terminal event.
- Signed payload, nonce ownership, consumed capability, and spending reservation are
  committed before broadcast. Unknown results retain the same bytes and reservation.
- Live submitted payments remain RESERVED across UTC midnight until receipt reconciliation.
  Success commits principal spending to the UTC day of reconciliation; reversion releases
  principal only. Gas is still paid on-chain; the policy budget tracks payment principal,
  not gas. Gas/fee exposure is independently bounded by signer configuration.
- Dashboard refresh checks existing live hashes. Simulation never gets fabricated receipts.
  Outcomes distinguish signed, uncertain, submitted, confirmed, reverted, and simulated.
- The retry action uses the existing proposal signing endpoint: first check its stored hash;
  otherwise, only rebroadcast its identical signed bytes after current authorization and stop
  checks. It never creates another payment, changes its nonce, or automatically increases fees.
- Added read-only fee preview and evidence export commands. Neither signs or broadcasts.
- Database startup adds nullable `transactions.execution_outcome` and `receipt_json`
  columns if absent. No reset, rebuild, deletion, or historical authorization backfill.

Files changed in this task (other dirty files predate it):

Backend: `app/models/__init__.py`, `app/db/__init__.py`, `app/schemas/__init__.py`,
`app/api/routes/proposals.py`, `app/api/routes/transactions.py`,
`app/services/blockchain.py`, `app/services/execution.py`, new `app/services/receipt.py`,
new `scripts/preview_sepolia_payments.py`, new `scripts/export_payment_evidence.py`,
new `tests/integration/test_sepolia_execution.py`.

Frontend: `src/App.tsx`, `src/types/index.ts`, `src/components/ProposalCard.tsx`,
new `src/paymentReceipts.ts`, new `tests/paymentReceipts.test.ts`,
`tests/paymentUi.test.ts`. This report is new. No environment file changed.

## Current live prerequisites (read-only check)

- Configured RPC reached chain **11155111**, Sepolia.
- Configured sender: `0x43377ff27AB257A345490f4f728a56453F8b1582`.
- Its observed balance: **0 wei**; pending network nonce: **0**.
- Current application mode: **simulated** (unchanged).
- `APPROVER_API_KEY` and `POLICY_ADMIN_API_KEY` are not configured.
- User supplied an RPC URL, not a recipient. An explicit recipient `0x...` address and
  confirmation that the configured sender is a dedicated test-only wallet are still needed.

Proposed amounts, not authorized: **0.00001 ETH** and **0.00002 ETH**.
No proposals or payment intents have been inserted into the real database for these drafts.
Do not choose a destination on the user's behalf. Fund only a confirmed dedicated Sepolia
wallet with valueless test ETH. Do not import a wallet holding valuable assets.

## Setup and authorization gate

1. Preserve `backend/.env`; set distinct local `APPROVER_API_KEY` and
   `POLICY_ADMIN_API_KEY` values alongside the existing proposer `API_KEY`.
   Never put them in `VITE_*`, logs, or committed files. Keep the emergency-stop
   administrator credential separate and backend-only.
2. Keep `EXECUTION_MODE=simulated` initially and `CHAIN_ID=11155111`. The signer must
   use only a dedicated Sepolia test wallet. RPC access is needed for live preflight.
3. Start/restart from the project root (startup applies additive columns):

   ```sh
   cd backend
   ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

   In a separate terminal from the project root:

   ```sh
   cd frontend
   npm run dev
   ```

4. Connect each role through API key / Switch role. Create a Sepolia policy as Policy
   administrator with the explicit recipient allowlist, a sufficient principal budget,
   and an escalation threshold below 0.00001 ETH to demonstrate approval on both payments.
   Budget period is a UTC calendar day; outstanding reservations carry across days.
5. Once the recipient is known and the database initialized, use this read-only preview:

   ```sh
   cd backend
   ./.venv/bin/python scripts/preview_sepolia_payments.py --recipient 0xYOUR_RECIPIENT --amounts 0.00001 0.00002
   ```

   It may use live RPC even while the application is simulated; it never signs or sends.
   Its output shows sender, recipient, amounts, chain, estimated fees, maximum fee exposure,
   and funding sufficiency. The estimate uses the observed base/priority fees and padded gas;
   the maximum is gas limit times max fee per gas. Neither is a guarantee of final gas cost.
   Nonces are allocated durably by execution, not reserved by this preview.
6. **Stop before live execution.** Present that fresh preview for explicit authorization
   of both exact payments and their fee caps. If caps need to change, request renewed
   authorization. Merely providing an RPC or recipient is not broadcast authorization.
   Do not change execution mode or click Sign & broadcast on the user's behalf yet.
7. Only after explicit authorization, set `EXECUTION_MODE=sepolia` and restart. Create
   **new** live intents; never reuse a simulated attempt, which is rejected across modes.
   Use the existing agent workflow for each explicit amount and address, evaluate, approve
   with Human approver, and submit with Proposer. Stay within the authorized fee caps.

## Judge-facing demonstration script

1. "This is [Simulation / Ethereum Sepolia]. Simulation has no on-chain evidence.
   Sepolia uses test assets; organizer acceptance of testnet evidence is not yet confirmed."
2. Enter `Send 0.00001 ETH to <approved recipient>`. Show exact wei, policy version,
   escalation, and the unsuccessful attempt to approve with Proposer credentials.
   Connect Human approver; approve the exact action. Submit with Proposer after the live
   authorization gate above. Show submitted separately from confirmed.
3. Repeat for `0.00002 ETH`; show its next nonce and distinct hash. Wait for receipt
   reconciliation through dashboard refresh (every ten seconds) or the authenticated
   `GET /api/v1/transactions/<id-or-hash>` endpoint. Do not call pending "confirmed".
4. Show a proposal above the policy maximum or outside the allowlist being rejected.
   It must have no ExecutionAttempt/broadcast. This is also covered with fake RPC tests;
   no unsafe live transaction is necessary to demonstrate rejection.
5. Show the full matching receipt, explorer page, proposal ID, policy/approval/execution
   references, and correlated audit events. Export both proposals:

   ```sh
   cd backend
   ./.venv/bin/python scripts/export_payment_evidence.py FIRST_PROPOSAL_ID SECOND_PROPOSAL_ID
   ```

   Save this public JSON output with the submission evidence after live execution.
   It omits raw prompts, credentials, capability tokens, keys, and signed raw payloads.
6. "The signer rechecks authorization inside the monolith. This is logical isolation,
   not a separate signer process or hardware boundary. API roles and JWT capabilities
   are not on-chain session keys. These hashes demonstrate Sepolia payments, not
   competition eligibility or a guaranteed challenge bonus."

## Targeted validation

- Backend **71 passed**, zero failures, across:
  `test_sepolia_execution.py`, `test_payment_security.py`, `test_execution_boundaries.py`,
  `test_payment_migration.py`, `test_emergency_stop.py`, `test_capability.py`,
  `test_replay.py`, `test_token_attacks.py`, and `test_parameter_tampering.py`.
- The nine new Sepolia integration tests use real signing and file SQLite with fake RPC:
  agent/approval/confirmation and evidence, successive pending nonces, durable-before-send,
  accepted-but-timeout reconciliation, identical-byte retry, denied actions and wrong chain,
  reversion, mismatched receipt, concurrent budget contention, concurrent receipt refresh.
- Frontend **31 passed**; includes read-only receipt refresh, retained uncertainty on failure,
  simulation isolation, and server-rendered distinct outcomes/retry controls.
- Targeted Ruff and Python compilation: passed.
- Frontend lint, TypeScript and Vite production build: passed.
- `git diff --check`: passed. No full-suite run requested/performed for this bounded task.
- Actual RPC chain/balance checks were read-only. No real payment test has run; there
  are no new real hashes or receipts to present. Browser interaction testing is unavailable
  in current Work settings; UI checks are automated logic/server-render tests, not visual QA.

## Remaining limits and recovery

- One validated receipt is treated as confirmation, not consensus finality. Reorg monitoring,
  multi-provider verification and configurable confirmation depth remain unimplemented.
- If RPC errors or the transaction is dropped, keep its reservation and signed bytes.
  Use receipt refresh or the existing retry endpoint/action. Never create a duplicate intent
  to work around a timeout. No automatic replacement/cancellation or fee bump is implemented.
- A stale policy or expired approval blocks rebroadcast unless a receipt already proves
  execution. Unknown outcomes keep their reservation; do not manually release it without
  establishing the nonce/receipt outcome. Current SQLite serialization is the supported engine.
- Funding, recipient, role credentials, dedicated-wallet confirmation, fresh fee preview,
  and explicit broadcast authorization are the remaining live-demo prerequisites.
- Preserve this work and all prior modifications; nothing was staged, committed or pushed.
