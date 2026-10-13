# KiteShield Wallet — API Contract & Module Boundaries

This document defines the authoritative HTTP API contract for KiteShield Wallet, its request/response schemas, error handling conventions, and architectural module boundaries.

---

## 1. Global API Standards

- **Base URL**: `/api/v1`
- **Content-Type**: `application/json`
- **Authentication**: `X-API-Key` HTTP Header (required on all protected endpoints)
- **Correlation ID**: `X-Correlation-ID` header injected on every request and response for end-to-end distributed tracing.
- **Envelope Standard**: All successful responses return an `APIResponse` object:
  ```json
  {
    "data": { ... },
    "meta": {
      "correlation_id": "f0281247-8358-4567-96ad-48f5fec6c0e4"
    }
  }
  ```
- **Error Standard**: All error responses return a standardized structured error object:
  ```json
  {
    "error": {
      "code": "POLICY_BLOCK",
      "message": "Transaction blocked by security policy.",
      "correlation_id": "06c0ab36-3d95-47d2-a8b7-e641c5fdfff3",
      "details": { ... }
    }
  }
  ```

---

## 2. Security Invariants (SI-1 to SI-12)

Every endpoint and service boundary enforces the following invariants:

| ID | Rule | Description |
| :--- | :--- | :--- |
| **SI-1** | Untrusted AI Input | LLM model outputs are untrusted. All proposals undergo strict Pydantic validation and address normalization before evaluation. |
| **SI-2** | No Invalid Signing | Invalid, malformed, or unverified proposals can never be signed or submitted. |
| **SI-3** | BLOCK Is Terminal | Proposals evaluated to `BLOCK` cannot be signed, approved, or bypassed under any circumstances. |
| **SI-4** | Autonomous Limit | Autonomous execution is strictly confined to `value_wei <= escalation_threshold_wei` and whitelisted recipients. |
| **SI-5** | Escalation Gate | Proposals exceeding thresholds or requiring review (`ESCALATE`) strictly mandate human operator approval before capability token issuance. |
| **SI-6** | Single-Use Tokens | Capability tokens (`jti`) are consumed atomically in the database upon verification. Replay attacks are rejected. |
| **SI-7** | Action-Bound Tokens | Capability tokens embed a SHA-256 action digest (`recipient`, `amount_wei`, `chain_id`, `policy_version`). Any parameter change invalidates the token. |
| **SI-8** | Digest-Bound Approvals | Human approvals record the exact canonical action digest. If the transaction parameters are altered before signing, the signature is rejected. |
| **SI-9** | Independent Signer | The isolated signer independently re-validates token claims, active policy version, token replay status, and recipient checks before signing. |
| **SI-10** | Key Isolation | Private signing keys are held strictly in the backend isolated signer. They are never transmitted to the browser, stored in client state, or logged. |
| **SI-11** | Zero Secrets in Audit | Audit logs and hash chains record metadata, digests, and decisions, but never private keys or raw capability signing secrets. |
| **SI-12** | Fail-Closed Default | Any unexpected error, network timeout, schema discrepancy, or ambiguous state fails closed and halts execution. |

---

## 3. Endpoints Specification

### 3.1 Health & Diagnostics
- **`GET /api/v1/health`**
  - **Auth**: None required.
  - **Response**: `{"status": "healthy", "service": "kiteshield-wallet", "version": "0.1.0"}`

---

### 3.2 Policy Engine & Governance
- **`GET /api/v1/policies/active`**
  - **Description**: Returns current active policy version rules, limits, and allowlists/blocklists.
  - **Response `data`**:
    - `id`: UUID string
    - `version`: Integer (e.g. `1`)
    - `max_amount_wei`: Decimal string (e.g. `"1000000000000000000"`)
    - `escalation_threshold_wei`: Decimal string (e.g. `"100000000000000000"`)
    - `daily_limit_wei`: Decimal string (e.g. `"5000000000000000000"`)
    - `allowed_recipients`: List of lowercase Ethereum addresses
    - `blocked_recipients`: List of lowercase Ethereum addresses
    - `is_active`: `true`
    - `created_at`: ISO 8601 UTC timestamp

- **`GET /api/v1/policies`**
  - **Description**: Returns complete immutable historical list of policies.

- **`POST /api/v1/policies`**
  - **Description**: Publish a new active policy version. Automatically bumps version number and deactivates prior versions.
  - **Body**: `max_amount_wei`, `daily_limit_wei`, `escalation_threshold_wei`, `allowed_recipients`, `blocked_recipients`.

- **`PUT /api/v1/policies/{policy_id}`**
  - **Description**: Update an existing policy by publishing a new incremented version.

---

### 3.3 Transaction Proposals
- **`POST /api/v1/proposals`**
  - **Description**: Create a canonical structured proposal directly.
  - **Body**:
    ```json
    {
      "prompt": "Send 0.05 ETH for staking node maintenance",
      "recipient": "0x742d35Cc6634C0532925a3b844Bc9e7595f2BD1e",
      "amount_wei": "50000000000000000",
      "chain_id": 11155111,
      "asset_type": "NATIVE_ETH"
    }
    ```
  - **Response `data`**: Returns proposal record with status `PROPOSED`.

