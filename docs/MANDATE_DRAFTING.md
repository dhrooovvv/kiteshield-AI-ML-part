# Treasury mandate drafting

Branch: `codex/treasury-mandate-drafting`. Draft-only: no saving, activation, observation, executable proposal, capability, signing or broadcast. Existing mandate saving and separate execute confirmation remain unchanged.

## Workflow

An authenticated policy administrator opens Treasury → Configure mandate → Draft from instructions. Generate draft interprets text; **Apply draft to form** only updates editable inputs. Any unspecified sweep/cooldown/freshness limits are cleared and shown as questions rather than silently inherited from defaults. The operator reviews and uses the existing Save flow separately. No mandate was saved or enabled during verification.

Example canonical grammar:

```text
Keep 0.04 ETH available, move excess to my saved treasury address, and make no more than three transfers daily.
```

Optional canonical clauses:

```text
maximum sweep 0.00003 ETH, minimum excess 0.00002 ETH, cooldown 600 seconds, freshness 60 seconds
```

The parser accepts clauses separated by commas, semicolons or newlines; integers or one–five for the daily count; plain positive decimal ETH with up to 18 decimal places. English ASCII only. Missing core fields cause clarification. Raw addresses, recipient substitution, authority changes, other assets/strategies and recognized instruction attacks are refused. Unknown phrasing asks for clarification rather than guessing. Approximate/ranged amounts require clarification. These are bounded grammar/heuristic protections, not universal prompt-injection detection.

## API

`POST /api/v1/treasury/draft`

Existing policy-administrator authentication (and the existing isolated-demo administrator exception); other roles cannot draft. Request has only `instruction` (1–2000 characters); extra fields are rejected.

Response uses the normal API envelope. Data contains status (`draft`, `clarification`, `refused`, `invalid`, `could_not_interpret`), draft values, resolved recipient, source, policy version, validation errors, questions and warnings. Nullable fields mean unresolved, not implicit defaults. Invalid results provide no applicable draft.

The endpoint reads the active policy, excludes blocked recipients, derives the configured sender offline and validates aliases/numbers. It makes no RPC calls and performs no database writes. A draft is a snapshot, not proof that an action will later be authorized; existing saving/execution checks remain authoritative.

### Requested audit versus no-write requirement

The brief asks both for no DB writes and for auditing requests, while forbidding audit-code changes. This implementation prioritizes no writes: a metadata-only application log records `MANDATE_DRAFT_REQUESTED` and the verified role. No instruction, key, model output or address is logged by this feature. This is **not a durable hash-chain audit event**. Existing audit code was not modified.

## Configuration

Added to Settings and `.env.example`; no live `.env` was changed:

```dotenv
DRAFTER_LLM_ENABLED=false
DRAFTER_LLM_ENDPOINT=http://127.0.0.1:11434/v1/chat/completions
DRAFTER_LLM_MODEL=local
DRAFTER_LLM_TIMEOUT_SECONDS=5
DRAFTER_RECIPIENT_ALIASES={}
```

Aliases are deployment-administrator-configured lowercase names mapped to public addresses. They are not accepted from a request. Example **for an isolated demo configuration only**:

```dotenv
DRAFTER_RECIPIENT_ALIASES={"treasury":"0x229D5588641f2614e3F486c853D8BA0eC5FFe811"}
```

The address must also be explicitly allowed and not blocked in the current policy, differ from the sender and be nonzero. The sweep maximum must fit both the global automation cap and policy max and stay strictly below an explicit approval threshold. No silent clamping. Missing fields cannot authorize an action.

The optional LLM supports a loopback OpenAI-compatible chat-completions endpoint with strict JSON-schema output; external URLs, credentials, query strings and redirects are rejected. HTTP proxy inheritance is disabled. It receives only fixed extraction instructions, the administrator's text and schema with configured alias names—no keys, resolved addresses, policy/database context or tools. Requests containing configured secrets or raw addresses are rejected before model access.

Canonical instructions always use the parser first, even when LLM mode is on. Otherwise validated model output must have exact allowed keys/types and explicit instruction-grounded numbers/alias. Canonical parsed fields cannot be replaced. Optional numeric limits require canonical clauses; omitted limits remain questions. Model failure or invalid output returns could-not-interpret. No supported local model is installed or enabled by this change.

## Isolation and demonstration

Use the existing isolated demo profile only, not the live `.env`, database or port 8000 backend. Keep `APP_ENV=demo`, `EXECUTION_MODE=simulated`, `AUTO_EXECUTE_ENABLED=false`, `TREASURY_MONITOR_ENABLED=false`, public test signer fixture and the guarded separate `kiteshield-demo.db`. Add aliases in that demo profile only. Never copy the funded key into the demo.

