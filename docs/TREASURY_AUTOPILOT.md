# Treasury Autopilot

## Scope and current status

Implemented: integer-wei planner, additive persistence, durable multi-worker SQLite
claims, lifespan monitor, authenticated API, dashboard, mandate provenance, existing
payment coordinator integration and receipt reconciliation. Off by default.
First activation is plan-only. The optional model advisor is deliberately not
implemented: explanations are deterministic, and no model has treasury authority.

Execution integration is exercised with fake Sepolia RPC and the documented public
test key only. **No live Treasury mandate has been persisted/activated; no funded
wallet has been signed with or broadcast by this implementation task.** A separate
read-only live preview is below. Existing live configuration/database are preserved.

## Planner and scope

All amount inputs/storage/API values are unsigned integer-wei strings, bounded by
uint256; target may be zero, sweep maximum/minimum must be positive. Recipient and
sender must differ and be nonzero public Ethereum addresses. Sender must match the
configured signing address; only Sepolia chain 11155111 is accepted.

`available_excess = observed_balance - target_balance - maximum_fee_reserve`

Below target means **human refill alert only**, never refill authority. Excess below
minimum means no sweep. Otherwise candidate is `min(excess, sweep_maximum)`; it is
not reduced/split to evade policy, approval thresholds or the global cap.

The read-only observer verifies chain identity twice, pins balance to a numbered
block with its hash/time, and uses the existing `prepare_transaction` gas preflight.
Reserve is padded gas × quoted maximum fee per gas; preparation already enforces
configured gas/fee bounds and unsupported contract-recipient restrictions. There
is no assumed live 21,000-gas transfer. A new-recipient high-gas regression is
covered. A failed fee quote cannot authorize a sweep. Simulation quotes are labelled.

Planner states: `DISABLED`, `BELOW_TARGET`, `WITHIN_TARGET_BAND`, `ELIGIBLE`,
`COOLDOWN_ACTIVE`, `DAILY_ACTION_LIMIT`, `OUTSTANDING_EXECUTION`,
`INVALIDATED_MANDATE`, `POLICY_RESTRICTED`, `NETWORK_UNAVAILABLE`, `STALE_SNAPSHOT`,
`EXECUTION_UNAVAILABLE`. Stable reason codes explain suppression. Missing RPC data
is unavailable, never interpreted as a zero balance.

## Persistence, claims, recovery

Two new tables on existing SQLAlchemy metadata: `treasury_mandates` (singleton,
versioned config, authenticated actors, mode, latest observation/plan, claim lease)
and `treasury_actions` (immutable config/version/observation snapshot, unique claim
token, unique proposal link, digest, initiation time and outcome). Existing
`init_db` creates missing tables additively; no old table/data is reset or removed.

SQLite `lock_execution` serializes claims and initiation across worker processes.
Claim transactions commit before slow RPC calls. Lease defaults to 120 seconds;
after expiry a worker may observe again, but a stale lease-holder cannot initiate
using a superseded token/version. A durable proposal and action-slot consumption
commit together before execution. Any unresolved treasury proposal or unresolved
execution blocks the next sweep. Outstanding manual signed/submitted attempts
also block new sweeps.

Cooldown and daily usage come from all retained initiation records, not editable
mandate counters. **A durable proposal initiation consumes one slot**, including
later failures, invalidation or deferral. UTC calendar days are explicit. Edits
disable the mandate, increment version and invalidate old unsigned authority;
history remains. There is no mandate-delete/reset endpoint.

A crash after initiation leaves the existing intent outstanding, never a replacement
proposal. The monitor does not automatically retry fresh signing, bump fees or
rebroadcast. It reads receipts using the existing receipt validator and records
meaningful transitions. Signed/uncertain attempts keep the same execution, nonce,
bytes and reservations. Existing proposer-authorized `/proposals/{id}/sign` recovery
may retry those bytes under existing financial/emergency checks. Disabling cannot
undo a signature or cancel a transaction already accepted by the network.

