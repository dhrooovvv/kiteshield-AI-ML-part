# KiteShield Wallet

KiteShield is a constrained wallet authorization prototype for the 2026 Shenzhen International FinTechathon, Topic F: Agent Wallet. It turns explicit payment instructions into policy-checked native ETH transfers on Ethereum Sepolia (chain **11155111**).

The agent proposes; deterministic policy authorizes; the signer revalidates before signing. Model output never grants permission to spend.

## Implemented scope

- Natural-language and structured native ETH payment proposals, with exact integer-wei amounts.
- Deterministic `ALLOW`, `ESCALATE`, or `BLOCK` decisions: recipient scope, per-payment maximum, approval threshold and daily principal budget.
- Separate proposer, human-approver, policy-administrator and emergency-stop credentials.
- Short-lived, single-use capabilities bound to the action and transaction envelope.
- Durable spending reservations, signed-transaction persistence, receipt reconciliation and recovery using the same signed bytes.
- Opt-in autonomous execution of eligible small payments within an additional cap.
- Dashboard for proposals, approvals, policy, audit history and read-only portfolio balances.
- Hash-linked audit events and Merkle checkpoints; simulation and live outcomes clearly distinguished.

Swaps, scheduling, rebalancing, ERC-20 spending, account abstraction and on-chain session-key enforcement are **not implemented execution features**. Reading an ERC-20 balance does not authorize spending it.

## Architecture

```text
React / TypeScript dashboard
       │ authenticated API requests
       ▼
FastAPI: input validation → screening → action extraction
       │
       ▼
Deterministic policy → approval when required
       │
       ▼
Execution coordinator → capability → signer revalidation
       │ reserve budget; persist signed bytes before broadcast
       ▼
Sepolia RPC → receipt reconciliation → dashboard evidence

SQLite / SQLAlchemy: policies, proposals, approvals, reservations,
execution attempts, transactions, capabilities and audit events
```

This is a **modular monolith**. The signer is logically separated within the backend, not isolated in a separate process, HSM or smart account. The browser and language model do not receive the signing key; compromise of the backend host remains a custody risk.

| Layer | Implementation |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, async SQLAlchemy |
| Storage | SQLite / aiosqlite, WAL mode |
| Blockchain | web3.py / eth_account; Sepolia only |
| Frontend | React 19, TypeScript, Vite, Lucide React, custom CSS |
| Extraction | Deterministic parser; optional OpenAI structured extraction |
| Screening | Rules; optional Horizon and Bastion classifiers |
| Authorization | HS256 JWT capabilities, canonical action/envelope bindings, atomic single use |
| Audit | SHA-256 event chain and database-held Merkle checkpoints |

## Model behavior

Without `OPENAI_API_KEY`, payment extraction is deterministic. With a key configured, `OPENAI_MODEL` selects the structured-output model (default `gpt-4o`); its extracted recipient and amount must match the deterministic parser. A configured model failure rejects the request rather than silently falling back.

`LEARNED_SCREENING_ENABLED=false` is the default and uses rule-based prompt screening. Enabling it requires the configured Horizon and Bastion model dependencies/cache. Rules can block directly; both learned positives block; learned disagreement produces security `REVIEW`; all-negative screening permits further validation. Required detector failure stops processing. A screening review is not an executable proposal or financial approval.

Offline evaluation strategies differ from this live aggregation logic. See [the public evaluation report](backend/reports/horizon_bastion_public_final.md) for dataset, thresholds and limitations. Benchmark metrics do not establish real-world wallet safety.

## Local setup: simulation first

### Prerequisites

- Python 3.12+ and a virtual environment. Optional learned-model packages may impose additional platform requirements.
- Node.js **22.12+** (the Vite 8 toolchain requires a supported modern Node runtime).
- A local clone of this repository.

Run backend commands from `backend/` so relative database and environment paths resolve correctly. If you already have a configured checkout, **keep its `.env` and database**; do not replace them with examples or regenerate working credentials.

### Backend

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

For a **fresh checkout only**, this creates `backend/.env` with independent random credentials and a fresh test-only signing key. It refuses to overwrite an existing file and does not print secrets:

