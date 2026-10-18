# Screening-counter integration fix

Root cause: prompt screening rejected attacks before creating a proposal. The overview
counted only BLOCKED proposals, so screening attacks were invisible even after refresh.
BLOCK/REVIEW errors also did not notify the dashboard to refresh immediately.

Changes in this task:
- backend/app/api/routes/proposals.py: persist PROMPT_SCREENING_BLOCKED through the
  existing audit interface before returning the unchanged screening rejection.
  Records include digest and reason, never raw prompt. SQLite execution locking plus
  the existing unique audit dedupe key make concurrent retries atomic. Same correlation
  ID and same prompt count once; separate request IDs count separate blocked attempts.
- backend/app/api/routes/audit.py: authenticated GET /api/v1/audit/screening-counts
  returns total blocked count plus separate screening/policy counts. Database aggregates
  are independent of the displayed 50-proposal page. A screening block creates no
  proposal and is not an approval, successful transaction, or broadcast.
- frontend/src/api/client.ts: notify subscribed dashboard refresh on BLOCK/REVIEW,
  preserving the original rejected Promise; add aggregate read method.
- frontend/src/App.tsx and views/OverviewView.tsx: fetch/present the persistent blocked
  aggregate and subscribe/unsubscribe refresh notifications. Refresh failures retain
  previous values and show an error. Existing escalation and approval behavior unchanged.
- backend/tests/integration/test_screening_counters.py and frontend/tests/apiRefresh.test.ts:
  concurrent deduplication, persistence across reads, no execution/capabilities/proposals
  for attacks, policy blocks distinct from human escalations, notification and rejection
  behavior, backend aggregate reads.

Validation: backend complete suite 364 passed, 14 skipped; frontend 37 passed;
Ruff, Python compilation, frontend lint, TypeScript/Vite build, git diff --check passed.
Tests used isolated SQLite and synthetic credentials, with execution forbidden in new
counter tests. No live payment endpoint was called and no signing/broadcast occurred.
No production policy/limits/credentials or CODEOWNERS-protected service was modified.
The Impeccable hardening guidance informed error preservation and subscription cleanup;
the incumbent UI layout and styling were retained. Browser visual QA was not performed.

Limits: historical screening blocks without audit records cannot be reconstructed and
are not backfilled. Repeating the same prompt under a new correlation ID is a new
attempt. Existing escalation/review list pagination semantics are unchanged.
