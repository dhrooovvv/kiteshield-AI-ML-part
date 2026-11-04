# KiteShield autonomous workflows — implementation handoff

1 November 2026. Supersedes the Gate 1 report's outstanding Gemma and wallet-adapter
items. This remains an **isolated simulation**, not live autonomous operation.

## Delivered and demonstrated

### Goal execution and workflow rules

The local `kiteshield-gemma4:12b-q4km` model proposes the fixed typed sequence
`balance → fund → payment → receipt`. Deterministic code binds the saved supplier,
amount and administrator mandate and decides whether each step may run. Gemma
receives no addresses, credentials, tools, documents or original untrusted goal.
Its request uses JSON schema, temperature 0, a timeout, disabled thinking, bounded
output and exact model/runtime pins. Invalid/incomplete/tool-calling output or
unavailable inference requires a human. The plan deliberately supports one bounded
workflow; this is not a general-purpose planner or arbitrary natural-language agent.

The new adapter calls the **existing** faucet, proposal, deterministic policy,
approval, capability, signer and execution services through an in-process isolated
API. No alternative wallet/signing library or signature implementation was added.
The existing signer signs only with its public test fixture key in simulated mode.

- Low balance claims a bounded funding allocation, uses the existing configured
  faucet adapter, checks its saved result, and continues. Sufficient balance skips
  the funding call. A durable claim and the existing adapter's request limits
  prevent repeated funding. No alternate endpoint is available.
- Funding mode is **simulated**: its result is checked as SIMULATED, not an actual
  chain receipt. The demonstration ledger credits a bounded synthetic allocation;
  this is not a claim that a real faucet delivered that quantity. Gas and actual
  wallet balances are outside this simulation ledger's accounting.
- Policy escalation creates the existing approval record and a persisted waiting
  task. The task timeline notifies the operator; unrelated tasks continue. The
  worker can only observe approval, never approve itself. A separate human-role
  endpoint forwards a human decision to the existing approval service. Approval
  resumes processing automatically; rejection closes the task with a reason.
- Blocks, unavailable services, stale mandates and other exceptions are persisted
  in an inbox with reason codes. Unknown outcomes retain claims. Recovery finds
  the same proposal and signed attempt instead of issuing a new payment.
- A durable payment barrier blocks other payments while an attempt is reserved or
  uncertain. Planning, balances and unrelated non-payment work can continue.
- Task limits may only decrease through the agent endpoint. Only administrator
  credentials can change mandates. The main services independently enforce their
  own policy and daily spending bounds.

Supported instruction forms include:

> Fund my wallet if needed, then pay 10 wei to supplier Acme and verify.

and `fund if needed, pay supplier Acme 10 wei, verify`. Unsupported or ambiguous
wording is refused, not guessed. Saved recipient resolution stays in code.

### Self-quarantine

Behind a separate flag, flagged injection, repeated blocks, a simulation-ledger
balance mismatch, a failed existing audit-chain check, a proposal-binding anomaly
or incoming permission-like event pauses autonomous execution and records an issue.
Only an administrator can resume. The decision persists in SQLite across engine
recreation. Ordinary incoming events are data only. No event grants permissions.

The current external-event API accepts only typed event kinds. Actual token/NFT
chain subscriptions and document/voice trigger ingestion are not implemented.
Text detection is a narrow rule screen plus exact goal validation, not a claim of
comprehensive prompt-injection detection. Audit checks use the existing verifier
with a bounded limit, not an independent proof against full backend compromise.
Already accepted/in-flight work cannot be retroactively cancelled by quarantine;
its outcome remains recorded. Ambiguous execution is held for reconciliation.

### Console

Separate frontend on **3001**, backend on **8001**. The console shows task steps,
persisted event history, exceptions and human approval controls. Credentials stay
in page memory and are never put into browser storage or sent to Gemma. It uses a
fixed same-origin proxy to 8001, restrictive content policy and text-only rendering
of dynamic values. No external frontend dependency or font was added.

This console is independent of the main dashboard. It was visually inspected in
its disconnected state; API flows were exercised end to end. This is not a claim
of complete browser interaction/accessibility test coverage.

## Verification and evidence

- **34 autonomy tests passed**: plans, flags, role separation, only-tightening,
  restart persistence, idempotency, failures, approval waits, unrelated progress,
  quarantine, anomalies and the uncertain-payment barrier.
- Existing backend: **647 passed, 14 skipped**.
- Existing frontend: **79 passed**; lint and production build passed.
- New Python Ruff check, compilation, standalone JavaScript syntax check and diff
  whitespace checks passed. Existing suites ran from disposable profiles without
  wallet `.env` files, with a guarded network; frontend builds used a disposable
  copy without `.env` files. No live service was tested.
- Real local Gemma was used in a fresh-profile workflow evaluation. Dataset frozen
  at commit **67e3de9** before evaluation. **12/12 selected scenarios passed**;
  two-sided Wilson 95% interval **[0.7575, 1.0000]**. This intentionally selected
  synthetic set is not a general model accuracy/security estimate. Human approval
  and rejection were separate test-harness actions using the human role.