- **`POST /api/v1/proposals/agent`**
  - **Description**: Natural language agent endpoint. Extracts structured transfer parameters from natural language prompts using GPT-4o with deterministic regex fallback.
  - **Body**:
    ```json
    {
      "prompt": "Transfer 0.05 ETH to 0x742d35Cc6634C0532925a3b844Bc9e7595f2BD1e for RPC node staking"
    }
    ```
  - **Response `data`**: Structured proposal record with status `PROPOSED`.

- **`GET /api/v1/proposals`**
  - **Description**: List all proposals with optional status filter and pagination (`limit`, `offset`).
  - **Query parameters**: `status` (`ALL`, `PROPOSED`, `ALLOWED`, `ESCALATED`, `APPROVED`, `BLOCKED`, `SUBMITTED`, etc.), `limit`, `offset`.

- **`GET /api/v1/proposals/{proposal_id}`**
  - **Description**: Retrieve detailed proposal record with nested relationships: `policy_decision`, `approval_request`, and `transaction`.

- **`POST /api/v1/proposals/{proposal_id}/evaluate`**
  - **Description**: Evaluates proposal deterministically against the active policy.
  - **Decisions**:
    - `ALLOW`: Status transitions to `ALLOWED`. Pre-conditions for signing met.
    - `ESCALATE`: Status transitions to `ESCALATED`. Creates an `ApprovalRequest` record awaiting human decision.
    - `BLOCK`: Status transitions to `BLOCKED`. Strictly terminal; cannot be signed.

- **`POST /api/v1/proposals/{proposal_id}/sign`**
  - **Description**: Issues capability token, performs independent signer verification, signs raw transaction, and broadcasts to Ethereum Sepolia.
  - **Preconditions**:
    - Proposal must be in `ALLOWED` or `APPROVED` status.
    - Active policy must match the evaluation policy version.
    - If `APPROVED`, human approval digest must match transaction parameters.
  - **Errors**:
    - `403 POLICY_BLOCK` if status is `BLOCKED`.
    - `403 APPROVAL_REQUIRED` if status is `ESCALATED`.
    - `409 SIGNING_REJECTED` if token replay or validation fails.

---

### 3.4 Human Approvals
- **`GET /api/v1/approvals/pending`**
  - **Description**: Retrieves all approval requests currently in `PENDING` state with full proposal context.

- **`POST /api/v1/approvals/{approval_id}/decide`**
  - **Description**: Record human operator authorization or rejection.
  - **Body**:
    ```json
    {
      "decision": "APPROVE",
      "approved_by": "user:security_operator"
    }
    ```
  - **Outcomes**:
    - `"APPROVE"`: Approval status transitions to `APPROVED`, proposal status transitions to `APPROVED`. Unlocks signing.
    - `"REJECT"`: Approval status transitions to `REJECTED`, proposal status transitions to `REJECTED`.

---

### 3.5 Transactions & Blockchain
- **`GET /api/v1/transactions/{tx_id}`**
  - **Description**: Inspect submitted transaction hash, status (`SUBMITTED`, `CONFIRMED`, `FAILED`), gas used, and block number.

---

### 3.6 Cryptographic Audit Trail
- **`GET /api/v1/audit/{correlation_id}`**
  - **Description**: Retrieve all correlated lifecycle audit records for an end-to-end operation.
  - **Response `data`**: Chronological event array with `event_type`, `actor`, `details`, `previous_hash`, `event_hash`, and timestamps.

- **`GET /api/v1/audit/integrity/verify?limit=100`**
  - **Description**: Recalculates canonical SHA-256 hashes across recent database records to verify zero tampering or broken links in the cryptographic hash chain.
  - **Response `data`**:
    ```json
    {
      "is_valid": true,
      "errors": [],
      "checked_limit": 100
    }
    ```

---

## 4. Blockchain Adapter: Mock RPC vs. Live Sepolia

KiteShield includes a built-in mock mode to allow robust local development, integration testing, and team onboarding without requiring live testnet faucet funds or experiencing public RPC outages.

| Mode | Configuration | Behavior |
| :--- | :--- | :--- |
| **Local Simulated Mode** | `SEPOLIA_RPC_URL=https://mock-rpc.sepolia.org` *(or `APP_ENV=test`)* | The complete 11-step verification gate and raw transaction signing run identically using `web3.py` and `eth_account`. Broadcast produces a deterministic SHA-256 hash prefixed with `0x`, tagged as `network: "sepolia-mock"`, and recorded in audit logs. No testnet gas is consumed. |
| **Live Sepolia Testnet** | `SEPOLIA_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/...` | Pre-signed raw transaction hex is broadcast via `w3.eth.send_raw_transaction` to Ethereum Sepolia (Chain ID 11155111). Signer account must hold Sepolia ETH for gas. Transaction hash can be viewed on Sepolia Etherscan. |
