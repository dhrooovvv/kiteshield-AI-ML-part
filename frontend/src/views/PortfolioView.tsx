import { useEffect, useReducer, useState } from 'react';
import { api } from '../api/client.ts';
import type { PortfolioSnapshot } from '../portfolio.ts';
import { initialPortfolioRead, portfolioReadReducer } from '../portfolio.ts';
import { humanizeEvent } from '../auditPresentation.ts';

const shortAddress = (value: string) => value.length > 20
  ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
const ethAmount = (value: string | null, fallback: string) => value === null ? fallback : `${value} ETH`;

export function PortfolioContent({ data, snapshotAgeSeconds }: {
  data: PortfolioSnapshot; snapshotAgeSeconds?: number;
}) {
  const { network, budget, recent_payments: payments } = data;
  const spent = Math.min(100, Math.max(0, Number(budget.spent_percent ?? 0)));
  const pending = Math.min(100 - spent, Math.max(0, Number(budget.pending_percent ?? 0)));
  return <div className="portfolio-content">
    <div className="portfolio-dashboard-grid">
    <section className="portfolio-section portfolio-holdings" aria-labelledby="holdings-title">
      <div className="portfolio-panel-heading"><h2 id="holdings-title">Holdings</h2></div>
      {network.status === 'unavailable'
        ? <p role="alert">Holdings unavailable: {network.message} No cached balances are shown.</p>
        : <>
          <div className="portfolio-table-wrap"><table className="portfolio-table">
            <thead><tr><th scope="col">Asset</th><th scope="col">Wallet</th>
              <th scope="col">Balance</th><th scope="col">Share of asset</th></tr></thead>
            <tbody>{network.holdings.map(row => <tr key={`${row.token_address ?? 'ETH'}:${row.address}`}>
              <td>{row.asset}{row.token_address && <><br /><small>Token contract{' '}
                <a href={`https://sepolia.etherscan.io/token/${row.token_address}`}
                  title={row.token_address} aria-label={`Token contract ${row.token_address}`}
                  target="_blank" rel="noopener noreferrer">{shortAddress(row.token_address)}</a></small></>}</td>
              <td><strong>{row.role}</strong><br />
                <a href={row.address_url} title={row.address} aria-label={row.address}
                  target="_blank" rel="noopener noreferrer">{shortAddress(row.address)}</a></td>
              <td>{row.balance}</td><td>{row.share_percent === null ? '— (zero total)' : `${row.share_percent}%`}</td>
            </tr>)}</tbody>
          </table></div>
        </>}
      <details className="portfolio-explainer"><summary>Details</summary>
        <p>Sepolia testnet, no market value · {data.mode === 'simulated'
          ? 'Simulation — no live execution' : 'Live Sepolia'}.</p>
        {snapshotAgeSeconds !== undefined && <p>Snapshot age: {snapshotAgeSeconds}s. Refresh to fetch current balances.</p>}
        {network.status === 'available' && <p>Chain {network.chain_id} · As of block {network.block_number},{' '}
          <time dateTime={network.block_timestamp}>{new Date(network.block_timestamp!).toLocaleString()}</time>
          {' '}· Signer pending nonce: {network.pending_nonce}</p>}
        <p>Share means each wallet’s percentage of the same asset across watched wallets,
          not a valuation or a combined percentage of different tokens. Balances are exact.</p>
        <p>{budget.period} · {budget.date}. Database accounting; pending includes unresolved
          reservations from earlier days. Principal only, excludes gas. All existing policy
          restrictions still apply.</p>
      </details>
    </section>
    <section className="portfolio-section portfolio-payments" aria-labelledby="payments-title">
      <div className="portfolio-panel-heading"><h2 id="payments-title">Recent payments</h2>
        <span>{payments.length} payments</span></div>
      {payments.length === 0 ? <p>No recorded payments.</p> : <div className="portfolio-table-wrap">
        <table className="portfolio-table"><thead><tr>
          <th scope="col">Recipient</th><th scope="col">Status</th><th scope="col">Transaction</th><th scope="col">Amount</th></tr></thead>
          <tbody>{payments.map(payment => <tr key={payment.proposal_id}>
            <td>
              <details className="portfolio-identifier"><summary>{shortAddress(payment.recipient)}</summary>
                <span>{payment.recipient}</span></details></td><td>
              <span className={`portfolio-payment-state ${payment.status === 'CONFIRMED' ? 'is-confirmed' : ''}`}>
                {humanizeEvent(payment.status)}</span>
              {payment.lifecycle_status && payment.lifecycle_status !== payment.status &&
                <><br /><small>Stored state: {payment.lifecycle_status}</small></>}</td>
            <td>{payment.status !== 'SIMULATED' && payment.explorer_url
              ? <a href={payment.explorer_url} title={payment.tx_hash ?? undefined}
                  aria-label={`Transaction ${payment.tx_hash}`} target="_blank" rel="noopener noreferrer">{shortAddress(payment.tx_hash ?? '')}</a>
              : payment.status === 'SIMULATED' ? 'Simulated · not broadcast'
                : payment.tx_hash ? <details className="portfolio-identifier">
                  <summary>{shortAddress(payment.tx_hash)}</summary><span>{payment.tx_hash}</span>
                </details> : 'Unavailable'}</td>
            <td className="portfolio-payment-amount">{payment.amount_eth} ETH</td>
          </tr>)}</tbody></table></div>}
    </section>
    <aside className="portfolio-section portfolio-budget" aria-labelledby="budget-title">
      <div className="portfolio-panel-heading"><h2 id="budget-title">Policy budget</h2>
        <span>Policy v{budget.policy_version ?? 'unavailable'} · UTC day</span></div>
      <div className="portfolio-budget-limit"><span>Daily limit</span>
        <strong>{budget.daily_limit_eth === null ? 'Not configured' : `${budget.daily_limit_eth} ETH`}</strong></div>
      {budget.status !== 'available' ? <p>No active policy. Budget unavailable.</p> : <>
        {budget.daily_limit_eth !== null && <div className="portfolio-budget-bar" role="img"
          aria-label={`Budget: spent ${budget.spent_today_eth} ETH, pending ${budget.pending_eth} ETH, remaining ${budget.remaining_eth} ETH`}>
          <span className="portfolio-budget-spent" style={{ width: `${spent}%` }} />
          <span className="portfolio-budget-pending" style={{ width: `${pending}%` }} />
        </div>}
        <dl className="portfolio-budget-facts">
          <div><dt>Spent today</dt><dd>{budget.spent_today_eth} ETH</dd></div>
          <div><dt>Pending reservations</dt><dd>{budget.pending_eth} ETH</dd></div>
          <div><dt>Remaining</dt><dd>{ethAmount(budget.remaining_eth, 'Not bounded')}</dd></div>
          <div><dt>Auto-execution cap ({budget.auto_execute_enabled ? 'enabled' : 'disabled'})</dt>
            <dd>{budget.autonomous_cap_eth} ETH</dd></div>
          <div><dt>Approval threshold</dt><dd>{ethAmount(budget.escalation_threshold_eth, 'Not configured')}</dd></div>
          <div><dt>Absolute maximum</dt><dd>{ethAmount(budget.absolute_max_eth, 'Unavailable')}</dd></div>
        </dl>
      </>}
    </aside>
    </div>
  </div>;
}

