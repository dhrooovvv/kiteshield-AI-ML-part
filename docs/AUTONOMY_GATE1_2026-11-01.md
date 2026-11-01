# KiteShield durable autonomy — Gate 1 report

## Scope and status

This is a separate, opt-in, **simulation-only prototype**, not a replacement for
the main wallet. Gate 1 is not fully demonstrated with real Gemma. Stop here for
review before Gate 2. No live autonomous operation is claimed.

Historical evidence baseline: commit `f7727c7`, tagged
`evidence/sepolia-confirmed-2026-10-18` before implementation. The tag identifies
committed historical receipt evidence; it is not a fresh chain verification or
an assertion that the current dirty checkout matches the historical execution.
Branch: `codex/durable-goals-gate1`. Pre-existing uncommitted work is preserved.

## Delivered

- `backend/demo_autonomy/engine.py`: SQLite tasks, typed steps, step leases,
  idempotency keys, persisted events, plan validation, task and cumulative mandate
  budgets. Re-created engine instances resume persisted work.
- An authenticated instruction in the exact grammar
  `fund if needed, pay supplier Acme 10 wei, verify` binds a supplier and amount
  from an administrator-created demo mandate. A model cannot supply a payee,
  address, amount, endpoint, or permission.
- Gemma/Ollama proposes only the ordered tool names: balance, fund, payment,
  receipt. JSON-schema request, strict parsed output, temperature zero, bounded
  timeout and fixed loopback URL. Exact Ollama version and model digest are
  mandatory and verified before inference. No downloads or model pulling.
- Invalid/missing planning, changed mandates, insufficient authority and unresolved
  outcomes produce `HUMAN_REQUIRED` with a reason. No automatic human fallback
  decision, proposal approval, policy expansion, or alternative endpoint exists.
- Task limits can only decrease through the agent endpoint. Only the distinct
  administrator credential can replace the demo mandate or raise its limits.
- An uncertain or expired in-progress step is reconciled, not reissued. An
  unresolvable result requires a human; reconciliation failure also stops retries.
- `server.py`: role-separated demo API and background worker. Both feature flags
  default off. `run.py` binds only `127.0.0.1:8001`, creates a private temporary
  profile and independent demo credentials, and supports `--resume` for that profile.
- `SimulatedAdapter`: atomic persistent local balance/funding/payment/receipt
  effects, explicitly marked SIMULATED. No real key, transaction hash or chain
  receipt is manufactured. Does not import the main application or signer.

## Not delivered at this gate

- Actual Gemma inference: local Ollama was unreachable during the read-only check.
  Request formatting is tested with a fake HTTP transport; plan/state tests use
  injected fixed responses. This is not evidence of model accuracy or latency.
- Calls to the existing configured faucet, proposal/policy pipeline, signer, or
  receipt service. The adapter currently uses only the isolated simulation ledger.
  Integrating those services remains necessary before claiming the full wallet
  goal works. No alternative real wallet/signing implementation was introduced.
- Gas accounting, real funding provider cooldowns/receipts, approval task resumption,
  exceptions inbox, streaming timeline UI, self-quarantine, on-chain enforcement,
  voice, x402, or additional networks. Those belong to subsequent gated work.
- New UI: port 3001 remains reserved for the isolated demo frontend. The existing
  dashboard has not been connected to this separate API. This gate is backend-only.
- Global exactly-once delivery to arbitrary external providers: the simulation
  adapter has atomic effects; external adapters will need reconciliation support.
- External documents, voice or incoming-token events as trigger channels. None
  are wired into this prototype and none can create or modify authority.

## Verification

- 22 Gate 1 tests passed. They cover restart through persistent storage, repeat
  submissions, duplicate workers, wrong tool/order/extra-field plans, invalid
  goals and recipients, budget exhaustion, only-tightening behavior, changed
  mandates, lost payment responses, unknown outcomes, role separation, disabled
  flags, missing model pins, planner failure/timeout, and the model HTTP payload.
- Existing backend suite: **647 passed, 14 skipped** in a disposable profile.
- Existing frontend suite: **79 passed**; lint and production build passed in a
  disposable copy excluding `.env` files and using existing dependencies.
- New code Ruff check passed. No protected execution/security files were edited.
- First regression attempt: one test failed because the initial network guard
  denied its own local mock RPC server (646 passed, 14 skipped). The verification
  harness was corrected to permit only ephemeral loopback servers bound by that
  test process. The full backend suite then passed. It cannot reach existing live
  listeners or external hosts.
- These are engineering tests, not a model benchmark. No statistical accuracy,
  confidence-interval, production-security or live-payment claim is made. Any
  later evaluation must use a committed frozen set and report confidence intervals.

The harness runs tests from a temporary directory with a minimal environment,
no `.env`, offline model settings and guarded sockets. Existing tests may exercise
signing with their existing test-only key/fake RPC fixtures; the new orchestrator
never signs. Live environment files, databases and running backend were not read,
modified, stopped or restarted.

## Dependencies and reuse decision

No repository was downloaded and no dependency installed or added. Existing
runtime versions used: FastAPI 0.143.0 (MIT), HTTPX 0.28.1 (BSD-3-Clause),
Pydantic 2.14.1 (MIT), Uvicorn 0.54.0 (BSD-3-Clause), pytest 8.4.2 (MIT).
These are observed environment versions, not a new project-wide lockfile.

Gemma/Ollama are disabled until explicitly enabled with exact runtime/model pins.
The default model name is only a selector, not proof of a locally installed model.
Model-specific license/terms and the selected model digest remain to be reviewed
before downloading or adopting a model for this demo.

AgentKit and MetaMask Smart Accounts Kit are deferred: wallet integration is
unnecessary for this state-machine gate and their signing paths must not replace
KiteShield's signer. whisper.cpp is deferred to the optional voice gate. Foundry
is deferred to the separate enforcement spike. No licenses/versions for those
unadopted packages are asserted; evaluate and pin before adoption.

## Running the isolated prototype

From `backend`, run `.venv/bin/python -m demo_autonomy.run`. This serves health
only with autonomy disabled by default. Opt-in flags are `--enable --gemma`, plus
`--model`, `--model-digest` (64-character SHA-256) and `--ollama-version`.
No model is installed by the launcher. Missing/unavailable pins or inference
cause human-required status rather than a guessed plan.

The launcher prints only the profile path; private demo tokens are in its
mode-0600 `demo-credentials.json`. Do not put tokens in goals or logs.
`--resume <previous-temp-profile>` reuses its task database and demo credentials;
repeat opt-in flags and pins deliberately on restart. Bind address and port cannot
be overridden. Do not point any frontend at a live backend; 3001 is the reserved
demo UI port.

API: administrator `PUT /mandate`; agent `POST /goals`, `GET /goals/{id}`,
`POST /goals/{id}/tighten`. Each uses its separate Bearer token. Goal requests use
`goal` and `request_key`; budget fields are exact integer wei. Mandates supply
`supplier`, `recipient`, `payment_cap`, and `funding_cap`. Caps are cumulative per
mandate version; an administrator replacement invalidates old pending tasks.

Reproduce isolated checks: from `backend`, run
`.venv/bin/python -m demo_autonomy.verify`. Logs and results are retained in a new
private temporary verification directory. It does not start or stop any app server.

## Gate decision

Reviewable simulation foundation implemented. Real Gemma planning and integration
with the existing wallet services remain unverified/unimplemented respectively.
Do not mark the overall acceptance criteria complete. Stop before Gate 2;
no self-quarantine, on-chain or voice work has started.
