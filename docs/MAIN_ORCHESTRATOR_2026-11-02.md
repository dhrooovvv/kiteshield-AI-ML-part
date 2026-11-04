> Superseded by [the completion report](KITESHIELD_COMPLETION_2026-11-02.md).
> This document records the earlier activation before voice, the incoming observer,
> the confirmed transfers and the approved vault integration.

# Durable orchestrator enabled on the existing wallet

2 November 2026. Supersedes the preceding report that the durable orchestrator
was disabled, and the earlier separate-wallet runtime.

The main frontend at **http://localhost:3000** now exposes **Autonomous Tasks**.
The normal main backend remains on 8128, using the original wallet
`0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7`, original role credentials, original
`backend/kiteshield.db`, existing RPC and unchanged core policy version 6.
Only new autonomy flags, planner pins, workflow scope and session budgets were
added to the private configuration. Every non-autonomy setting was compared
with a private pre-change copy and was unchanged.

## Status

| Feature | Current evidence |
| --- | --- |
| Durable typed goals and fixed Gemma plan | Implemented and enabled; fresh local Gemma call returned balance → fund → payment → receipt |
| Existing-wallet integration | Implemented and enabled; original address and actual balance shown in the UI |
| Task budget and fee reservations | Implemented; tested in isolated databases; payment and fee reservations persist across restarts |
| Existing policy and vendor checks | Preserved; new workflow mandate does not rewrite the core policy; vendor version binding uses the existing core validator |
| Human approval isolation and resume | Implemented; isolated main-app test verifies one task pauses and a human role resumes it while another task continues |
| Lost-response and restart behavior | Implemented and tested; uncertain payment ownership blocks another payment; the same signed transaction is reconciled rather than signed again |
| Exceptions and persisted timeline | Implemented; UI reads the durable task journal |
| Self-quarantine | Implemented for the durable orchestrator; only its administrator role may resume it |
| Incoming permission-like events | Explicit event hook implemented; automatic token/NFT event subscriptions are not implemented |
| Real Sepolia preflight | Verified with original RPC/wallet; 25,200 estimated gas and 856,800 wei estimated fee ceiling at observation; no signature or broadcast |
| New orchestrator's first real payment and receipt | **Unverified live**; no new payment was created during this activation |
| Automatic faucet funding | Adapter and workflow implemented, but **unavailable in this installation**: existing faucet is disabled and has no provider credentials; funding budget remains zero |
| Guarded vault/session key integration | Not integrated; the existing isolated spike is retained. Integration requires protected signing/execution changes prohibited by the remaining hard rules |
| Local whisper.cpp voice | Not implemented; earlier browser voice support is not local whisper.cpp |

This is not a claim that every original goal feature is complete or that live
end-to-end autonomous funding/payment has been demonstrated.

## Current scope

The administrator standing mandate is **Northstar Services**, recipient
`0x229D5588641f2614e3F486c853D8BA0eC5FFe811`.

- New orchestrator session payment budget: **0.00005 ETH**, derived from and
  bounded by the saved vendor maximum, current policy and existing automatic cap.
  This is a cumulative durable budget; restarting does not reset it.
- Existing global automatic payment cap remains **0.01 ETH**. Other existing
  policy/vendor limits still apply. The new workflow does not increase them.
- Session fee budget: **24,887,000,000,000,000 wei**, bounded by the original
  configured maximum gas × maximum fee. Each task reserves its smaller bounded
  preflight envelope, with limited headroom for gas/fee changes between reads.
  The existing signer still enforces the original outer gas bounds.
- Funding budget: **0**; faucet is disabled. Sufficient existing funds allow the
  funding step to skip with no synthetic credit.
- Actual observed balance: **0.0496699999983914 Sepolia ETH**.

Example real execution command, to use only when a transfer is intended:

```text
Fund my wallet if needed, then pay 0.00001 ETH to supplier Northstar Services and verify.
```

The exact decimal ETH amount is converted deterministically. Integer-wei goals
remain supported. The model receives only the canonical tool-planning prompt,
not this raw goal, addresses, keys, external documents or callable tools.

## Main integration details

The former agent-proposal endpoint can execute during policy evaluation when
legacy automatic execution is enabled. The durable adapter therefore creates an
existing **structured proposal**, which carries no legacy automatic-execution
intent. It attaches the existing saved-vendor draft/binding artifacts before
evaluation and only calls the unchanged sign endpoint after durable payment and
fee reservations and execution limits are in place. A targeted main-app test
specifically verifies that evaluation cannot sign before those reservations.

No signer, capability, policy-engine, audit, core/security, authorization or
execution module was edited for this change. Policy/version, vendor/version,
capability, nonce, emergency-stop and signer checks remain authoritative.

Main workflow settings default off and grant zero budget. Explicit activation
requires both `AUTONOMY_ENABLED` and `AUTONOMY_LIVE_ENABLED`, the pinned planner,
a configured recipient, positive session budgets and independent existing roles.
The simulation runner retains its original isolation guard.

Task state lives in `backend/autonomy-state/goals.sqlite3`; it is bound to the
original wallet address/database and refuses reuse with another wallet identity.
The directory is private and ignored by Git. No new wallet or API keys were
generated. The separate-wallet services from the previous setup remain stopped.

Quarantine pauses this new orchestrator. Legacy invoice/treasury/ordinary assistant
automation retains its existing settings and controls; this change does not make
the orchestrator's quarantine a replacement for the wallet's global emergency stop.
This distinction matters when presenting the system's security scope.

## Verification

- **50 focused backend checks passed:** 9 main integration/assistant checks and
  41 relevant Sepolia/workflow/isolation checks. Financial tests used test-owned
  databases and public fixture keys with network connections forbidden.
- **6 focused frontend checks passed.** Frontend type/build, frontend lint,
  new Python lint and whitespace checks passed. A hook-dependency warning found
  during verification was fixed; final frontend lint was clean.
- Fresh pinned local Gemma/Ollama planning succeeded.
- Real RPC read-only preflight succeeded with the existing wallet and gas settings.
- The authenticated main UI showed the original wallet, live balance, configured
  standing mandate and enabled Start task control. No task was submitted in the UI.
- Backend restart retained the standing mandate and wallet identity.
- Existing core audit integrity verified. All **19** historical transactions
  remained confirmed; **zero** new transactions were added.
- Full unrelated backend/frontend suites were not rerun, as requested.

These are regression checks, not a new statistical model evaluation. There are
no new confidence-interval or general reliability claims. One matching mined
receipt is not finality, and completed tasks are not continuously monitored for
later reorgs. Source changes remain in the current working tree, not a Git-main
merge or published deployment. The local services are detached processes rather
than an operating-system startup service.

Evidence:

- `backend/demo_autonomy/reports/main-orchestrator-enabled-2026-11-02.json`
- `backend/demo_autonomy/reports/main-orchestrator-preflight-2026-11-02.json`
- Isolated checks: `/var/folders/ky/xlzf2wp51f7gl7lp9_089_y80000gn/T/kiteshield-main-orchestrator-final-u9efms3r`
- Final fee-headroom/main checks: `/var/folders/ky/xlzf2wp51f7gl7lp9_089_y80000gn/T/kiteshield-main-fee-check-uk7debdl`

Private rollback copies of the pre-change configuration/database and process
ownership/logs are under `/Users/dhruv/.local/share/kiteshield/main-existing-20261102`.

![Enabled durable orchestrator using the existing wallet](ui-audit-3000/11-main-orchestrator-enabled-2026-11-02.png)
