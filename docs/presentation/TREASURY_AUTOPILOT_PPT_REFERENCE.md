# KiteShield Treasury Autopilot

Presentation reference and short technical overview · October 19, 2026

## 1. What is Treasury Autopilot?

Treasury Autopilot is KiteShield's **mandate-based wallet balance manager**. It
monitors a configured Sepolia wallet and can transfer excess ETH to a designated
recipient while retaining an operator-defined target balance and accounting for fees.

Instead of entering a payment instruction every time, an administrator defines a
standing mandate. The system then evaluates whether a bounded sweep is eligible.
It does not transfer the entire balance or treat automation as unrestricted access.

**PPT takeaway:** “Keep a target wallet balance and move eligible excess under
explicit, enforceable spending rules.”

## 2. What it can do

- **Monitor balances:** Read the sender's ETH balance and record the observation
  block, block hash and time, verifying Sepolia chain `11155111`.
- **Plan before executing:** Start disabled, then use plan-only mode to inspect
  recommendations without creating an executable payment.
- **Sweep eligible excess:** In explicitly enabled execute mode, initiate a
  native ETH payment within the mandate and existing financial policy.
- **Limit unattended activity:** Enforce a maximum sweep, minimum excess,
  cooldown and maximum initiated actions per UTC day.
- **Explain inactivity:** Show insufficient excess, cooldown, stale observations,
  policy restrictions, network failures or outstanding executions.
- **Track evidence:** Link mandate versions to proposals, audit records,
  transaction hashes and receipt outcomes.
- **Alert below target:** Ask a human to refill the wallet; it has no automatic
  refill authority.

The dashboard separates configuration from eligibility. It shows the latest
activity inline, with earlier activities and payment details in scrollable dialogs.

## 3. How a sweep is calculated

All financial arithmetic uses **integer wei**, not floating-point ETH.

```text
available excess = observed balance − target balance − maximum fee reserve

If available excess < minimum excess: no sweep
Otherwise: candidate amount = min(available excess, maximum sweep)
```

Fee reserve comes from the existing bounded transaction preflight: padded gas
estimate multiplied by the quoted maximum fee per gas. Live transfers do not assume
a fixed 21,000-gas cost. A candidate must still pass every authorization check.

The planner is **deterministic**, not an LLM making financial decisions. The
optional AI explanation advisor has not been implemented.

## 4. Technical architecture and execution

The feature extends KiteShield's existing modular monolith:

| Component | Responsibility |
|---|---|
| React + TypeScript dashboard | Runtime credentials, mandate controls, status and evidence |
| FastAPI API | Authenticated reads and administrator-only mandate mutations |
| Pure planner | Exact calculation and explicit eligibility/suppression reasons |
| Lifespan-managed monitor | Periodic observations and bounded initiation; currently configured at 60 seconds |
| SQLite + SQLAlchemy | Versioned mandate, durable claims, action history and proposal references |
| Existing execution coordinator | Policy, spending reservations, capability, signer, broadcast and receipt handling |

An eligible sweep follows this sequence:

1. Acquire a durable monitoring claim and obtain a fresh network observation.
2. Calculate excess and check mandate, policy, cooldown, daily usage and pending work.
3. Persist one proposal with explicit **deterministic-mandate provenance**.
4. Revalidate fresh authority and reserve spending through the existing workflow.
5. Issue a transaction-bound capability; the logical signer independently validates it.
6. Persist signed execution state before broadcast, then reconcile the receipt.

Plan-only creates no executable proposal or capability. Refresh reads saved state;
the explicit one-off observation operation also remains plan-only.

## 5. Security and recovery boundaries

- Only the policy-administrator role can configure or activate a standing mandate.
- Execute activation requires separate confirmation and global execution flags.
- Recipient must be explicitly allowlisted; amount must fit the global automation
  cap and remain **strictly below** the policy approval threshold.
- Current policy, aggregate spending reservations, bounded fees and emergency stop
  remain enforced. Candidates are not split to evade approval requirements.
- Database-backed claims and unique proposal links prevent duplicate initiation
  across concurrent workers. Unresolved work blocks another sweep.
- Mandate edits/disabling invalidate fresh authority for old unsigned proposals.
  They cannot undo a signature or reverse a broadcast transaction.
- Uncertain broadcasts retain the same signed bytes, nonce and reservation.
  Recovery must not silently create another payment; no automatic fee bumping or
  fresh-signing retries are introduced.

**Limits:** Signer isolation is logical and shares the backend host; it is not an
HSM or separate-process custody boundary. Local hash-linked audits are not externally
anchored immutable records. Receipt confirmation is not a finality guarantee.

## 6. Demonstration evidence and validation

A read-only inspection of the local application records found this Treasury sweep:

| Evidence | Recorded value |
|---|---|
| Mandate version | `13` |
| Amount | `0.00003 ETH` (`30000000000000 wei`) |
| Recipient | `0x229D5588641f2614e3F486c853D8BA0eC5FFe811` |
| Proposal | `29d5bdbf-927d-4ba2-9073-1ffeb6cce7fc` |
| Execution mode / outcome | `sepolia` / `CONFIRMED` |
| Stored receipt | Status `1`, block `11946646` |
| Transaction | `0x60e81e80a695f0923c78523d184a9f910f8f404e501fdce9df2a9b6a44aa3ef0` |

[Open the recorded transaction on Sepolia Etherscan](https://sepolia.etherscan.io/tx/0x60e81e80a695f0923c78523d184a9f910f8f404e501fdce9df2a9b6a44aa3ef0).
These values were checked against persisted application/receipt records while
writing this document; the explorer and network were not independently re-queried.
This is testnet evidence, not proof of production readiness or competition acceptance.

Latest recorded automated checks: **424 backend tests passed, 14 skipped; 49
frontend tests passed.** Ruff, frontend lint, TypeScript, Python compilation and
production build passed in their respective verification runs. Coverage includes
concurrent initiation, stale/invalid mandates, scope/budget restrictions, uncertain
recovery and additive migration. Browser visual verification remains unavailable.
Tests were not rerun for this documentation-only change.

## Suggested five-slide PPT structure

1. **Problem:** Repeated manual treasury payments create operational work.
2. **Solution:** A standing mandate retains a target balance and bounds excess sweeps.
3. **Mechanism:** Observation → deterministic plan → existing authorized execution.
4. **Security:** Role separation, policy limits, durable deduplication and safe recovery.
5. **Evidence and limits:** Recorded Sepolia sweep, tests, shared-host custody and
   organizer-dependent acceptance. API roles/JWT capabilities are not on-chain
   session keys or account abstraction.

### Short speaker note

“Treasury Autopilot changes the interaction from repeated payment commands to a
bounded standing mandate. The operator chooses the target, recipient and limits.
KiteShield monitors the wallet, reserves for fees and moves only eligible excess.
Every payment still goes through deterministic policy, spending reservations,
capability verification, signing and receipt tracking. A recorded Sepolia sweep
demonstrates the flow; it does not imply unrestricted authority or production custody.”

For exact routes, configuration and recovery details, see
[Treasury Autopilot technical handoff](../TREASURY_AUTOPILOT.md).