Unsigned deferred proposals remain conservatively outstanding; there is no new
automatic retry/cancellation workflow. Operator intervention through the existing
execution API is required, and only a still-current enabled mandate can grant new
signing authority. An invalidated unsigned intent intentionally remains blocked
until a future separately designed resolution workflow; do not delete its record
to bypass this. Monitor receipt reconciliation is bounded to 10 candidates/pass.

## Existing execution integration and enforcement

The monitor creates a typed, exact native-payment proposal and a genuine
deterministic policy decision, linked uniquely to its mandate/version. Its text is
a labelled system description, not a fabricated user prompt. No `BENIGN` screening
record or `AutonomousIntent` is forged. API/card provenance is
`DETERMINISTIC_MANDATE`, with mandate version. Agent prompt provenance remains
separate; screening/model policy is unchanged.

Execution calls the existing `execute_payment`, capability issuer, signer and
blockchain adapter. Existing signer, capability, financial policy engine and
blockchain files are unchanged. Only orchestration and the shared authorization
gate gain a treasury restriction:

1. Before acquiring the execution write lock, the coordinator gets a fresh
   balance/block/fee observation. This runtime proof cannot come from API inputs.
2. Under the existing lock, authorization rechecks mandate version/config, enabled
   execute mode, configured sender/chain/recipient, snapshot age/block age, digest,
   available excess, conservative fee reserve, global flags, cooldown, action count,
   outstanding execution and current policy/budget.
   An execution/spending-state fingerprint also rejects a competing payment that
   completed between observation and lock acquisition, not just pending payments.
3. Require explicit recipient allowlisting, amount ≤ global automation cap and
   **strictly below** policy approval threshold; no escalation or splitting.
4. Capability issuance and independent signer revalidation run the same gate.
   Prepared-envelope fee exposure may not exceed the fresh reserve.
5. Existing atomic spending reservations, fresh policy version, nonce ownership,
   envelope binding, single-use capability and emergency-stop checks remain intact.

Already-signed recovery retains its prior identity instead of asking for fresh
mandate permission; all pre-existing financial authorization and emergency-stop
checks still apply. A mandate cannot widen financial policy authority.

## API (prefix `/api/v1/treasury`)

Every route uses existing envelope/error conventions and runtime `X-API-Key` auth.
Credentials are not configuration-body fields. No frontend build credentials.

| Route | Role | Effect |
|---|---|---|
| `GET /treasury` | Any verified read role | Saved mandate/status/observation, global availability, counters; no RPC, proposal or execution |
| `GET /treasury/actions` | Any verified read role | Last 20 actions with linked proposal/execution/hash evidence; no execution |
| `PUT /treasury/mandate` | Policy administrator | Save disabled versioned mandate; optimistic version check |
| `POST /treasury/mode` | Policy administrator | Explicit off / plan-only / execute transition |
| `POST /treasury/observe` | Policy administrator | One bounded observation, **always plan-only**, even while execute mode is selected |

Simulation-only demo administrator retains existing isolated-profile requirements.
Proposer/human-approver credentials cannot configure/activate/observe a standing
mandate. A demo credential cannot enable live execution.

Create body (zero for `expected_version` only on first create):

```json
{
  "expected_version": 0,
  "sender": "<configured public signer address>",
  "recipient": "<explicit allowlisted public address>",
  "chain_id": 11155111,
  "target_balance_wei": "49000000000000000",
  "sweep_maximum_wei": "30000000000000",
  "minimum_excess_wei": "20000000000000",
  "cooldown_seconds": 600,
  "daily_action_limit": 3,
  "freshness_seconds": 60
}
```

Enable plan-only: `{"expected_version":1,"mode":"plan_only"}`. Observe with
`POST /treasury/observe`, no body. Separate execute confirmation:
`{"expected_version":2,"mode":"execute","confirm_standing_permission":true}`.
Disable with current version and `"mode":"off"`. Every mode transition increments
version. Refresh after every mutation; stale versions are rejected. Never infer
permission from an optimistic frontend state.

