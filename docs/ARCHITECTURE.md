# KiteShield Wallet — Architecture

## System Overview

KiteShield Wallet implements a **constrained authorization pipeline** for AI agent-initiated blockchain transactions. The architecture follows a **modular monolith** pattern — logically separated modules within a single deployment unit.

### Core Principle
> "Give the agent hands, not the keys."

The system ensures that:
1. An AI agent can **propose** transactions
2. A deterministic **policy engine** evaluates proposals
3. A human can **approve** escalated actions
4. A narrowly-scoped **capability token** authorizes exactly one action
5. An **isolated signer** independently verifies before signing
6. An **audit trail** records the complete lifecycle

## Architecture Diagram

```mermaid
graph TB
    subgraph "Browser — Untrusted"
        FE["React 19 + Vite Dashboard"]
    end

    subgraph "Backend — FastAPI Monolith"
        API["API Layer<br/>Routes + Validation + Auth"]
        AGT["Agent Service<br/>OpenAI Structured Output"]
        PE["Policy Engine<br/>Deterministic Rules"]
        APR["Approval Service<br/>Human Review"]
        CAP["Capability Service<br/>JWT Issuance"]
        SIG["Isolated Signer<br/>Independent Verification"]
        BC["Blockchain Adapter<br/>web3.py / Sepolia"]
        AUD["Audit Service<br/>Event Recording"]
    end

    subgraph "External Services"
        OAI["OpenAI API"]
        SEP["Sepolia RPC"]
    end

    subgraph "Storage"
        DB["SQLite — WAL Mode"]
    end

    FE -->|"HTTPS/JSON"| API
    API --> AGT
    AGT -->|"Structured Output"| OAI
    AGT -->|"Normalized Proposal"| PE
    PE -->|"Decision"| API
    API -->|"ESCALATE"| APR
    FE -->|"Approve/Reject"| APR
    API -->|"ALLOW/APPROVED"| CAP
    CAP -->|"JWT Token"| SIG
    SIG -->|"Verified Sign"| BC
    BC -->|"Submit Tx"| SEP
    PE --> AUD
    APR --> AUD
    CAP --> AUD
    SIG --> AUD
    BC --> AUD
    PE & APR & CAP & SIG & AUD & BC --> DB
```

## Trust Boundaries

```mermaid
graph LR
    subgraph "TB-0: External / Untrusted"
        Browser["Browser"]
        LLM["OpenAI LLM"]
        RPC["Sepolia RPC"]
    end

    subgraph "TB-1: Application Logic"
        API["API + Validation"]
        Agent["Agent Service"]
        Policy["Policy Engine"]
        Approval["Approval Service"]
        Capability["Capability Service"]
        Audit["Audit Service"]
    end

    subgraph "TB-2: Signing Boundary"
        Signer["Isolated Signer"]
        Key["Private Key"]
    end

    Browser -.->|"Validate all input"| API
    LLM -.->|"Structured output, untrusted"| Agent
    RPC -.->|"Verify chain ID"| API
    Capability -.->|"JWT token"| Signer
    Signer --> Key
```

## Module Responsibilities

| Module | Responsibility | I/O | Deterministic | Security Boundary |
|---|---|---|---|---|
| API Layer | Request validation, routing, auth | HTTP I/O | No | TB-0 → TB-1 |
| Agent Service | LLM interaction, proposal normalization | Network I/O | No | TB-0 → TB-1 |
| Policy Engine | Rule evaluation, decision making | DB read | Yes* | Internal |
| Approval Service | Human review workflow | DB I/O | No | Internal |
| Capability Service | JWT token issuance | DB I/O | No | Internal |
| Isolated Signer | Token verification, tx signing | DB I/O, Crypto | No | TB-1 → TB-2 |
| Blockchain Adapter | TX submission, status tracking | Network I/O | No | TB-1 → TB-0 |
| Audit Service | Event recording | DB write | No | Internal |

*Deterministic given same input, same policy version, and same spending state.

## Transaction Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> PROPOSED: Agent proposes
    PROPOSED --> EVALUATING: Normalize + validate
    EVALUATING --> ALLOWED: Policy ALLOW
    EVALUATING --> ESCALATED: Policy ESCALATE
    EVALUATING --> BLOCKED: Policy BLOCK
    EVALUATING --> FAILED: Validation error

    ESCALATED --> APPROVED: Human approves
    ESCALATED --> REJECTED: Human rejects
    ESCALATED --> EXPIRED_APPROVAL: Approval timeout

    ALLOWED --> AUTHORIZED: Capability token issued
    APPROVED --> AUTHORIZED: Capability token issued

    AUTHORIZED --> SIGNING: Signer processing
    SIGNING --> SIGNED: Transaction signed
    SIGNING --> SIGN_FAILED: Verification failed

    SIGNED --> SUBMITTED: Sent to network
    SUBMITTED --> CONFIRMED: Block confirmation
    SUBMITTED --> TX_FAILED: Revert/failure

    BLOCKED --> [*]
    REJECTED --> [*]
    EXPIRED_APPROVAL --> [*]
    FAILED --> [*]
    SIGN_FAILED --> [*]
    TX_FAILED --> [*]
    CONFIRMED --> [*]
```

## Blockchain Adapter: Mock RPC vs Live Sepolia

KiteShield provides two distinct execution modes via `backend/app/services/blockchain.py`:

1. **Local Simulated Mode (`mock-rpc`)**:
   - Enabled when `SEPOLIA_RPC_URL` contains `mock-rpc` (e.g. `https://mock-rpc.sepolia.org`) or `APP_ENV=test`.
   - The isolated signer re-verifies all parameters, checks token claims, consumes the token atomically, and signs the raw EIP-155 transaction using the configured testnet private key.
   - The broadcast step returns a deterministic mock hash prefixed with `0x`, tagged as `network: "sepolia-mock"`, and recorded in audit logs.
   - Ideal for local visual testing, automated CI runs, and developer onboarding without testnet gas dependencies.

2. **Live Ethereum Sepolia Mode**:
   - Enabled when configured with a real JSON-RPC provider (e.g. Alchemy, Infura, or PublicNode).
   - Pre-signed raw transaction bytes are submitted to Ethereum Sepolia (Chain ID `11155111`) via `w3.eth.send_raw_transaction`.
   - Requires the signer account to hold Sepolia testnet ETH for gas fees.

## Related Documentation

- [API Contract & Module Boundaries](API_CONTRACT.md)
- [Team Workflow & Engineering Standards](TEAM_WORKFLOW.md)
- [Work Breakdown & Independent Workstreams](WORK_BREAKDOWN.md)
- [Security Threat Model & Invariants](SECURITY.md)

## Architecture Decision Records

- [ADR-001: Modular Monolith](DECISIONS/ADR-001-modular-monolith.md)
- [ADR-002: SQLite for MVP](DECISIONS/ADR-002-sqlite-for-mvp.md)
- [ADR-003: HS256 Capability Tokens](DECISIONS/ADR-003-hs256-capability-tokens.md)
