# KiteShield Wallet — Team Collaboration & Engineering Workflow

This guide establishes the engineering standards, security gates, branch workflow, and review procedures for team members collaborating on the KiteShield Wallet repository.

---

## 1. Guiding Engineering Philosophy

KiteShield Wallet is a security-first system operating under the principle:
> **"Give the agent hands, not the keys."**

Because the software authorizes blockchain transactions on behalf of autonomous agents, **security invariants take precedence over feature velocity**.

---

## 2. Protected Security-Critical Modules

The following core modules define the trust boundaries and cryptographic invariants of KiteShield. Any modification to these modules **strictly requires designated security review**:

| File / Module | Responsibility | Why It Is Protected |
| :--- | :--- | :--- |
| `backend/app/services/signer.py` | Isolated Signer & Gatekeeper | Houses private signing key; enforces 9-check verification gate and atomic single-use token consumption (`SI-6`, `SI-9`, `SI-10`). |
| `backend/app/services/capability.py` | Capability Token Minting | Mints HS256 JWT tokens bound to canonical action SHA-256 digests (`SI-7`). |
| `backend/app/services/policy_engine.py` | Deterministic Evaluator | Evaluates proposals against limits, address whitelists/blacklists, and daily caps (`SI-3`, `SI-4`). |
| `backend/app/services/audit.py` | Append-Only Audit Logger | Maintains cryptographic SHA-256 hash chains across all state transitions (`SI-11`). |
| `backend/app/core/security.py` | API Key & Secret Validation | Enforces API authentication, constant-time comparisons, and correlation ID tracking. |

### Protection Rules for Protected Modules:
1. **Never alter security invariants** (`SI-1` through `SI-12`) without an approved Architecture Decision Record in `docs/DECISIONS/`.
2. **Never weaken fail-closed defaults** (`SI-12`). Any ambiguous state must throw a domain exception rather than proceeding with execution.
3. **No client-side enforcement assumptions**: Frontend validation is for UI convenience only. Backend security checks must remain 100% authoritative.
4. **Mandatory Test Coverage**: Any change to these files must include corresponding test cases under `backend/tests/security/` or `backend/tests/unit/`.

---

## 3. Branching Strategy

We follow a GitHub-flow branch model with clean topic branches:

- **`main`**: Production-ready branch. Must always pass all backend tests (91+), linting, and frontend production builds.
- **`feat/<short-title>`**: New features or capabilities (e.g. `feat/erc20-support`, `feat/tx-receipt-polling`).
- **`fix/<short-title>`**: Bug fixes (e.g. `fix/checksum-normalization`).
- **`sec/<short-title>`**: Security enhancements, hardening, or invariant tests.
- **`docs/<short-title>`**: Documentation and specification updates.

---

## 4. Git Hygiene & Secret Management

### Strict Rules on Secrets:
- **NEVER** commit `.env`, `.env.local`, or any file containing private keys, API secrets, or passwords.
- Both root `.gitignore`, `backend/.gitignore`, and `frontend/.gitignore` ignore all `.env*` files (except `.env.example`).
- If you accidentally stage a secret, **STOP IMMEDIATELY**. Do not push. Unstage using `git restore --staged <file>` or rotate the secret immediately if exposed.
- Use `.env.example` templates to document new environment variables. Never put real credentials in `.env.example`.

---

## 5. Local Setup for New Teammates

### Step 1: Clone Repository
```bash
git clone <repo-url> KiteShield
cd KiteShield
```

### Step 2: Configure Environment Files
```bash
# Backend setup
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Generate fresh local secrets
python -c "
import secrets
from eth_account import Account
print('Generated Local Secrets:')
print('CAPABILITY_TOKEN_SECRET=' + secrets.token_hex(32))
print('API_KEY=' + secrets.token_urlsafe(32))
acc = Account.create()
print('SIGNER_PRIVATE_KEY=' + acc.key.hex().removeprefix('0x'))
print('Derived Signer Address: ' + acc.address)
"
# Paste the generated values into backend/.env
```

```bash
# Frontend setup
cd ../frontend
npm install
cp .env.example .env
# Set VITE_API_KEY in frontend/.env to match API_KEY from backend/.env
```

### Step 3: Initialize Database & Seed
```bash
cd ../backend
source .venv/bin/activate
python scripts/seed.py
```

### Step 4: Run Dev Servers
```bash
# Terminal 1: Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev -- --host 127.0.0.1 --port 3000
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 6. Pre-Commit Verification Checklist

Before opening a pull request, run and confirm all checks pass locally:

```bash
# 1. Backend verification
cd backend
source .venv/bin/activate
pytest                # Must pass 91/91 tests
ruff check .          # Must report 0 errors

# 2. Frontend verification
cd ../frontend
npm run lint          # oxlint must report 0 errors
npx tsc -b            # TypeScript strict mode must pass with 0 errors
npm run build         # Production Vite build must succeed
```

---

## 7. Pull Request Standards

Every PR must use the pull request template (`.github/pull_request_template.md`) and confirm:
1. Workstream tag (Backend / Frontend / Security / Blockchain).
2. Explicit statement on whether security-critical files were modified.
3. Confirmation that no secrets or `.env` files are included.
4. Test output and build logs attached.
