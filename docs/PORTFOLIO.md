# Read-only Portfolio

Open **Portfolio** beside Overview. The only new endpoint is authenticated
`GET /api/v1/portfolio`; the same verified API credentials used for other reads apply.
There is no proposal, approval, signing, broadcast, receipt reconciliation, token
discovery, or financial authorization operation in this endpoint or view.

## Configuration

Defaults show ETH for the signer public address only. Optional backend configuration
uses JSON arrays, not private keys or frontend build variables:

```dotenv
WATCHED_ADDRESSES=["0x229D5588641f2614e3F486c853D8BA0eC5FFe811"]
TOKEN_ALLOWLIST=[]
```

Each configured ERC-20 entry needs `symbol`, public `address`, and `decimals`:

```json
[{"symbol":"TEST","address":"0x1111111111111111111111111111111111111111","decimals":18}]
```

The token above is a syntax example, NOT a verified token deployment. Configure only
known Sepolia contracts; incorrect contracts/decimals produce unavailable or misleading
balances. There is no automatic token discovery. Up to 10 watched addresses and 8
tokens are accepted. Restart after configuration changes. Actual local watch/token
lists were not changed by this task.

## Data semantics

- Every request freshly verifies chain 11155111, reads the latest block number and UTC
  timestamp, reads ETH/configured token balances at that numbered block, reads the
  signer's pending nonce separately, and rechecks chain identity. There is no cache.
- A failure/malformed RPC response clears the whole holdings snapshot, returns an
  explicit unavailable reason, and suppresses provider exception text/credential URLs.
  Budget and payment records remain separately labeled database information.
- Amounts are exact decimal strings calculated with Decimal; `balance_raw` is the exact
  integer string and `decimals` is configured token precision. No USD/price data exists.
- Share percentages are **wallet shares of each individual asset**, rounded to six
  decimal places. ETH and arbitrary ERC-20 units are not summed into a fictitious
  portfolio valuation. Zero-total assets have null share, displayed as zero-total.
  Different token contracts remain identifiable even when symbols match.
- Budget principal excludes gas. Spent today means COMMITTED reservations assigned to
  today's UTC calendar day. Pending includes every RESERVED amount, including earlier
  days, matching existing authorization accounting. Remaining is floored at zero.
  An absent daily limit is unbounded/not configured, not zero. No active policy is
  explicitly unavailable. The configured auto-execution cap is shown alongside the
  policy escalation threshold/absolute max and version; this display changes no limits.
- Recent payments are the last 10 transaction records, not unexecuted proposals.
  `status` displays the execution outcome (including SIMULATED/UNCERTAIN/REVERTED);
  `lifecycle_status` and `execution_outcome` are also exposed separately. Unverified
  historical mode/outcome is not silently presented as a confirmed live payment.
  Explorer links require Sepolia mode/chain and a complete 32-byte hash; simulated
  outcomes never receive links. These are stored outcomes, not freshly reconciled
  receipts or finality guarantees.
- Portfolio reads on entry and explicit refresh, not on the app-wide background poll.
  A manual refresh keeps the layout stable, labels previous data as stale with its age,
  and replaces the snapshot atomically. Failures clear old data and show unavailable.
  Snapshot age is available under Details between reads. The header Refresh control
  triggers a new read; obsolete reads are cancelled. No trading/payment controls exist.

## Verification — October 18, 2026

- Complete backend suite: **372 passed, 14 skipped**.
- Frontend suite: **39 passed**.
- Ruff, Python compilation, frontend lint, TypeScript/Vite build and `git diff --check` pass.
- Eight new backend tests cover exact 1-wei/uint256 formatting, auth, no writable route,
  wrong-chain/RPC/malformed failure states, secrets absent, no execution methods,
  provider-log suppression, UTC pending reservations, simulated/unverified explorer
  suppression, and explicitly configured ERC-20 reads. Frontend tests cover GET-only
  refresh, simulation/unavailable labels, budget text, and explorer suppression.
- A real authenticated **read-only GET** returned mode Sepolia, verified chain 11155111,
  block 11940145, one holdings row, pending nonce 5, policy version 6 and five historical
  payments. No proposal was created, no payment was signed/broadcast, and no receipt
  state was updated by Portfolio.
- Existing dashboard panels, typography, palette and layout tokens were reused under
  Impeccable guidance. Source/SSR review performed; browser visual verification was
  unavailable. No claims about contrast/layout measurements or visual sign-off.

## Files changed for this task

Backend: `app/core/config.py`, `app/main.py`, `.env.example`; new
`app/api/routes/portfolio.py`, `tests/integration/test_portfolio.py`.

Frontend: `src/api/client.ts`, `src/App.tsx`, `src/components/Navigation.tsx`,
`src/index.css`; new `src/portfolio.ts`, `src/views/PortfolioView.tsx`,
`tests/portfolio.test.ts`.

