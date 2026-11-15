import { ArrowDownToLine, ArrowUpRight, BookOpen, Check, Circle, Clock3, Fingerprint, Play, RotateCcw, ShieldCheck, ShoppingBag } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { api } from '../api/client.ts';
import { weiToEth } from '../amounts.ts';
import { readableReason } from '../autonomy.ts';
import { commerceRequest, purchaseExplorer, type CommerceCatalog, type PurchaseOrder } from '../commerce.ts';
import './commerce.css';

const finished = new Set(['DELIVERED', 'BLOCKED', 'REJECTED', 'SIMULATED', 'FAILED', 'CANCELLED']);
const message = (error: unknown) => error instanceof Error ? error.message : 'Purchase status unavailable. Check the order before retrying.';

export function CommerceView() {
  const roles = useSyncExternalStore(api.subscribeCredentials, api.getConnectedRoles, api.getServerConnectedRoles);
  const connected = roles.includes('proposer');
  const [catalog, setCatalog] = useState<CommerceCatalog | null>(null);
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [refreshError, setRefreshError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState<{ order_id: string; goal: string; scenario?: string } | null>(null);
  const generation = useRef(0);
  const locked = useRef(false);
  const [revision, setRevision] = useState(0);
  const order = orders.find(item => item.id === selectedId) ?? orders[0];
  const update = useCallback((next: PurchaseOrder) => {
    setOrders(previous => [next, ...previous.filter(item => item.id !== next.id)]);
    setSelectedId(next.id);
  }, []);

  useEffect(() => {
    if (!connected) return;
    let active = true;
    let reading = false;
    async function load() {
      if (reading) return;
      reading = true;
      const started = generation.current;
      try {
        const [nextCatalog, result] = await Promise.all([
          commerceRequest<CommerceCatalog>('/catalog'),
          commerceRequest<{ orders: PurchaseOrder[] }>('/orders'),
        ]);
        if (active && generation.current === started) {
          setCatalog(nextCatalog);
          setGoal(previous => previous || nextCatalog.goal);
          setOrders(result.orders);
          setRefreshError('');
        }
      } catch (failure) { if (active && generation.current === started) setRefreshError(message(failure)); }
      finally { reading = false; }
    }
    void load();
    const timer = setInterval(() => void load(), 2000);
    return () => { active = false; clearInterval(timer); };
  }, [connected, revision]);

  async function purchase(scenario: 'standard' | 'tampered') {
    if (locked.current || !catalog) return;
    locked.current = true;
    generation.current += 1;
    setBusy(true); setError(''); setNotice('');
    const request = pending ?? { order_id: crypto.randomUUID(), goal: catalog.goal, scenario };
    setPending(request);
    try {
      const result = await commerceRequest<PurchaseOrder>('/orders', request);
      update(result);
      setPending(null);
      setNotice(result.state === 'BLOCKED' ? 'Changed checkout rejected before payment.' : 'Purchase recorded.');
      setRevision(value => value + 1);
    } catch (failure) { setError(message(failure)); }
    finally { locked.current = false; setBusy(false); }
  }
  async function retrieve(id: string) {
    if (locked.current || pending) return;
    locked.current = true; generation.current += 1; setBusy(true); setError('');
    try { update(await commerceRequest<PurchaseOrder>(`/orders/${encodeURIComponent(id)}`)); setNotice('Existing order retrieved.'); }
    catch (failure) { setError(message(failure)); }
    finally { locked.current = false; setBusy(false); }
  }
  function download() {
    if (!order?.delivered || !order.artifact || order.mode !== 'SEPOLIA') return;
    const blob = new Blob([order.artifact.content], { type: order.artifact.mime_type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = order.artifact.name; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const deliveryEvents = new Set(['PAYMENT_VERIFIED', 'PRODUCT_DELIVERED']);
  const events = order ? [
    ...order.events.filter(event => !deliveryEvents.has(event.kind)),
    ...(order.task?.events ?? []),
    ...order.events.filter(event => deliveryEvents.has(event.kind)),
  ] : [];
  const explorer = order ? purchaseExplorer(order) : null;
  const canStart = connected && catalog?.ready && !busy && (!order || finished.has(order.state));
  const waiting = !!order && !finished.has(order.state) && !order.delivered;
  const status = order?.delivered ? 'Delivered' : order ? readableReason(order.state) : 'Ready to purchase';

  return <section className="commerce-workspace" aria-label="Autonomous purchase">
    <div className="commerce-heading">
      <div><h2>From instruction to delivery.</h2><p>One purchase. A verified payment. Your product.</p></div>
      <span className="commerce-mode"><span />{!catalog ? 'Checking connection' : catalog.mode === 'SEPOLIA' ? 'Sepolia test ETH' : 'Simulation'}</span>
    </div>
    {!connected && <p className="commerce-message">Connect Admin to open the shop.</p>}
    {(error || refreshError) && <div className="commerce-message" role="alert"><span>{error || refreshError}</span><button className="btn btn-outline" onClick={() => setRevision(value => value + 1)}>Refresh status</button></div>}
    <form className="commerce-mission" onSubmit={event => { event.preventDefault(); void purchase('standard'); }}>
      <label htmlFor="purchase-goal">Your instruction</label>
      <div><textarea id="purchase-goal" rows={2} maxLength={500} required value={goal} readOnly placeholder="Buy the developer report from the approved shop…" />
        <button className="btn btn-primary" disabled={(!canStart && !pending) || busy || !connected || !catalog?.ready}>
          {busy ? <Clock3 size={16} /> : <Play size={16} />} {pending ? 'Retry purchase' : 'Start purchase'}
        </button></div>
      {catalog && !catalog.ready && <p>{readableReason(catalog.reason || 'Administrator setup required')}. Open Agent controls to review the session.</p>}
      {notice && <p role="status">{notice}</p>}
    </form>
    <div className="commerce-panels">
      <section className="commerce-card commerce-shop" aria-label="Digital shop">
        <header><ShoppingBag size={17} /><h3>The shop</h3><span>Digital edition</span></header>
        <div className="commerce-book" aria-label="Developer field guide cover">
          <div className="commerce-book-line" /><span>KiteShield Editions</span><strong>Developer<br />field guide</strong>
          <svg viewBox="0 0 240 110" fill="none" aria-hidden="true"><path d="M20 90L70 25L120 70L170 15L220 50" stroke="currentColor" strokeWidth="2" /><path d="M20 90H220M70 25V90M120 70V90M170 15V90M220 50V90" stroke="currentColor" strokeOpacity=".25" />{[[20,90],[70,25],[120,70],[170,15],[220,50]].map(([x,y]) => <circle key={x} cx={x} cy={y} r="4" fill="currentColor" />)}</svg>
          <small>Systems • payments • reliable agents</small>
        </div>
        <div className="commerce-product"><h4>{catalog?.product.name || 'Developer field guide'}</h4><p>{catalog?.product.description || 'A downloadable guide from your approved merchant.'}</p></div>
        <dl className="commerce-facts">
          <div><dt>Merchant</dt><dd>{order?.merchant?.name || catalog?.merchant?.name || 'Awaiting mandate'}</dd></div>
          <div><dt>Product</dt><dd>{weiToEth(catalog?.product.price_wei || '10000000000000')} ETH</dd></div>
          <div><dt>Optional extras</dt><dd>None</dd></div>
          <div className="commerce-total"><dt>Total</dt><dd>{weiToEth(order?.quote.total_wei || catalog?.product.price_wei || '10000000000000')} ETH</dd></div>
        </dl>
        <p className="commerce-caption">Network fees are bounded separately by your wallet settings.</p>
      </section>
      <section className="commerce-card commerce-activity" aria-label="Persisted purchase activity">
        <header><Fingerprint size={17} /><h3>Agent activity</h3><span className="commerce-state" data-success={order?.delivered}>{status}</span></header>
        {order ? <>
          <div className="commerce-order-label">Order <span>{order.id.slice(0, 8)}</span>{waiting && <Clock3 size={14} />}</div>
          <ol className="commerce-timeline" aria-live="polite" aria-relevant="additions">
            {events.map((event, index) => <li key={`${index}-${event.id}`}><span className="commerce-event-dot" data-blocked={event.kind.includes('BLOCKED')}>{event.kind.includes('BLOCKED') ? <ShieldCheck size={12} /> : <Check size={12} />}</span><div><strong>{readableReason(event.kind)}</strong><p>{eventDetail(event.detail)}</p></div></li>)}
            {!events.length && <li><span className="commerce-event-dot"><Circle size={12} /></span><div><strong>Order recorded</strong><p>Waiting for the next persisted event.</p></div></li>}
          </ol>
          {order.reason && <div className="commerce-reason"><ShieldCheck size={17} /><span>{readableReason(order.reason)}</span></div>}
          <button className="btn btn-outline commerce-retry" disabled={busy || !!pending} onClick={() => void retrieve(order.id)}><RotateCcw size={14} /> Retrieve same order</button>
        </> : <div className="commerce-awaiting"><Fingerprint size={28} /><h4>Your agent is ready</h4><p>Start the purchase to follow each recorded decision here.</p></div>}
      </section>
      <section className="commerce-card commerce-result" aria-label="Purchase result">
        <header><BookOpen size={17} /><h3>Your purchase</h3></header>
        <div className={`commerce-delivery${order?.delivered ? ' is-delivered' : ''}`}>
          {order?.delivered ? <Check size={28} /> : <ArrowDownToLine size={28} />}
          <h4>{order?.delivered ? 'Ready to open' : order?.state === 'SIMULATED' ? 'Simulation completed' : 'Delivery follows verification'}</h4>
          <p>{order?.delivered ? 'Payment verified. Your field guide is unlocked.' : 'The shop releases the file after a matching Sepolia payment.'}</p>
          <button className="btn btn-primary" disabled={!order?.delivered || !order.artifact} onClick={download}><ArrowDownToLine size={15} /> Download field guide</button>
        </div>
        {order && <dl className="commerce-facts commerce-invoice"><div><dt>Invoice</dt><dd>{order.invoice.number}</dd></div><div><dt>Status</dt><dd>{readableReason(order.invoice.status)}</dd></div><div><dt>Total</dt><dd>{weiToEth(order.invoice.total_wei)} ETH</dd></div></dl>}
        {explorer && <a className="commerce-receipt" href={explorer} target="_blank" rel="noopener noreferrer">View Sepolia receipt <ArrowUpRight size={14} /></a>}
        <div className="commerce-challenge"><ShieldCheck size={18} /><h4>Challenge the checkout</h4><p>Submit a changed price and see the spending boundary enforced.</p><button className="btn btn-outline" disabled={!catalog?.ready || busy || !!pending || waiting} onClick={() => void purchase('tampered')}>Try a changed price</button></div>
      </section>
    </div>
    {!!orders.length && <nav className="commerce-history" aria-label="Purchase history">{orders.slice(0, 6).map(item => <button key={item.id} aria-current={order?.id === item.id ? 'true' : undefined} onClick={() => setSelectedId(item.id)}><span>{item.id.slice(0, 8)}</span>{item.delivered ? 'Delivered' : readableReason(item.state)}</button>)}</nav>}
  </section>;
}

function eventDetail(detail: string): string {
  if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(detail)) return 'Saved payment workflow attached to this order.';
  if (/^0x[0-9a-f]{64}$/i.test(detail)) return 'Payment evidence saved with this purchase.';
  try {
    const result = JSON.parse(detail);
    if (result.tool === 'fund' && result.skipped) return 'Balance sufficient. Funding skipped.';
    if (result.verified) return 'Matching payment receipt verified.';
    if (typeof result.tool === 'string') return readableReason(result.tool);
    return 'Recorded by the purchase workflow.';
  } catch { return detail.length > 180 ? detail.slice(0, 177) + '…' : detail; }
}
