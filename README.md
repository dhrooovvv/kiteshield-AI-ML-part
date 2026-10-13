# KiteShield Wallet

> **"Give the agent hands, not the keys."**

KiteShield Wallet is a constrained AI agent authorization system for blockchain transactions, built for the **2026 Shenzhen International FinTechathon — Topic F: Agent Wallet**.

## What It Does

An AI agent can **propose** blockchain transactions. A deterministic **policy engine** evaluates each proposal. A separate **signer** independently verifies authorization before signing. The system enforces clear boundaries between what the agent wants, what the policy allows, and what gets signed.

```
Agent Proposes → Policy Evaluates → Human Approves (if needed) → Token Authorizes → Signer Verifies → Transaction Submitted
```

## Key Security Principles

- **Model output is untrusted** — all agent proposals are validated and normalized
- **Policy decisions are deterministic** — same input + same policy = same decision
- **BLOCK never leads to signing** — blocked transactions cannot bypass policy
- **Tokens are transaction-bound** — changing any parameter invalidates authorization
- **Signer independently verifies** — does not trust the API's assertion
- **Single-use authorization** — replay attacks are prevented by token consumption
- **Private keys never leave the signer** — browser and LLM never see them

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy (Async), aiosqlite |
| Database | SQLite (WAL mode, async engine) |
| Blockchain | Ethereum Sepolia testnet (Chain ID 11155111), web3.py, eth_account |
| Agent Extraction | OpenAI GPT-4o (structured outputs) with deterministic regex fallback |
| Frontend | React 19, TypeScript (Strict Mode), Vite, Lucide React, Custom Dark CSS |
| Authorization Tokens | HS256 JWT, SHA-256 canonical action digests |
| Audit Logging | Cryptographic append-only hash chains (SHA-256) |

## Quick Start

### Prerequisites

- Python 3.12+ (Python 3.14 recommended)
- Node.js 20+
- Git

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # macOS/Linux

# Install backend dependencies
pip install -e ".[dev]"

# Configure local development environment
cp .env.example .env

# Generate fresh local secrets and print derived address
python -c "
import secrets
from eth_account import Account
print('CAPABILITY_TOKEN_SECRET=' + secrets.token_hex(32))
print('API_KEY=' + secrets.token_urlsafe(32))
acc = Account.create()
print('SIGNER_PRIVATE_KEY=' + acc.key.hex().removeprefix('0x'))
print('Signer Public Address: ' + acc.address)
"
# Paste these values into backend/.env (leave SEPOLIA_RPC_URL=https://mock-rpc.sepolia.org for local simulation)

# Seed initial active policy (v1) and demo historical proposals
python scripts/seed.py

# Run backend test suite (91 passing tests)
pytest

# Start backend API server
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Frontend Setup

In a new terminal:
```bash
cd frontend

# Install frontend dependencies
npm install

# Configure environment
cp .env.example .env
# Set VITE_API_KEY to match the API_KEY set in backend/.env

# Run linting and TypeScript check
npm run lint
npx tsc -b

# Start Vite development server
npm run dev -- --host 127.0.0.1 --port 3000
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Blockchain Execution Modes: Mock RPC vs. Live Sepolia

KiteShield provides two execution modes via `backend/app/services/blockchain.py`:

1. **Local Simulated Mode (`SEPOLIA_RPC_URL=https://mock-rpc.sepolia.org`)**:
   - Ideal for local development, rapid UI feedback, and automated CI tests.
   - The isolated signer re-verifies all parameters, checks token claims, consumes the single-use token atomically, and signs the raw EIP-155 transaction using the configured testnet private key.
   - Raw transaction submission produces a deterministic SHA-256 transaction hash (`0x...`), recorded as `network: "sepolia-mock"`. No testnet ETH is consumed.
2. **Live Ethereum Sepolia Mode (`SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/...`)**:
   - Submits pre-signed raw transaction bytes directly to the Ethereum Sepolia network (Chain ID `11155111`) via `w3.eth.send_raw_transaction`.
   - Requires testnet ETH in the signer wallet for gas fees.

---

## Project Structure

```
KiteShield/
├── backend/                  # FastAPI modular monolith backend
│   ├── app/
│   │   ├── api/routes/       # 16 REST endpoints (policies, proposals, approvals, txs, audit)
│   │   ├── core/             # Settings, logging, security, error handling
│   │   ├── db/               # Async SQLAlchemy engine & session factory
│   │   ├── models/           # DB models (Policy, Proposal, Approval, AuditEvent, etc.)
│   │   ├── schemas/          # Pydantic v2 validation & serialization models
│   │   └── services/         # Business logic (isolated signer, capability, policy engine, audit)
│   ├── scripts/seed.py       # DB initialization & baseline v1 seeding script
│   └── tests/                # 91 unit, integration, and security invariant tests
├── frontend/                 # React 19 + TypeScript + Vite dashboard
│   ├── src/
│   │   ├── api/client.ts     # Typed centralized API client with correlation tracking
│   │   ├── components/       # Header, Navigation, Badges, Modals, Proposal Cards
│   │   ├── views/            # Overview, Proposals, Approvals, Policies, Audit Explorer
│   │   └── types/            # TypeScript interfaces matching backend models
├── docs/                     # Architectural, security, and workflow documentation
│   ├── ARCHITECTURE.md       # Modular monolith architecture & trust boundaries
│   ├── API_CONTRACT.md       # Complete 16-endpoint API specifications & SI-1 to SI-12
│   ├── TEAM_WORKFLOW.md      # Collaboration standards, branch strategy, review gates
│   ├── WORK_BREAKDOWN.md     # 4 independent parallel workstreams
│   └── SECURITY.md           # Security threat model & invariant definitions
└── .github/                  # CI workflow, CODEOWNERS, and PR template
```

## Team Documentation

- [Team Workflow & Contribution Standards](docs/TEAM_WORKFLOW.md)
- [Work Breakdown & 4 Independent Workstreams](docs/WORK_BREAKDOWN.md)
- [API Contract & Module Boundaries](docs/API_CONTRACT.md)
- [Architecture & Trust Boundaries](docs/ARCHITECTURE.md)
- [Security Threat Model & Invariants](docs/SECURITY.md)

## Competition

**2026 Shenzhen International FinTechathon**
- Track: International
- Topic: F — Agent Wallet
- Deadline: October 20, 2026

## License

MIT