Errors: `MISSING_API_KEY`/`INVALID_API_KEY` (401), `ROLE_FORBIDDEN` or existing demo
isolation errors (403); `VALIDATION_ERROR` (422) for invalid config, stale
`MANDATE_VERSION_CONFLICT`, `POLICY_RESTRICTED`, premature activation or
`EXECUTION_UNAVAILABLE`; standard schema errors reject extra/invalid fields.
Shared-boundary denials use existing signing/policy/emergency error codes.
Read-only status reports availability reason codes such as `MONITOR_DISABLED`,
`GLOBAL_AUTOMATION_DISABLED`, `LIVE_SEPOLIA_REQUIRED` without exposing RPC URLs.

## Configuration and isolated start

Safe defaults in `backend/.env.example`:

```dotenv
TREASURY_MONITOR_ENABLED=false
TREASURY_MONITOR_INTERVAL_SECONDS=60
TREASURY_CLAIM_SECONDS=120
```

Interval validates 30–3600 seconds, claim lease 60–600. Lifespan starts monitoring
only with the explicit flag and cancels/awaits the task on shutdown. Execute
additionally requires existing `AUTO_EXECUTE_ENABLED=true`, verified live Sepolia
mode and all mandate/policy gates. This task changes **no live environment file**.

To run a separate plan-only UI demo, keep the existing backend running untouched:

1. In `backend/`, create `.env.demo` from `.env.demo.example` **only if it does not
   already exist**. Generate independent application/demo secrets as its comments
   instruct. Keep its public `b…b` test signer, exact `kiteshield-demo.db` path,
   `APP_ENV=demo`, `APP_DEBUG=false`, `EXECUTION_MODE=simulated`. Never copy live keys.
2. Set only this demo profile's `SEPOLIA_RPC_URL=http://127.0.0.1:8547`,
   `TREASURY_MONITOR_ENABLED=true`, `AUTO_EXECUTE_ENABLED=false` and
   `APP_CORS_ORIGINS=http://localhost:3001`.
3. Start the synthetic **read-only** fixture:
   `./.venv/bin/python scripts/treasury_demo_rpc.py`.
4. In another terminal, `backend/`:
   `./.venv/bin/uvicorn app.main:app --env-file .env.demo --host 127.0.0.1 --port 8001`.
   Do not use `--reload` for the demo or restart the live port 8000 process.
5. In `frontend/`:
   `VITE_API_BASE_URL=http://127.0.0.1:8001/api/v1 npm run dev -- --port 3001`.
   Enter the isolated demo credential at runtime. Configure its policy to allow
   the intended recipient, threshold `0.001 ETH`, max `1 ETH`, budget `1 ETH`.
6. Treasury → Configure mandate: sender comes from this **public fixture**, not
   the funded wallet. Synthetic balance is `0.05 ETH`; use target `0.049 ETH`,
   sweep max `0.00003 ETH`, minimum `0.00002 ETH`, 600-second cooldown, 3/day.
   Save disabled → enable plan-only → Observe once. Execute remains unavailable
   in this simulation. The fixture rejects signing/submission RPC methods.

Exercise execution integration without live services:

```sh
cd backend
./.venv/bin/pytest -q tests/integration/test_treasury.py tests/unit/test_treasury_planner.py tests/unit/test_treasury_migration.py tests/unit/test_treasury_lifecycle.py
```

Those tests use file-backed isolated SQLite, fake Sepolia RPC and only public test
keys; they exercise the real capability/signer/coordinator code, not a replacement
payment implementation. They cannot demonstrate a real on-chain Treasury sweep.

## Read-only live demo preparation (not an activation)

Prepared October 19, 2026, at 11:57 IST / 06:27 UTC. Observation block `11946392`,
hash `0x98c5f373590526a12d8bab28612fdb7e5d7eb9536327c435338a790170b9e726`.

- Sender: `0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7`
- Recipient: `0x229D5588641f2614e3F486c853D8BA0eC5FFe811`
- Observed balance: `49909999995135800 wei` (`0.0499099999951358 ETH`).
- Proposed target, calculated once as balance minus `0.00004 ETH`:
  `49869999995135800 wei` (`0.0498699999951358 ETH`).
