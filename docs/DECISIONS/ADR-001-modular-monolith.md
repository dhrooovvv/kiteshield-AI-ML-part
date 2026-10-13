# ADR-001: Modular Monolith Architecture

## Status
Accepted

## Context
KiteShield Wallet has a 7-day development window with a 3-4 person team. We need clear module boundaries without the operational complexity of microservices.

## Decision
Use a modular monolith with logically separated modules (policy engine, signer, capability service, etc.) within a single FastAPI process.

## Consequences
- **Positive**: Single deployment, simpler debugging, shared database, fast inter-module calls
- **Negative**: All modules share process memory (signing key accessible to all code), no independent scaling
- **Mitigation**: Signer module has a clean interface; can be extracted to a separate service post-MVP
