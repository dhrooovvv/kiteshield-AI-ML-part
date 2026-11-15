# Autonomous purchase workflow

The main app includes an opt-in purchase workflow under Workflows. It sells one
synthetic digital field guide through a local demo merchant, priced at exactly
0.00001 ETH. Sepolia settlement uses the existing approved recipient and guarded
vault. The merchant is part of this demo application. It is not a Riptide or
third-party merchant integration.

## Enablement

`AUTONOMY_COMMERCE_ENABLED=false` is the default. An administrator can enable it
in the main service configuration together with the existing autonomy and vault
settings. Restart through the normal service procedure. This flag does not grant
spending authority, configure a recipient, fund the vault, renew a session, or
clear quarantine. Existing mandates, policy, budgets and role checks still apply.

The isolated main-app launcher accepts `--enable-commerce` with
`--enable-autonomy`. It uses port 8001 and disposable storage. Its simulation
cannot unlock the live product or present an explorer receipt as proof.

## Purchase sequence

1. Connect the Proposer role and open Workflows / Autonomous purchase.
2. Start the displayed supported instruction. The application saves a merchant
   quote, invoice and order identity before creating its durable goal.
3. Local Gemma proposes the existing balance, funding, payment and receipt steps.
   Deterministic code validates them and retains all execution authority.
4. The purchase observes one existing goal and vault operation. Its invoice is
   an attached record and never enters the separate invoice-payment worker.
5. A completed task with matching verified Sepolia vault payment and receipt
   unlocks the downloadable guide. Transaction identity is unique per order.
6. Retrieve the same order to see its saved progress and result. A changed-price
   checkout is rejected by the backend before a payment task is created.

## Human Admin connection

`UNIFIED_ADMIN_ENABLED=false` preserves the existing separate backend permissions.
When an administrator enables it, the existing `POLICY_ADMIN_API_KEY` identifies
one human Admin with proposal, approval, policy, vault-owner and emergency controls.
The dashboard uses one connection field and verifies the credential's identity.
The key stays in browser memory and disconnect clears the session. Gemma receives
no credential, and autonomous workers continue using their existing restricted
proposer identity. The isolated launcher also accepts `--unified-admin`.

## Boundaries

Only the fixed supported purchase instruction and product are available.
The quote binds recipient, price, chain, expiry and mandate version. Arbitrary
website instructions and model-selected recipients or transaction data are not
accepted. Owner and agent keys remain in the existing wallet configuration.

Order retry recovers a persisted task even if the process stopped between task
creation and linking it to the order. A separate order ID expresses a new purchase.
Unknown payment outcomes retain existing reconciliation and human-review behavior.

Fulfillment uses the existing adapter's saved verified payment evidence. This is
a local merchant sharing the application trust boundary. It is not an independent
payment processor or a finality guarantee, and completed deliveries are not
continuously rechecked for chain reorganizations.

No Riptide code or new signing dependency is included. Ethereum Sepolia is chain
11155111. Ethereum mainnet and Base Sepolia are outside this workflow.

## Verification on 12 November 2026

- 49 focused backend tests passed, including purchase concurrency, restart,
  receipt matching, request-key preclaim, disabled mode and role checks.
- Frontend production build and lint passed.
- The installed local Gemma returned the required schema-valid four-step plan.
- Isolated main-app API rejected a changed price with
  `CHECKOUT_TOTAL_CHANGED`, no payment task and no delivery.
- The desktop purchase screen was inspected against that isolated API.

These checks did not activate the main deployment or send a new Sepolia payment.
The live purchase-to-delivery sequence remains unverified. A currently valid
administrator-configured session and funded vault are required for that run.

Unified Admin verification passed 67 focused backend tests covering Admin opt-in,
legacy permissions, emergency stop, vault controls and purchases. All 92 frontend
tests, production build and frontend lint passed. Browser verification used the
single connection dialog and displayed one Admin badge in the isolated app.
Targeted lint for the new Admin security changes passed. Broader backend lint
still reports existing long lines in the assistant and invoice-agent modules.