- Maximum sweep `30000000000000 wei`; minimum excess `20000000000000 wei`.
- Cooldown 600 seconds, 3 initiated actions per UTC day, freshness 60 seconds.
- Read-only padded gas quote 25,200; max fee 31 wei/gas, priority 1 wei/gas;
  fee reserve `781200 wei`. Pending candidate nonce was 5 (not reserved).
- Available excess after that reserve: `39999999218800 wei`.
- The existing explicit allowlist/policy scope check returned allowed.

This is historical preview evidence, not authority and not a current fee quote.
The operator must apply configuration through the dashboard, observe freshly and
separately authorize activation. No caps/fees/policy were loosened for eligibility.
`scripts/preview_treasury.py` prepares a read-only proposal without initializing DB,
saving a mandate, using administrator/approver API credentials, signing or broadcasting.

## Security guarantees and remaining limits

| Threat | Enforcement | Regression evidence | Limitation |
|---|---|---|---|
| Proposer creates unattended spend authority | Existing policy-admin dependency on all mutations | Treasury role/activation tests | Application roles share one backend host |
| Refresh causes payment | GET reads only; Observe forces plan-only | API/UI read-only tests and execute-mode manual observation test | Operator execute activation is standing permission |
| Duplicate timers/workers/restart pay twice | SQLite lock, leased token, unique action/proposal link, outstanding intent | Concurrent execution, expired claim and uncertain recovery tests | SQLite only; DB loss/tampering outside guarantee |
| Mandate changes after proposal | Fresh context + shared authorization/signer gate, version/digest binding | Edit-during-RPC and unsigned manual-execution rejection tests | Already signed transactions cannot be undone |
| Stale/wrong chain/fee or balance errors | Pinned observation, freshness/chain checks, bounded preflight | Wrong chain, stale block, balance, high gas, fee tests | RPC trust, chain reorgs and external wallet spends remain possible |
| Budget/cap/approval bypass | Existing PolicyEngine, spending reservations, strict threshold/global cap, explicit allowlist | Treasury scope tests + existing payment security suite | Principal accounting excludes gas; reserve separately protects observation target |
| Counter resets by edits | Count retained initiation records with UTC dates | UTC/cooldown/edit regression | Deliberate administrator DB changes defeat local records |
| Uncertain submission becomes replacement | Existing signed bytes/nonce/reservation identity retained | Uncertain retry test + existing execution suite | Manual same-transaction recovery may still require operator attention |
| Emergency stop bypass | Existing authorization/sign/submission stop checks | Treasury stop and existing boundary tests | Cannot undo a transaction already accepted by network |

Signer isolation is **logical**, not a separate process/HSM. Custody, database and
secrets share a host. Hash-linked audit records are local tamper-evidence, not
independent immutable/external anchoring. Receipt success is not a finality guarantee.
No production-safety, competition-eligibility, session-key or bonus-award claim.

## 60–90 second judge script

“This Treasury Autopilot uses a standing administrator mandate, not a one-off
payment prompt. Here are its exact recipient, target, sweep maximum, cooldown and
UTC action budget. It starts disabled. I enable plan-only and request an
observation; it verifies the network, accounts for bounded fees and produces an
integer-wei recommendation without creating a proposal or signing authority.

Refresh only reads saved data. Here a below-target observation asks a human to
refill; it cannot move funds into the wallet. Execute requires a separate standing
permission and the existing global live settings. It cannot exceed policy or
cross the approval threshold. The same capability, signer, spending reservation
and receipt workflow handles execution.

This dashboard demo is simulation, not an on-chain payment. The isolated fake-RPC
tests show one payment under concurrent ticks, a preserved nonce/transaction on
timeout, and rejection after mandate invalidation. The action links expose mandate
version, block, proposal and receipt evidence. No live Treasury sweep has yet been
authorized or demonstrated.”
