# Sepolia payment 1 confirmed; payment 2 preview only

## Actual execution evidence

Payment 1 was explicitly authorized by the user, then created through
`POST /api/v1/proposals/agent`, evaluated by the deterministic policy engine,
and signed/submitted through the existing proposer-authenticated signing endpoint.
No admin or human-approver credentials were used. Active policy v6 returned ALLOW;
its threshold did not require human approval. Chat authorization was not represented
as a dashboard human-approval record or as on-chain session-key authority.

- Sender: `0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7`
- Recipient: `0x229D5588641f2614e3F486c853D8BA0eC5FFe811`
- Amount: **0.00001 ETH** (`10000000000000` wei)
- Chain: **Ethereum Sepolia, 11155111**
- Nonce: **0**
- Proposal ID: `b5d9d642-3fe4-44de-b589-2ff4d058f892`
- Correlation ID: `demo-payment1-authorized-2026-10-18-33wei`
- Transaction record: `0ad13ad5-81fa-4498-905d-66842326d99f`
- Transaction hash: `0x02437c8d60cfc3ecd3eab9406437ce948b3474a58a3e833d7483d1bcefd8faaa`
- Explorer: https://sepolia.etherscan.io/tx/0x02437c8d60cfc3ecd3eab9406437ce948b3474a58a3e833d7483d1bcefd8faaa
- Successful receipt: **status 1, block 11938916**
- Signed gas limit: **248870**, max fee **33 wei/gas**, priority fee **1 wei/gas**
- Actual gas used: **204600**, effective price **17 wei/gas**
- Actual fee: **3478200 wei**
- Actual total cost including principal: **10000003478200 wei = 0.0000100000034782 ETH**
- Recipient balance independently observed after confirmation: `10000000000000` wei.

The network transaction fields were checked against the approval. PublicNode
independently returned the same successful receipt and gas costs. Confirmation
means an observed mined receipt, not a claim of consensus finality/reorg immunity.

Full receipt, public envelope, policy/approval/execution references and all seven
audit-event hashes are saved in:
`docs/evidence/sepolia-payment1-02437c8d60cfc3ec.json`.

Audit sequence: PROPOSAL_CREATED → POLICY_ALLOW → EXECUTION_LIMITS_CHECKED →
CAPABILITY_ISSUED → SIGNING_COMPLETED → TX_SUBMITTED → TX_CONFIRMED.
TX_CONFIRMED event ID: `4e5e943d-5942-4e52-a55b-7ae3a159f2de`.

## Scoped implementation prerequisite

Added optional strict `ExecutionLimits` to the existing signing endpoint and
coordinator, not a new execution path. It can only restrict execution; it cannot
grant permission. Sender, recipient, exact amount, chain, nonce, gas, both fee caps
and total exposure are checked against the prepared envelope under the execution
lock before capability issuance/signing. The capability then binds the envelope
as before. Retry requests with limits check the original stored envelope.
The successful limit check is audited. Global limits and credentials were not changed.

Files changed: `backend/app/schemas/__init__.py`,
`backend/app/api/routes/proposals.py`, `backend/app/services/execution.py`,
`backend/tests/integration/test_sepolia_execution.py`, and these new evidence files.
Existing policy, signer authorization, emergency stop and approval checks remain intact.

Validation: **47 targeted backend tests passed**, including caller-bound sender,
recipient, amount, nonce, gas, fee, total and fee-race rejection before signing;
targeted Ruff, Python compilation and git diff --check passed.

## Payment 2 — not authorized, not signed, not broadcast

Fresh read-only preview after payment 1 confirmed:

| Field | Value |
|---|---:|
| Amount | 0.00002 ETH |
| Provisional nonce | 1 |
| Gas limit including existing margin | 25200 |
| Max fee per gas | 33 wei |
| Priority fee per gas | 1 wei |
| Estimated fee | 428400 wei |
| Maximum fee exposure | 831600 wei |
| Maximum total cost | 20000000831600 wei = 0.0000200000008316 ETH |
| Sender balance at preview | 49989999996521800 wei |

No payment-2 proposal, spending reservation or signing request was created. These
are provisional values, not an execution authorization. Recheck all conditions if
the user later authorizes payment 2. Never replace or duplicate payment 1.

Organizer acceptance of testnet evidence remains unconfirmed. This receipt is actual
Sepolia evidence, not simulated evidence, a production-safety certification, or proof
that any competition bonus or eligibility criterion has been satisfied.
