# Treasury Autopilot implementation — October 19, 2026

## Delivered

- Pure integer-wei planner with explicit suppression/refill-only states.
- Additive mandate/action tables, version invalidation and durable leased SQLite
  claims. Retained UTC initiation history controls daily limits and cooldown.
- Lifespan-owned, off-by-default monitor and receipt-only recovery.
- Role-gated API and Treasury dashboard with separate standing-permission
  confirmation, explicit simulation/unavailable states and existing proposal cards.
- Deterministic mandate provenance; no fabricated BENIGN screening or user prompt.
- Fresh balance/fee/context and competing-execution fingerprint checks at shared
  authorization, then existing policy, reservation, capability, signer and RPC paths.
- Read-only live demo preparation and a local, read-only synthetic RPC demo fixture.
- API/setup/security/recovery documentation and 60–90 second judge script in
  `docs/TREASURY_AUTOPILOT.md`; README and safe config examples updated.

## Files

Backend new: `app/models/treasury.py`, `app/schemas/treasury.py`,
`app/services/treasury_planner.py`, `app/services/treasury.py`,
`app/api/routes/treasury.py`, `scripts/preview_treasury.py`,
`scripts/treasury_demo_rpc.py`; integration test `test_treasury.py` and unit tests
`test_treasury_planner.py`, `test_treasury_migration.py`, `test_treasury_lifecycle.py`.

Backend integration edits: `app/core/config.py`, `app/main.py`,
`app/models/__init__.py`, `app/schemas/__init__.py`, `app/api/routes/proposals.py`,
`app/services/execution.py`, `app/services/authorization.py`, `.env.example`.
Signer, capability, PolicyEngine, blockchain adapter, audit implementation,
emergency-stop service and role authentication files are unchanged.

Frontend new: `src/treasury.ts`, `src/views/TreasuryView.tsx`,
`tests/treasury.test.ts`. Integration edits: `src/App.tsx`, `src/api/client.ts`,
`src/components/Navigation.tsx`, `src/components/ProposalCard.tsx`,
`src/types/index.ts`, `src/index.css`. No dependencies added.

## Validation

- Backend full suite: **424 passed, 14 skipped** (includes 52 Treasury tests).
- Frontend full suite: **47 passed** (2 new Treasury tests).
- Ruff, frontend lint, TypeScript and Vite production build passed.
- Python compilation and `git diff --check` run at final handoff.
- A local HTTP synthetic RPC was exercised through the real observer; unsupported
  signing/submission methods were rejected. Lifespan opt-in and awaited shutdown
  are covered separately from monitor-loop cancellation.
- Existing Vite websocket port-in-use warnings appeared in SSR tests; no failed
  checks. Browser visual/interaction verification was unavailable (browser
  automation disabled). Frontend verification is API/SSR plus type/build checks,
  not proof of mouse/keyboard operation in a real browser.

Read-only live preview: block 11946392; balance `0.0499099999951358 ETH`, proposed
target `0.0498699999951358 ETH`, maximum sweep `0.00003 ETH`, reserve `781200 wei`.
This is a historical observation, not current permission or a fee guarantee.
No existing administrator/approver API credential was used.

## Status and next operator work

Implemented and exercised with isolated SQLite/fake RPC/public test keys. Actual
live Treasury execution remains **unactivated and unproven**. The live backend was
not restarted; live environment/database were not modified; no funded-wallet
signing or broadcast occurred. Existing unrelated files remain untouched. No
commit or push was made for this task.

Operator next: run the separate demo on ports 8001/3001 with synthetic read-only
RPC port 8547; review UI in a browser; apply a mandate using the policy-admin role;
enable plan-only and observe. Any future live execute activation/payment requires
separate explicit authorization. Observe freshly rather than reuse the preview.

Known limits: optional AI advisor not implemented; deferred unsigned intents need
explicit operator recovery and invalidated ones intentionally stay blocked (no
new resolution/cancellation workflow). Already-signed recovery reuses existing
bytes and cannot be undone by mandate disabling. Shared-host/logical custody,
trusted RPC and local audit history are not hardware isolation, external anchoring
or chain finality guarantees. Competition acceptance remains organizer-dependent.

## Follow-up: operator-requested restart integration

With the operator's authorization, `backend/.env` now sets
`TREASURY_MONITOR_ENABLED=true`, interval 60 seconds and claim lease 120 seconds.
No other limits, credentials or live mandate settings were changed. A read-only
database check confirmed the existing mandate remains enabled **plan-only**, version 2.
The operator will restart the backend; no restart, execute activation, signing or
broadcast was performed here. The committed example remains off by default.

The dashboard now explains each execute blocker, shows the observed balance and
refreshes saved state via GET every 15 seconds without starting observations or
payments. Execute confirmation and mandate editing retain the version originally
reviewed, so background refresh cannot silently apply permission to a new version.
The excess/minimum requirement remains enforced; the target was not lowered.

Tests explicitly override Treasury environment values so enabling a local monitor
does not activate monitoring in isolated tests. Frontend regression checks cover
monitor-disabled, insufficient-excess, administrator and expired-snapshot guidance.