- The fresh wallet-services database contains **one simulated faucet request and
  four simulated transactions**; rejection produced no transaction. A small task
  completed while another waited for approval.
- The demo backend was stopped and resumed using the same temporary profile:
  four completed and one rejected task were preserved, with transaction count
  still four. An initial manual assertion mistakenly expected the evaluation to
  leave quarantine active; its harness had already reset quarantine between cases.
  Subsequent explicit checks verified that an NFT permission-like event quarantines,
  agent resumption is forbidden, and administrator resumption succeeds.
- Persisted evaluation, exact source hashes and supplemental checks:
  `backend/demo_autonomy/reports/workflow-evaluation-2026-11-01.json`.

## Safety and scope boundaries

The historical evidence tag and branch from Gate 1 are retained. Existing dirty
work was preserved. No source edits were made to signer, capability, policy_engine,
audit, core/security, authorization or execution. Live `.env`, database, funded
key and running live backend were not accessed or changed.

The sandbox must start before any main-app import. It clears inherited secrets,
changes only its own process to a private temporary profile, disables `.env`
loading in memory, uses separate databases and fixture credentials, rejects live
mode, and denies the blockchain service's network RPC access. It has no live-mode
flag. The raw simulated signatures/hashes in the core database are not on-chain
execution evidence. Only our own 8001 demo process was restarted during testing.

All feature flags default **off**. Previously persisted quarantine is not authority
that the agent can clear by changing its instruction. Resuming does not widen a
budget or grant a recipient permission.

## Model and dependency decisions

- Ollama **0.40.8**, existing installation; MIT upstream license:
  https://github.com/ollama/ollama/blob/v0.40.8/LICENSE
- Existing local Gemma selector: `kiteshield-gemma4:12b-q4km`.
  Exact digest: `13478e018db994bfea035644c1774abc573381ee0ff7e11ad59f3fbc89fd1519`.
  No model download or hosted model request occurred. Google's Gemma 4 license
  page identifies Apache-2.0: https://ai.google.dev/gemma/apache_2 . The specific
  locally imported GGUF has no embedded license returned by Ollama; its upstream
  quantization provenance is not independently established here. No weights are
  redistributed in this change.
- AgentKit and MetaMask Smart Accounts Kit remain unadopted: their wallet/signing
  paths do not solve the workflow-state problem and must not replace this signer.
- No new Python/Node dependency was installed for the workflow or console.
- Foundry v1.3.1 was evaluated and used only for the separate spike. Official
  binary archive hash, licenses, compiler pin and test evidence are recorded in
  `spikes/guarded-vault/DESIGN.md`. No install scripts ran.

## Separate enforcement spike and optional voice

The guarded-vault spike passed **9 local Foundry tests**, including 256 fuzz cases.
It uses distinct owner/agent test identities, receiver pinning, session/per-payment
caps, expiry, nonces/epochs, tightening and owner-only resumption. It targets chain
11155111 but is **not deployed to Sepolia** and is not integrated into KiteShield.

Integration is a **NO-GO under the current protected-code restriction**: contract
calldata and vault/session authority would need explicit bindings in protected
signer/capability/policy/authorization/execution surfaces. That design note is the
requested spike result; no such change was attempted. A live deployment would also
need separately funded keys and independent review.

Optional whisper.cpp voice remains unimplemented. No additional wallet capabilities,
networks, swaps, x402 purchasing or token/NFT authority were silently introduced.

## Run or inspect the demo

The current console is http://127.0.0.1:3001 and API is http://127.0.0.1:8001.
Private demo role tokens and databases are in:
`/private/var/folders/ky/xlzf2wp51f7gl7lp9_089_y80000gn/T/kiteshield-gate1-demo-kough7ih`.
Use `demo-credentials.json` only for these demo role fields. Do not paste tokens
into the goal. The profile has the approved synthetic Acme recipient, budgets of
1000 wei, and human approval threshold 50 wei. It was resumed by the administrator
after the explicit quarantine test so new permitted demo tasks can run.

From `backend`, launch a fresh profile explicitly:

```sh
.venv/bin/python -u -m demo_autonomy.run --enable --gemma --workflows --quarantine \
  --wallet-services --model kiteshield-gemma4:12b-q4km \
  --model-digest 13478e018db994bfea035644c1774abc573381ee0ff7e11ad59f3fbc89fd1519 \
  --ollama-version 0.40.8
```

Add `--resume <the-previous-temp-profile>` to recover that profile. Repeat explicit
flags and pins on restart. Start the console separately with
`.venv/bin/python -m demo_autonomy.ui` from `backend`. Both commands refuse occupied
ports naturally; do not stop unrelated listeners. Configure a fresh mandate using
the administrator role before issuing a goal. Approver credentials are separate
from both agent and administrator credentials.

Regression harness: `.venv/bin/python -m demo_autonomy.verify`.
Frozen evaluation: `.venv/bin/python -m demo_autonomy.evaluate <fresh-demo-profile>`.
The evaluation harness configures its synthetic mandate using the administrator
role and records approval/rejection using the human role; it is a test procedure,
not an agent self-approval feature.