```sh
python - <<'PY'
import os
import secrets
from pathlib import Path
from eth_account import Account

text = Path('.env.example').read_text()
values = {
    'CAPABILITY_TOKEN_SECRET': secrets.token_hex(32),
    'API_KEY': secrets.token_urlsafe(32),
    'APPROVER_API_KEY': secrets.token_urlsafe(32),
    'POLICY_ADMIN_API_KEY': secrets.token_urlsafe(32),
    'EMERGENCY_STOP_ADMIN_API_KEY': secrets.token_urlsafe(32),
    'SIGNER_PRIVATE_KEY': Account.create().key.hex().removeprefix('0x'),
    'APP_DEBUG': 'false',
}
lines = [f'{line.split("=", 1)[0]}={values[line.split("=", 1)[0]]}'
         if '=' in line and line.split('=', 1)[0] in values else line
         for line in text.splitlines()]
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write('\n'.join(lines) + '\n')
print('Created private local configuration in simulation mode.')
PY

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The example defaults to `EXECUTION_MODE=simulated`, `AUTO_EXECUTE_ENABLED=false`, no OpenAI key and rules-only screening. Simulation performs the constrained test-signing flow but does not broadcast to Ethereum. Its hashes are not evidence of on-chain execution.

On a new database, connect the policy-administrator role in the dashboard and create the initial policy with recipients and bounds you intend to use. Existing installations keep their active policy. **Do not run `scripts/seed.py` against a live database**: it inserts sample historical records and a baseline policy; those sample hashes are not real payment evidence.

### Frontend

In another terminal, from the repository root:

```sh
cd frontend
npm ci
# Fresh checkout only; preserve an existing .env:
cp -n .env.example .env
npm run dev -- --host 127.0.0.1 --port 3000
```

Open [http://localhost:3000](http://localhost:3000). Use **API key / Switch role** to connect the appropriate role credential from your private backend configuration. Credentials stay in dashboard memory until reload. Multiple roles can be connected.

Never put credentials in `VITE_*` variables, browser persistent storage, screenshots or prompts. `VITE_API_BASE_URL=/api/v1` is public routing configuration, not a secret. Vite proxies `/api` to port 8000 in development; a deployed frontend needs its own API routing configuration.

For an isolated simulation profile with a combined demo role, see [Demo administrator setup](docs/DEMO_ADMIN.md). That role is rejected outside the guarded demo profile and never grants emergency-stop authority.

## Configuration and live Sepolia

**The RPC URL alone does not select execution mode.** Settings are cached at startup; restart the existing backend after deliberate configuration changes. Do not run two backend processes against the same local execution setup.

| Variable | Meaning / default |
|---|---|
| `EXECUTION_MODE` | `simulated` by default; `sepolia` enables the live execution path |
| `SEPOLIA_RPC_URL` | Mock placeholder permitted for simulation; live requires a real HTTPS Sepolia RPC |
| `CHAIN_ID` | Must be `11155111` |
| `SIGNER_PRIVATE_KEY` | Dedicated test-only wallet key; backend only |
| `AUTO_EXECUTE_ENABLED` | `false` by default; opt-in standing permission for eligible unattended payments |
| `AUTO_EXECUTE_MAX_ETH` | Additional automation ceiling, default `0.0001` ETH |
| `MAX_GAS_UNITS` | Gas-unit cap, default `100000`; fresh recipient funding may exceed it |
| `MAX_FEE_PER_GAS_WEI` | Maximum permitted fee per gas |
| `MAX_PRIORITY_FEE_PER_GAS_WEI` | Maximum permitted priority fee per gas |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Optional extraction model configuration |
| `LEARNED_SCREENING_ENABLED` | Optional learned detectors, default `false` |
| `WATCHED_ADDRESSES` / `TOKEN_ALLOWLIST` | Explicit read-only portfolio configuration |

Live startup rejects non-HTTPS, placeholder, mock and local/private RPC hosts. It calls `eth_chainId` and requires **11155111**, then requires a successful `eth_blockNumber`. Failure prevents startup. The dashboard shows `Sepolia · chain 11155111 · block N` using the verified startup snapshot, not a continuously refreshed network head.

There is no separate live-mode confirmation flag. Choosing live mode makes authorized execution capable of broadcasting; enabling automation additionally allows eligible Propose/evaluate flows to execute without a separate manual sign click. Treat both configuration changes deliberately. Live mode rejects mock RPC startup and cannot use the simulation submission path as live evidence.

Before a live payment, verify the derived sender, funding, explicitly allowlisted recipient, active policy, pending nonce, gas estimate, fee limits and maximum cost. Fetch these from the chain at preparation/signing time; previews do not reserve nonces. Get explicit authorization before signing or broadcasting. See [the payment workflow](docs/SEPOLIA_PAYMENT_DEMO.md) and [autonomous eligibility/recovery](docs/AUTONOMOUS_PAYMENTS.md).

## Authorization and recovery semantics

- `BLOCK` overrides escalation and allowance. Approval cannot authorize a blocked action.
- Signing rechecks the current policy version, persisted action, decision and any required unexpired approval.
- Daily accounting includes committed principal for the current UTC day and **all outstanding reservations**, including earlier days. Gas is excluded from that principal budget and bounded separately.
- Signed bytes, transaction identity and capability consumption persist before broadcast. Retry recovery reconciles or resends the same signed transaction rather than issuing a fresh payment.
- Pending/uncertain execution retains its reservation. A reverted execution releases principal.
- Autonomous execution requires verified live Sepolia, benign action-bound screening provenance, explicit recipient scope and an amount within the automation cap and strictly below the approval threshold. Only one outstanding signed/submitted execution is allowed through that orchestrator; waiting proposals need reevaluation.
- No automatic fee bumping, background restart recovery worker or reorg monitor is implemented.
- `ALLOW`, submitted, uncertain, confirmed, reverted and simulated are different outcomes. A matching mined receipt is confirmation here, **not finality**.

## Verification

From `backend/`, with the development environment activated:

```sh
pytest
ruff check app tests
python -m compileall -q app
```

From `frontend/`:

```sh
npm test
npm run lint
npm run build
```

Tests use isolated databases and test fixtures/fake RPC; passing them does not demonstrate live network completion. Avoid fixed test-count claims in setup instructions: counts change as coverage grows. Prior run totals and their scope are recorded in individual implementation handoffs.

## Evidence and presentation

The October 18 source/evidence review found five local Sepolia transaction records marked confirmed. This is a dated observation, not a current chain query or finality guarantee. Example:

- [First payment on Sepolia Etherscan](https://sepolia.etherscan.io/tx/0x02437c8d60cfc3ecd3eab9406437ce948b3474a58a3e833d7483d1bcefd8faaa)
- [Exported first receipt and audit references](docs/evidence/sepolia-payment1-02437c8d60cfc3ec.json)
- [First-payment report](docs/PAYMENT1_CONFIRMATION_2026-10-18.md) — historical snapshot; later payments supersede its then-pending second-payment status.
- [10-minute presentation brief](docs/presentation/KITESHIELD_10_MINUTE_BRIEF.html) — architecture, model-mode snapshot, policy evolution, benchmark caveats and speaker notes.

Application roles and JWT capabilities are **not on-chain session keys**. Competition acceptance of Sepolia evidence and any challenge-bonus award must be confirmed with the organizers.

## Security limits

This is a testnet prototype, not production custody or a compliance certification. Signer and capability secrets share the backend host. Audit events and Merkle checkpoints share the database; without an independently protected root, a privileged attacker can rewrite and recompute history. SQLite serialization is not proof of distributed scalability. Use a dedicated test-only wallet and never fund it with real assets.

## Repository guide

```text
backend/app/api/routes/    API endpoints, role checks and orchestration
backend/app/core/          Settings, authentication and live RPC startup guard
backend/app/services/      Policy, extraction, authorization, execution, signer, audit
backend/app/ai_ml/         Screening integrations and experimental decision strategies
backend/app/models/        Durable policy, approval and execution records
backend/scripts/           Preview, evidence export and development utilities
backend/tests/             Unit, integration and security regression tests
frontend/src/              React dashboard, API client and runtime credential handling
frontend/tests/            Frontend behavior tests
backend/reports/           Offline evaluation reports
docs/                     Technical handoffs, evidence and presentation material
```

Further reading: [autonomous payments](docs/AUTONOMOUS_PAYMENTS.md), [portfolio semantics](docs/PORTFOLIO.md), [screening-counter behavior](docs/SCREENING_COUNTER_FIX_2026-10-18.md), [team workflow](docs/TEAM_WORKFLOW.md). Older architecture/API planning documents are background material; use current code and focused implementation handoffs for exact behavior.

## Treasury Autopilot

The **Treasury Autopilot** tab monitors an explicit, versioned Sepolia sweep mandate.
It is off by default and first activates in **plan-only** mode. Execute activation
requires a separate administrator confirmation plus the existing global live
automation configuration. It adds restrictions to the existing policy → capability
→ logical signer → broadcast → receipt coordinator; it does not replace that path.

GET/Refresh only reads saved status. One-off observations are explicit plan-only
POSTs. Durable SQLite claims, outstanding-intent blocking, UTC action limits and
cooldown survive restart and mandate edits. Disabling blocks fresh signing, not
already-signed transaction recovery.

See [Treasury setup, API, safety boundaries and demo](docs/TREASURY_AUTOPILOT.md).
No live mandate has been activated or Treasury payment broadcast during development.

## Competition and license

2026 Shenzhen International FinTechathon · International Track · Topic F: Agent Wallet. The stated deadline is October 20, 2026; confirm submission timing and requirements against the official rules.

Package metadata declares MIT licensing. Review third-party model, dataset and dependency licenses separately before redistribution.