export function PortfolioView({ refreshRevision }: { refreshRevision: number }) {
  const [{ data, error, refreshing, loadedAt }, dispatch] = useReducer(
    portfolioReadReducer, initialPortfolioRead,
  );
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    if (loadedAt === null) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [loadedAt]);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (cancelled) return;
      dispatch({ type: 'start' });
      api.getPortfolio(controller.signal).then(value => {
        if (!cancelled) dispatch({ type: 'success', data: value, at: Date.now() });
      }).catch(() => {
        if (!cancelled) dispatch({ type: 'failure',
          message: 'Portfolio unavailable. Check your connection and verified API role, then retry.' });
      });
    });
    return () => { cancelled = true; controller.abort(); };
  }, [refreshRevision]);
  return <div className="portfolio-content">
    {data && refreshing && <p className="required-role-note" role="status">
      Refreshing — showing stale snapshot · age {Math.max(0, Math.floor((clock - (loadedAt ?? clock)) / 1000))}s.
    </p>}
    {error ? <p role="alert">{error} Use Refresh to retry.</p> : data ? <PortfolioContent data={data}
      snapshotAgeSeconds={Math.max(0, Math.floor((clock - (loadedAt ?? clock)) / 1000))} />
      : <p role="status">Reading portfolio…</p>}
  </div>;
}
