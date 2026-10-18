# Simulation-only Demo administrator

The existing dashboard now supports one verified Demo administrator credential for
proposal creation, evaluation, simulated submission, policy management and approval
decisions. The backend records actor `demo_admin`, not a fabricated human identity.
Policy evaluation, approvals when required, spending limits, signer checks and the
emergency stop still apply. This is a demo convenience, not separation of duties.

## Start it

1. Stop the backend in its terminal with Ctrl+C. Do not launch a second copy on 8000.
2. From `backend/`:

   ```sh
   ./.venv/bin/uvicorn app.main:app --env-file .env.demo --reload --host 127.0.0.1 --port 8000
   ```

3. Keep the frontend running (`npm run dev` from `frontend/`) and refresh the dashboard.
4. Open API key / Switch role; select **Demo administrator (simulation only)**.
   Copy only the `DEMO_ADMIN_API_KEY` value from `backend/.env.demo` into the dialog.
5. Verify the header says **Simulation · no on-chain broadcast** and shows the verified
   Demo administrator role. Its single credential is used for all three demo roles.
6. The new demo database starts without a policy. Use Create Initial Policy, enter
   the desired bounds and allowlist, and publish. Test a proposal above the escalation
   threshold, explicitly approve it, then Sign & simulate. No on-chain receipt is claimed.

`backend/.env.demo` has been created with independent application credentials and
owner-only file permissions. Its values were not printed. It is Git-ignored; do not
commit it or put credentials into `VITE_*`, browser storage or prompts. Credentials
stay in dashboard memory and are cleared on page reload. If sharing the project,
use `.env.demo.example` and generate separate application secrets for that copy.

## Isolation and limits

- Requires APP_ENV=demo, EXECUTION_MODE=simulated and the separate local
  `sqlite+aiosqlite:///./kiteshield-demo.db` database. Startup rejects an unsafe combination.
- The demo profile uses a **public non-secret test signer fixture**, never the configured
  live wallet key. Never fund this fixture or use it as a real wallet.
- No RPC call is needed for this simulation. Optional models/OpenAI are disabled in
  the supplied demo profile. Signed test hashes are not evidence of broadcast/mining.
- Demo key authentication is rejected in live Sepolia, the normal development profile,
  a shared/live database, or an owner-signer configuration. A live profile is also
  rejected if pointed at the named demo database. Do not rename/copy demo data into
  a live database; this is configuration/storage isolation, not a hardware boundary.
- Demo key never grants emergency-stop administration; that credential stays separate
  and backend-only. Prompt-screening review records remain informational, not executable.
- Existing proposer/human-approver/policy-admin separation remains in the live profile.
  Demo policy and approval changes are stored only in the demo database.

## Return to real Sepolia

Stop demo backend with Ctrl+C, then from `backend/`:

```sh
APP_DEBUG=false ./.venv/bin/uvicorn app.main:app --env-file .env --reload --host 127.0.0.1 --port 8000
```

Refresh the browser and reconnect the separate live roles. Confirm the verified Sepolia
header before preparing any real transaction. Changing profile is not broadcast permission.
No real transactions were signed or sent during this task; payment 2 remains unauthorized.
The existing live `.env`, database, policies, and real payment evidence were not replaced.

## Validation

- 69 focused backend tests passed: demo role, identity, payment-security, Sepolia execution,
  execution boundaries and emergency-stop regressions.
- 33 frontend tests passed, including one-key routing, live rejection/disconnection and
  component permission gates for the Demo administrator.
- Frontend lint, TypeScript and production build passed; targeted Ruff, Python compilation
  and git diff --check passed.
- Temporary real local demo server verified simulated health, backend-verified demo identity
  and authenticated policy reads. The live/default server rejected the same demo key (401).
  The temporary port-8001 server was stopped afterwards to avoid a stray background process.
- Browser visual testing is unavailable in current Work settings; component checks use
  server rendering, not a claimed interactive browser session.
