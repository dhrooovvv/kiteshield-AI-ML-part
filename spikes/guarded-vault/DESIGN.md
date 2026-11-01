# Guarded-vault enforcement spike — 1 November 2026

**Decision: NO-GO for integration; GO for further isolated research.**

This separate proof of concept targets Ethereum Sepolia (chain 11155111) and rejects
other chain IDs at construction. It has NOT been deployed or broadcast to Sepolia.
All execution evidence is from Foundry's local EVM configured with Sepolia's chain
ID. No funded wallet, RPC credentials or live configuration were used.

## What the experiment establishes

The owner and agent are different identities. Only the owner configures the agent,
recipient, session allowance, per-payment cap and expiry. The agent can reduce
allowance, cap and expiry, and can pause itself. Only the owner can resume. A new
owner configuration does not silently clear quarantine. The agent cannot choose a
recipient during payment, expand its limits, configure another agent or approve a
proposal. Nonce and epoch checks reject stale/replayed actions. Deposits emit an
event and do not alter allowance. Checks/effects precede the external transfer.

The test suite derives separate owner/agent addresses from public test-only keys
0x111 and 0x222. These are fixtures, not wallet credentials for deployment.

## Tools, pinning, and evidence

- Foundry **v1.3.1**, official `darwin_arm64` release archive.
- Release archive SHA-256:
  `e3c880d28eae2a150f3f01a674b3cd6a130d6d3f16685740cd1e16538b58a4a5`.
  Verified against the digest in GitHub's release asset metadata before execution.
- Downloaded the archive directly and extracted only `forge` to a private temporary
  folder. No installer script, foundryup, shell pipeline or repository install ran.
- Foundry license: MIT OR Apache-2.0, checked at the pinned upstream tag:
  https://github.com/foundry-rs/foundry/tree/v1.3.1
- Solidity compiler pinned **0.8.30**, EVM Cancun, optimizer 200 runs. Forge fetched
  the pinned compiler through its normal compiler mechanism; not a wallet SDK.
- Solidity compiler license: GPL-3.0, checked at the pinned tag:
  https://github.com/ethereum/solidity/blob/v0.8.30/LICENSE.txt .
  No compiler or Foundry binary is redistributed in this repository.
- No forge-std, smart account library, wallet library or external Solidity dependency.
- Command: `forge test --root spikes/guarded-vault -vv`.
- **9 tests passed; 0 failed**, including **256 fuzz executions** of the cap test.
  Covers authorized payments, owner-only configuration, tightening, stale/replayed
  actions, owner-only resumption, deposits, expiry, wrong caller and wrong chain.

This small suite is not an audit, invariant proof or production certification.
Fuzz runs are not independent samples for a statistical security success rate.

## Why integration is a no-go

KiteShield currently authorizes native transfers. Calling `GuardedVault.pay` would
require a contract-call action type, exact ABI calldata binding, vault/session/epoch
and nonce bindings, gas accounting, receipt decoding, expiry/rotation semantics and
new custody/recovery design. Those changes intersect the protected signer,
capability, policy, authorization and execution surfaces. None were changed.

It would be incorrect to route arbitrary model-selected calldata through the
existing native-transfer permission. A live vault would also require separately
funded owner and agent wallets, a deployment ceremony and independent review.
The current session allowance does not encode invoice-specific human approval or
prove that a purchased external service was delivered.

No deployment script, integration import or UI control is provided. The spike
cannot be enabled by an agent instruction. Any future integration needs explicit
approval and a reviewed change to the protected authorization design.
