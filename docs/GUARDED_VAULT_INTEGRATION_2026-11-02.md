# KiteShield guarded vault integration — 2 November 2026

The user explicitly approved scoped changes to signer, capability, authorization
and execution for the reviewed guarded-vault design. This document supersedes
the original spike's integration NO-GO. This is a bounded Sepolia deployment,
not an independent security audit or authorization for Ethereum mainnet.

## Authority and execution

The existing wallet `0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7` remains owner.
Its key, RPC, policy version 6, vendor registry and role credentials were retained.
A separate restricted agent identity has a private 0600 key file outside Git.
It does not replace the original wallet or global signing configuration.

Vault calls have immutable typed records, exact ABI templates, a separate JWT
audience and single-use capability records. The existing IsolatedSigner is the
only signing path. It independently checks the persisted intent, role, current
policy, artifact/runtime pin, exact calldata/value/sender/nonce, session epoch,
allowance, expiry, fees and any required action-bound human approval. An ordinary
native capability cannot authorize a vault call, or vice versa.

Administrator intents may deploy, configure, deposit, grant agent gas, resume
pause independently of the agent gas balance, or recover only to the immutable owner. The agent may pay the fixed recipient,
reduce allowance/cap/expiry, or pause. Neither incoming transfers nor token/NFT
events update these grants. Recovery pauses and advances the epoch. Configuring
a session does not clear an on-chain pause. Only the administrator can resume.

Optional automatic escrow funding uses only the existing configured faucet
adapter, its cooldown and the task's funding budget. The vault must be explicitly
registered in the administrator's watched-address configuration and a separate
flag must be enabled. The funding target is the frozen vault, not the owner's
wallet; grants never increase on incoming ETH. Agent gas still requires an owner grant.

Each new task freezes its payment method and vault grant. Historical native tasks
remain native; restart or a new grant never retargets an old task. Payout policy
and human-approval digests bind the complete typed vault operation. Native
transfers retain their original validation. No zero-value payout or fictitious
one-wei spending entry is used for owner controls.

The shared execution mutex coordinates native and vault nonces for each sender.
Signed bytes, token consumption and budget reservations are committed before
broadcast. Unknown outcomes retain the same operation/hash and do not sign or
send a replacement. Receipt reconciliation verifies the exact transaction,
canonical block, pinned runtime, and matching Paid event. Reconciliation does
not grant authority and can finish after an approval or session expires.

Local self-quarantine immediately stops this orchestrator. Its optional safety
worker requests one restriction-only on-chain pause per quarantine epoch. If
that request fails, local quarantine remains active and an issue is raised;
there is no retry loop or automatic on-chain resume. Existing legacy invoice,
treasury and ordinary manual flows remain governed by their existing controls;
this is not a claim of a new global emergency stop.

## Bounds and verification

Initial vault allowance and escrow: 40,000,000,000,000 wei, the unallocated part
of the existing 50,000,000,000,000 wei durable payment budget. Agent gas grant:
1,000,000,000 wei. Session duration: at most one hour; only an administrator can
renew it. Native transaction gas settings were retained. Vault agent gas ceiling
is 1,000,000; a separate 8,000,000 owner ceiling accommodates deployment.
All operations also reserve against a cumulative fee budget.

Live RPC preflight required about 5.34 million gas for deployment and a read-only
call with a one-million cap failed. The mined deployment used 5,301,312 gas.
Foundry v1.3.1 uses an older local gas schedule, so its local gas figures are
not live fee predictions. Ethereum's [state-creation repricing specification](https://eips.ethereum.org/EIPS/eip-8037)
and [Foundation developer note](https://blog.ethereum.org/2026/08/24/glamsterdam-repricing-testing)
describe why contract creation can require more gas; that is an explanation
consistent with these observations, not an independent attestation of this RPC's fork configuration.

- Final full backend run: 771 passed, 14 opt-in live-model tests skipped,
  including all 32 vault tests after the owner-cap, owner-pause, legacy nonce
  and configured-faucet integration changes.
- Frontend: 89 passed; production build and lint checked.
- Solidity: 13 passed, including 256 cap fuzz cases, owner-only recovery,
  replay/stale epoch rejection, tightening, pause/resume, and deposits.
- Tests use public fixture keys and isolated databases; network is blocked except
  the exact local read-only treasury fixture. Tests do not use the funded wallet.

Contract source is MIT with no Solidity dependencies. Solidity 0.8.30, optimizer
200, Cancun bytecode and official compiler package integrity are pinned in the
committed artifact. Official Foundry and local voice tool pins/licenses are
recorded in LICENSES.md. No installation scripts or third-party signing paths
were adopted. This remains logical isolation inside one backend process.

Public deployment and payment evidence is recorded in
`backend/demo_autonomy/reports/guarded-vault-sepolia-2026-11-02.json`.
No statistical security accuracy is inferred from unit tests or a single live
payment; historical committed simulated evaluations are not live performance claims.
