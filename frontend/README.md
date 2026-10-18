# KiteShield dashboard

React 19 + TypeScript + Vite dashboard for KiteShield’s constrained Sepolia payment workflow.

See the [project README](../README.md) for backend configuration, simulation/live modes, security boundaries and payment prerequisites.

## Development

Use Node.js 22.12+ and start the backend on `127.0.0.1:8000` first.

```sh
npm ci
# Fresh checkout only; keep existing configuration:
cp -n .env.example .env
npm run dev -- --host 127.0.0.1 --port 3000
```

Open [http://localhost:3000](http://localhost:3000). Vite proxies `/api` to the backend. `VITE_API_BASE_URL` defaults to `/api/v1`; production hosting needs corresponding API routing.

Connect credentials using **API key / Switch role**. They stay in memory until reload. Never put API keys, private keys or emergency-stop credentials in `VITE_*` variables or browser persistent storage. Role indicators explain backend-verified permissions; the backend enforces access.

## Views

Overview, Portfolio, Proposals, Human Approvals, Policy Engine and Audit Explorer. Portfolio reads balances; it does not trade or send tokens. Policy allowance and receipt confirmation are displayed separately. Simulated outcomes are not on-chain evidence.

When live automation is enabled, proposing/evaluating an eligible small payment can execute it. Do not use live scenario presets merely to preview the interface.

## Checks

```sh
npm test
npm run lint
npm run build
```

The build runs TypeScript checks and produces `dist/`. `npm run preview` serves that build locally; it is not a production API deployment setup.

The interface uses React and custom CSS. The installed `frappe-ui` dependency is not an integrated React component system; installation alone does not migrate the dashboard to Vue/Frappe.
