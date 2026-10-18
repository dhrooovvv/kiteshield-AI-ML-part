# Autonomous execution implementation — October 18, 2026

Branch: `codex/autonomous-payments`. Existing uncommitted work preserved.

Changed for this task: backend/.env.example; app/core/config.py;
app/api/routes/proposals.py; app/models/__init__.py; app/services/receipt.py;
new app/services/autonomous.py; new tests/integration/test_autonomous.py;
docs/AUTONOMOUS_PAYMENTS.md and this report. No frontend source changes needed:
existing proposal transaction rendering and ten-second receipt polling are reused.

CODEOWNERS-protected signer, capability, policy engine, authentication, audit service,
and blockchain adapter were not edited by this task. Those files already contain
uncommitted work from earlier tasks and are not clean relative to Git HEAD.

Validation: complete backend pytest: 362 passed, 14 skipped. New autonomous tests:
12 passed (fake RPC and test-only key; no network). Includes concurrent evaluation,
single stored execution, blocked eligibility, receipt confirmation, sequential nonces,
and timeout recovery retaining original signed bytes/hash. Backend Ruff and Python
compilation pass. Frontend: 33 tests pass; lint and TypeScript/Vite build pass.
Git diff whitespace check passes. Actual browser interaction was not verified.

Invariant wording: ALLOW now permits optional unattended execution only within the
additional autonomous eligibility gate; ALLOW alone is not authority. No manual human
click is required for eligible payments once the operator explicitly enables the flag.
Signer logical isolation, capabilities, approvals for escalations, current-policy checks,
aggregate reservations, fee bounds, and emergency stop remain unchanged.

Limits: flag remains false; live configuration was not changed, no application restart,
no live signing/broadcast. No automatic restart worker, fresh-nonce retry, or queue.
Pending payments reconcile through existing receipt polling; subsequent waiting proposals
require reevaluation. Failures require inspection and existing same-execution recovery.
Existing proposals lack benign provenance and cannot auto-execute. Separate repeated
Propose requests remain separate payment intents; deduplication is per proposal.

Enablement and any live smoke payment require separate operator authorization. Follow
AUTONOMOUS_PAYMENTS.md; never treat tests as evidence of a new on-chain transaction.
