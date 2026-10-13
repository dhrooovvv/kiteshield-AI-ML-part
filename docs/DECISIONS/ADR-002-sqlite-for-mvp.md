# ADR-002: SQLite for MVP Database

## Status
Accepted

## Context
The MVP needs a database for policies, proposals, approvals, tokens, transactions, and audit events. Options: SQLite or PostgreSQL via Docker.

## Decision
Use SQLite in WAL (Write-Ahead Logging) mode.

## Rationale
- Zero setup required — no Docker, no external service
- WAL mode supports concurrent reads (sufficient for demo)
- Write serialization is acceptable for MVP throughput (~10 TPS)
- Simplifies the "reproduce from clone" requirement
- Foreign keys and CHECK constraints work in SQLite

## Trade-offs
- No true concurrent writes (writes are serialized)
- No built-in row-level locking (use application-level transactions)
- Spending-limit concurrency needs careful handling with IMMEDIATE transactions

## Migration Path
SQLAlchemy abstracts the dialect. Switching to PostgreSQL requires changing DATABASE_URL and handling a few SQLite-specific PRAGMAs.