Documentation: `docs/PORTFOLIO.md`.

No signer, policy engine, capability, audit service, core/security, execution service,
live credential, auto-execution flag, policy, or spending reservation was changed.
Existing dirty work preserved; nothing staged, committed or pushed.

## Compact dashboard layout follow-up

The October 18 screenshot showed full-width holdings prose pushing the budget and
payments below the fold. The follow-up uses a compact network/mode/block/nonce strip,
desktop holdings/budget columns, and recent payments directly below. At 1180px and
below the sections stack; at 600px the budget changes from three columns to two.
Help text remains accessible through native details/summary disclosures. Exact balances
are unchanged; addresses/hashes are shortened visually with full title/accessibility
labels on links and keyboard/touch disclosures for unlinked identifiers. Explorer
targets are unchanged. No backend or execution code was changed.

Changed: frontend/src/views/PortfolioView.tsx, frontend/src/index.css,
frontend/tests/portfolio.test.ts, and this document. Impeccable layout and Product Design
context guidance were used to extend the established design rather than replace it.
Frontend tests: 40 passed; lint, TypeScript/Vite build, whitespace check pass. The
layout detector reports no findings. Source/SSR checks preserve ordering, full public
address metadata, exact balances, and read-only controls. Browser visual verification
remains unavailable; no measured viewport-height or scroll-reduction claim is made.

## Refresh flicker follow-up

Root cause: each global dashboard refresh incremented the revision consumed by Portfolio;
the read effect then cleared its data, replacing the whole dashboard with a loading line.
Portfolio now has a separate manual refresh revision. Its reducer retains a clearly
marked, age-labelled previous snapshot only while refreshing; failure clears it.
The one-second snapshot age timer does not make RPC requests or unmount panels.

Changed: frontend/src/App.tsx, frontend/src/views/PortfolioView.tsx,
frontend/src/portfolio.ts, frontend/tests/portfolio.test.ts, and this document.
Frontend suite: 42 passed; lint, TypeScript/Vite build and whitespace check pass.
The new reducer tests verify stable data identity/timestamp during refresh, atomic
replacement on success, and clearing balances on failure. Impeccable hardening guidance
informed stable loading and explicit stale/error states. Browser verification unavailable.
No backend, execution policy, signing, or broadcast changes; no transaction was sent.

## Portfolio chrome simplification

Removed the Portfolio-only global "Last updated" row, repeated introductory copy,
duplicate refresh button, idle snapshot banner, and always-visible network metadata.
One collapsed Details disclosure in Holdings retains network/mode/block/nonce,
snapshot age, allocation explanation, and testnet/no-market-value context. Refreshing
stale-data and unavailable/error messages remain visible when relevant; transaction
simulation labels and the app header network indicator remain intact.

Holdings and budget now stretch to a shared bottom edge, with recent payments directly
below their common row. No fixed heights or clipped records were introduced. Updated
files: PortfolioView.tsx, App.tsx, index.css, portfolio.test.ts, and this document.
Impeccable distillation guidance informed progressive disclosure rather than removing
financial context. Frontend tests: 42 passed; lint, TypeScript/Vite build and whitespace
check pass. No backend changes or payments. Browser visual verification unavailable.

## Figma design-language adaptation

Reference: Figma file LKuWOG1nxtsKqfqcGZdx3h, node 0:2. High-fidelity design context
and its screenshot were inspected before adaptation. User approved applying its
design language to Portfolio only, not cloning the sample Expenses app or changing
the shared dashboard shell.

Portfolio now has one white workspace, flat holdings/payment ledger sections,
thin #eceff5 separators, #262a41 primary text, a #f8f9fb policy rail, and restrained
#31ba96 budget accents from the reference. Real amounts are right-aligned; payment
statuses are humanized, with confirmed status using accessible darker green text.
Google Sans Flex and existing app navigation are retained. No sample expense data,
decorative avatars, charts, or promotional imagery is inserted, and there are no
temporary Figma asset URLs in the shipped code. This is a semantic adaptation, not
a pixel-for-pixel recreation of the sample screen.

The ledger and rail share a CSS grid; narrow screens stack holdings, payments,
and budget in DOM order. Full addresses and transaction identifiers remain available,
balances stay exact, simulated transactions still have no explorer link, errors remain
explicit, and the manual-only refresh behavior is unchanged.

Task changes: frontend/src/views/PortfolioView.tsx, frontend/src/index.css,
frontend/tests/portfolio.test.ts, and this document. Existing dependency and unrelated
worktree changes preserved; no new dependencies installed for this task.
Frontend tests: 42 pass; lint, TypeScript/Vite build and whitespace check pass.
Browser visual comparison remains unavailable; no pixel-fidelity claim is made.
No backend, credential, transaction or security behavior changed; no signing/broadcast.
