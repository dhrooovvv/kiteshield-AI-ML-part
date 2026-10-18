# Two-payment Sepolia preparation — blocked at configured gas limit

Date: October 18, 2026. Status: NOT AUTHORIZED, NOT SIGNED, NOT BROADCAST.

## Independent checks

- Configured key derives to requested sender:
  `0x3807fc9c3A8adF2d465290bbf06AE769DD08Ada7`.
- Recipient: `0x229D5588641f2614e3F486c853D8BA0eC5FFe811`.
- Chain verified as Sepolia, `11155111`. Balance: `50000000000000000` wei (0.05 ETH).
- Both sender and recipient have zero bytes of account code.
- Recipient explicitly allowlisted in active policy version 6; no empty-list inference.
- Active policy maximum 1 ETH; UTC daily principal budget 5 ETH; human escalation
  threshold 0.5 ETH. Neither payment requires human approval under this policy.
- Emergency stop inactive. No admin or approver credential used; no policy/approval changed.
- No existing execution attempt belongs to this sender in the local database.
- Publicnode RPC independently returned the same balance, chain, and gas estimate.

## Runtime

Added `EXECUTION_MODE=sepolia` to existing ignored backend/.env without changing
existing credential values. Backend restarted on 127.0.0.1:8000; frontend running on
127.0.0.1:3000. Backend process disables debug SQL logging to avoid recording binds.
Startup chain/block checks passed, readiness returned HTTP 200 with database/rules ready.
Frontend API proxy returns verified live health. Actual Header component rendered with
that health contains **Sepolia · chain 11155111 · block 11938738**. The number is the
startup observation, not a continuously polled block height. Browser visual interaction
is unavailable in Work settings; this was real-health server-render verification.

## Provisional read-only quotes

No nonce was reserved and no proposal or execution was created. Nonces are candidates
only and must be checked again before execution. Fees and account state may change.

| Field | Payment 1 | Payment 2 |
|---|---:|---:|
| Amount ETH | 0.00001 | 0.00002 |
| Amount wei | 10000000000000 | 20000000000000 |
| Candidate nonce | 0 | 1 |
| RPC gas estimate | 207391 | 207391 |
| Gas limit with existing 20% margin | 248870 | 248870 |
| Max fee per gas, wei | 29 | 29 |
| Priority fee per gas, wei | 1 | 1 |
| Estimated fee, wei (padded gas × observed base-plus-priority) | 3733050 | 3733050 |
| Maximum fee exposure, wei | 7217230 | 7217230 |
| Maximum total cost, wei | 10000007217230 | 20000007217230 |
| Maximum total cost, ETH | 0.00001000000721723 | 0.00002000000721723 |

Combined payment value: 0.00003 ETH.
Combined maximum fee exposure: 14434460 wei (0.00000000001443446 ETH).
Combined maximum total cost: **30000014434460 wei = 0.00003000001443446 ETH**.

**Execution blocker:** configured MAX_GAS_UNITS is 100000; required padded gas is
248870. Both existing-service previews correctly fail the gas bound. The detailed
numbers above are diagnostic read-only estimates, not executable approvals. Max fee
per gas remains within the existing 100000000000-wei setting. No limits were raised.
Do not substitute a 21000 gas limit or silently remove the margin to bypass this check.

## Necessary preparation fixes and validation

- Existing execution_attempts table lacked execution_mode. Added nullable column via
  existing additive startup migration; historical rows stay NULL, never guessed live
  or simulated. A legacy unresolved mode for a sender blocks new nonce allocation.
  Existing records were preserved; no table reset or recreation occurred.
- Preview script now reports successive provisional candidate nonces and per-payment
  maximum totals, and rejects a nonce advancing past its second candidate mid-preview.
- Changed: backend/.env, app/db/__init__.py, app/services/blockchain.py,
  scripts/preview_sepolia_payments.py, tests/unit/test_payment_migration.py;
  added tests/unit/test_payment_preview.py and this report. Other dirty work preserved.
- Targeted backend tests: **47 passed** (preview, migration, live startup, Sepolia execution).
- Header regression: **1 passed**. TypeScript and Vite build: passed.
- Targeted Ruff, Python compilation, git diff --check: passed.

## Stop / next authorization

No signing or broadcast is authorized. User must explicitly decide how to resolve the
gas cap (or wait for a valid RPC estimate within it). Do not change it implicitly.
After resolving it, refresh both complete previews and request explicit payment approval.
Then execute payment 1 through the existing agent/policy/signer flow, reconcile its
receipt and export public evidence. Re-preview payment 2; request renewed approval for
changed approved details or exceeded fee limits before execution.

No new transaction hashes, receipts, signing capabilities, or spending reservations
exist for these two drafts. Organizer acceptance of testnet evidence remains unconfirmed.
