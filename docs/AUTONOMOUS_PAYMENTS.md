# Autonomous Sepolia payments

Auto-execution is disabled by default. The local live Sepolia integration was subsequently
enabled at the user's request on October 18, 2026, with the existing 0.0001 ETH cap.
No payment was submitted to verify enablement. Health reports the active flag and cap.
Enable `AUTO_EXECUTE_ENABLED=true` only when intentionally authorizing unattended payments;
set `AUTO_EXECUTE_MAX_ETH=0.0001` (exact Decimal ETH) or a smaller limit and restart.
This flag is standing execution permission, not a substitute for backend financial authorization.

With Auto-Evaluate selected, Propose screens and creates an agent proposal, evaluates it,
then executes eligible ALLOW decisions through the existing execution coordinator. Without
Auto-Evaluate the proposal waits for evaluation. Structured/legacy proposals without
server-recorded benign screening provenance cannot auto-execute.

Eligibility requires verified live Sepolia chain 11155111, BENIGN screening bound to the
action digest, a positive amount within the configured cap and strictly below the policy
approval threshold, and an explicit recipient allowlist entry. An absent allowlist or
approval threshold is not autonomous permission. Existing current-policy checks, aggregate
UTC-day reservations (including outstanding reservations across midnight), capabilities,
independent logical signer validation, and emergency stop remain authoritative.
The signer remains logically isolated, not hardware/process isolated.

Only one outstanding signed/submitted execution is permitted through the autonomous
orchestrator at a time. Other eligible proposals remain ALLOWED, not silently queued.
Reevaluate them after receipt reconciliation to execute. Existing signed attempts are
never replaced: recovery uses the existing sign/reconcile endpoints and stored bytes.
After an auto-execution failure, no automatic fresh signing retry occurs; inspect the
durable execution before recovery. No background restart worker or automatic fee bumping
is introduced. A failed/uncertain response must never be treated as permission to create
another proposal for the same intent.

Proposal responses include the existing transaction fields. The existing dashboard poll
reconciles receipts and displays submitted, confirmed, reverted, or uncertain outcomes in
the same proposal UI. Confirmation requires an observed matching receipt, not merely ALLOW.
When enabled, the agent form always evaluates after Propose. Small ALLOWED proposal cards
omit manual signing and offer reevaluation if automatic execution has not completed.
Over-cap ALLOWED payments and APPROVED escalations retain manual signing. This is UI guidance,
not a change to backend authorization. The effective limit is shown in each proposal card.
Autonomous start, broadcast, confirmation, and failure events use actor
`autonomous_executor`. Existing signer/coordinator audit actors are preserved.

Schema change is additive: `autonomous_intents` is created by existing metadata startup,
with proposal ID as primary key. Existing proposal/transaction records are not rewritten.
The existing unique execution-per-proposal and sender/chain/mode/nonce constraints remain.

Tests use file SQLite, a public test-only signing fixture, and fake RPC; no live network,
real credential, or blockchain broadcast is used. Simulated application mode never
auto-executes. Test-only fake verified-Sepolia metadata exercises the live eligibility gate.