From backend/:

```sh
./.venv/bin/uvicorn app.main:app --env-file .env.demo --host 127.0.0.1 --port 8001
```

From frontend/ in another terminal:

```sh
VITE_API_BASE_URL=http://127.0.0.1:8001/api/v1 npm run dev -- --host 127.0.0.1 --port 3001 --strictPort
```

Use only synthetic/demo administrator credentials and its separate policy. Do not save or activate a mandate for this draft demonstration. Show the returned values and questions, apply them to the form and stop there.

Task verification used a **new temporary directory** and isolated demo SQLite database, no existing `.env.demo` or live data. Port 8001/3001 processes were started only after checking the ports were free, and stopped after testing. Policy setup used that synthetic database only. No mandate, payment or execution was created. Desktop/narrow-window UI checks verified drafting/applying, blank unresolved limits and unchanged saved state. No real model inference was demonstrated.

## Evaluation and tests

Dataset: `backend/evaluation/mandate_drafting_v1.jsonl`, 70 distinct instructions, frozen in Git before evaluation (`ff93045`; initial corpus `fe2fb7f`). Six categories: clean 15, paraphrases 15, ambiguous 10, unsupported 10, malicious 15, formatting/non-English 5.

Run from backend/:

```sh
PYTHONPATH=. ./.venv/bin/python scripts/evaluate_mandate_drafter.py
./.venv/bin/pytest -q
```

The evaluator loads no application environment, DB, RPC or signer. It uses public fixture addresses as internal alias context; those addresses are not sent to a model. Only an explicitly configured loopback model endpoint may be contacted for the optional comparison. Default report: `backend/reports/mandate_drafting_v1.json`.

The report gives per-category exact core-field accuracy, clarification/refusal rates, false accepts, latency and 95% confidence intervals (Wilson for proportions; seeded bootstrap for mean latency). Exact accuracy denominators contain intended-draft cases; clarification/refusal denominators contain their expected cases. N/A denominators are explicit. The corpus is curated development evidence, not a broad held-out security benchmark. Implementation development used its visible categories; no generalization claim.

Observed: clean 15/15 exact, paraphrases 0/15 (clarification), ambiguous 10/10 clarification, unsupported 10/10 refusal, malicious 15/15 refusal and **0/15 malicious false accepts**. Formatting: 2/2 intended drafts exact; 3/3 unsupported-language/format refusals. A 0/15 observed false-accept rate has a Wilson 95% upper bound of about 20.4%; it does not establish zero real-world false accepts.

**LLM-assisted benchmark not run:** no local compatible model server was available. The feature's JSON contract, timeout, invalid output, numeric invention, unknown alias and fallback behavior were exercised with mocked model responses. No claim that LLM assistance improves accuracy or latency is supported yet.

Final validation: backend **447 passed, 14 skipped**; frontend **51 passed**; targeted Ruff, compilation, frontend lint and TypeScript/Vite build pass. Frontend test tooling emitted existing Vite HMR port-24678 contention warnings; all tests passed. Those warnings are not presented as a clean zero-warning run.

## Files changed by this task

New:
- `backend/app/schemas/mandate_draft.py`
- `backend/app/services/mandate_drafter.py`
- `backend/app/api/routes/mandate_draft.py`
- `backend/tests/integration/test_mandate_draft.py`
- `backend/evaluation/mandate_drafting_v1.jsonl`
- `backend/scripts/evaluate_mandate_drafter.py`
- `backend/reports/mandate_drafting_v1.json` and `.md`
- `frontend/src/mandateDraft.ts`
- `frontend/src/components/MandateDraftBox.tsx`
- `frontend/tests/mandateDraft.test.ts`
- This document.

Integration edits only:
- `backend/app/core/config.py`: drafter configuration and alias-shape validation.
- `backend/.env.example`: safe drafter examples.
- `backend/app/main.py`: route registration.
- `frontend/src/api/client.ts`: administrator-authenticated draft request.
- `frontend/src/views/TreasuryView.tsx`: draft control and form ref; existing save/mode logic retained.
- `frontend/src/index.css`: scoped draft-panel styles.

Existing Autopilot work and previously dirty protected files were preserved. This task did not edit signer, capability, policy_engine, audit, core/security, authorization or execution code. Only the frozen evaluation set has been committed; implementation remains local/uncommitted. Nothing pushed.
