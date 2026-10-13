# KiteShield Wallet — Work Breakdown & Independent Workstreams

This document defines 4 distinct, parallel workstreams designed for team members to work on independently without blocking each other or causing merge conflicts.

---

## Overview of Workstreams

```
┌────────────────────────────────────────────────────────────────────────┐
│                        KiteShield Core Platform                        │
├────────────────────┬────────────────────┬───────────────┬──────────────┤
│    Workstream 1    │    Workstream 2    │ Workstream 3  │ Workstream 4 │
│      Backend       │      Frontend      │   Security    │  Blockchain  │
│  & Policy Engine   │     Dashboard      │   & Testing   │   & Demo     │
└────────────────────┴────────────────────┴───────────────┴──────────────┘
```

---

## Workstream 1: Backend & Policy Engine Expansion

**Objective**: Broaden the policy engine's analytical capabilities, asset types, and high-throughput reliability without touching the isolated signer's core invariants.

### Independent Tasks:
- [ ] **Task 1.1: ERC-20 Token Transfers (`AssetType.ERC20`)**
  - Implement standard ERC-20 `transfer(address to, uint256 amount)` calldata serialization in `backend/app/schemas/`.
  - Add token contract address allowlisting in `PolicyConfig`.
  - Add decimal scaling support for tokens (e.g. 6 decimals for USDC, 18 for DAI).
- [ ] **Task 1.2: Velocity & Sliding Time-Window Limits**
  - Extend `backend/app/services/policy_engine.py` to evaluate sliding window limits (e.g. max 3 transactions per hour, rolling 24-hour spend vs calendar day).
  - Add database indexing on `spending_records.period_date` for high-throughput queries.
- [ ] **Task 1.3: Real-Time Event Streaming (Server-Sent Events)**
  - Implement `/api/v1/events/stream` SSE endpoint in FastAPI.
  - Broadcast proposal creation, policy decision, and transaction confirmation events to listening clients.
- [ ] **Task 1.4: Database Migrations (Alembic)**
  - Configure Alembic for zero-downtime database schema versioning alongside existing SQLite WAL mode.

---

## Workstream 2: Frontend Dashboard Enhancements

**Objective**: Deliver a state-of-the-art developer and operator user experience that visualizes security boundaries with crystal clarity.

### Independent Tasks:
- [ ] **Task 2.1: Server-Sent Events (SSE) Client Integration**
  - Replace current 10-second polling interval in `App.tsx` with live event stream listener.
  - Add reconnection fallback and optimistic UI updates for pending approvals.
- [ ] **Task 2.2: Visual Policy Rule Builder**
  - Create an interactive drag-and-drop or tag-based rule editor in `frontend/src/views/PoliciesView.tsx`.
  - Support easy address tagging (e.g. "Staking Node", "Treasury Multisig", "Known Phishing").
  - Real-time ETH/USD fiat valuation calculator using public oracle feeds.
- [ ] **Task 2.3: Live Etherscan Sepolia Transaction Explorer Linker**
  - Enhance transaction modals to link directly to `https://sepolia.etherscan.io/tx/{tx_hash}` when running in live Sepolia mode.
  - Display confirmation receipts (block number, gas used, effective gas price).
- [ ] **Task 2.4: Accessibility & Keyboard Navigation (WCAG 2.1 AA)**
  - Add full keyboard navigation across modal dialogs (`Esc` to dismiss, focus trapping).
  - High-contrast visual audit for colorblind operators (`ALLOW`/`ESCALATE`/`BLOCK` distinct iconography and textures).

---

## Workstream 3: Security, Adversarial Testing & Invariant Verification

**Objective**: Subject the authorization pipeline to hostile inputs, edge cases, and automated invariant verification to guarantee zero bypasses.

### Independent Tasks:
- [ ] **Task 3.1: Invariant Verification Suite (`SI-1` to `SI-12`)**
  - Build automated regression tests explicitly verifying every invariant:
    - Attempt signing a `BLOCK` proposal via direct API call (must fail 403).
    - Attempt replaying a consumed `jti` capability token (must fail 409).
    - Attempt tampering with `value_wei` after capability token issuance (must fail with digest mismatch).
    - Attempt approving an expired approval request (must fail 410).
- [ ] **Task 3.2: Property-Based Fuzzing with Hypothesis**
  - Implement Hypothesis test suite for `backend/app/schemas/` validating extreme inputs:
    - Unicode strings, null byte injections, 256-bit integer boundaries, zero Wei, negative Wei, scientific notation.
  - Verify that no untrusted input ever triggers an unhandled 500 error.
- [ ] **Task 3.3: Static Analysis & Dependency Vulnerability Scanning**
  - Integrate `bandit -r app/` and `safety check` in CI.
  - Integrate `npm audit` for frontend dependencies.

---

## Workstream 4: Blockchain, Sepolia Testnet & Demo Scripts

**Objective**: Build automated, reproducible demo scenarios for competition judging and live Sepolia testnet execution.

### Independent Tasks:
- [ ] **Task 4.1: Automated Demo Runner Script (`scripts/demo_scenarios.py`)**
  - Create a standalone Python CLI script demonstrating the entire story in 90 seconds:
    - Scenario A: Agent requests small node maintenance transfer &rarr; `ALLOW` &rarr; signed & submitted autonomously.
    - Scenario B: Agent requests large treasury transfer &rarr; `ESCALATE` &rarr; holds for human review &rarr; human reviews and approves &rarr; signed.
    - Scenario C: Agent attempts transfer to malicious address &rarr; `BLOCK` &rarr; zero signature created.
    - Scenario D: Inspector validates cryptographic audit chain &rarr; 100% integrity confirmed.
- [ ] **Task 4.2: Live Sepolia Faucet & Wallet Management Script**
  - Provide a script to check burner wallet testnet balance, estimate gas fees, and alert when testnet funds are low.
- [ ] **Task 4.3: Competition Pitch Slides & Architecture Diagrams**
  - Generate high-resolution presentation diagrams of the 11-step verification gate and token lifecycle for the Shenzhen FinTechathon submission.

---

## Workstream Assignment Matrix

| Workstream | Lead Area | Primary Files | Prerequisites |
| :--- | :--- | :--- | :--- |
| **WS-1: Backend** | Python / FastAPI / Models | `backend/app/api/`, `backend/app/models/`, `backend/app/services/policy_engine.py` | Python 3.12+, pytest |
| **WS-2: Frontend** | React 19 / TypeScript / Vite | `frontend/src/views/`, `frontend/src/components/`, `frontend/src/api/` | Node 20+, npm |
| **WS-3: Security** | Security Testing / Invariants | `backend/tests/security/`, `backend/tests/unit/` | pytest, hypothesis |
| **WS-4: Blockchain/Demo**| Scripts / Sepolia / Demos | `backend/scripts/`, `backend/app/services/blockchain.py`, `docs/` | web3.py, testnet wallet |
