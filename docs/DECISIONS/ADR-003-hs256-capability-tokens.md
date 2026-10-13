# ADR-003: HS256 JWT for Capability Tokens

## Status
Accepted

## Context
Capability tokens authorize exactly one transaction action. They must be:
- Cryptographically signed
- Short-lived (120s)
- Transaction-bound (recipient, amount, chain)
- Single-use (replay-protected)

## Decision
Use HS256 (HMAC-SHA256) JWTs with a 256-bit symmetric secret.

## Rationale
- Single service architecture — the issuer and verifier are in the same process
- Simpler key management — one secret vs. key pair
- Sufficient security for MVP — key never leaves server memory
- PyJWT is a mature, well-audited library

## Alternatives Considered
- **RS256**: Asymmetric signing. Better for multi-service. Overkill for single process.
- **PASETO**: More opinionated, fewer footguns. Less ecosystem support in Python.
- **Custom HMAC**: Unnecessary when JWT with HS256 provides the same guarantees with standardized format.

## Security Properties
- Secret must be ≥ 256 bits (enforced in config validation)
- Secret stored in environment variable, never in code or logs
- Token lifetime: 120 seconds
- Clock skew tolerance: 30 seconds
- Single-use enforced by database consumption record

## Token Claims
```json
{
  "jti": "unique-token-id",
  "iss": "kiteshield-capability-service",
  "aud": "kiteshield-signer",
  "sub": "agent-id",
  "action": "eth_transfer",
  "chain_id": 11155111,
  "recipient": "0x...",
  "amount_wei": "10000000000000000",
  "tx_digest": "sha256-of-canonical-action",
  "policy_version": 1,
  "approval_id": null,
  "nonce": "unique-nonce",
  "iat": 1697200000,
  "exp": 1697200120
}
```

## Migration Path
To support multi-service deployment, switch to RS256. The signer would hold the public key only; the capability service would hold the private key.
