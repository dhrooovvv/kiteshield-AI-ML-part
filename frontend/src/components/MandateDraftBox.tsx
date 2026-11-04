import { useState } from 'react';
import { api } from '../api/client.ts';
import type { MandateDraftResult } from '../mandateDraft.ts';

export function MandateDraftBox({ disabled, onApply }: {
  disabled: boolean; onApply: (draft: MandateDraftResult) => void;
}) {
  const [instruction, setInstruction] = useState('');
  const [result, setResult] = useState<MandateDraftResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [applied, setApplied] = useState(false);
  async function draft() {
    setBusy(true); setError(''); setResult(null); setApplied(false);
    try { setResult(await api.draftTreasuryMandate(instruction)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Draft unavailable'); }
    finally { setBusy(false); }
  }
  return <section className="treasury-draft" aria-label="Draft a mandate from instructions">
    <h3>Draft from instructions</h3>
    <p>Draft only. Nothing is saved or enabled. Use a configured recipient alias, never an address.</p>
    <label htmlFor="mandate-instruction">Treasury instruction</label>
    <textarea id="mandate-instruction" maxLength={2000} rows={3} value={instruction}
      disabled={disabled || busy} onChange={e => { setInstruction(e.target.value); setResult(null); setApplied(false); }}
      placeholder="Keep 0.04 ETH available, move excess to my saved treasury address, and make no more than three transfers daily." />
    <button type="button" className="btn btn-outline" disabled={disabled || busy || !instruction.trim()}
      onClick={() => void draft()}>{busy ? 'Interpreting…' : 'Generate draft'}</button>
    {error && <p role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <strong>{result.status.replaceAll('_', ' ')} · {result.source}</strong>
      {[...result.validation, ...result.questions, ...result.warnings].map((text, i) => <p key={i}>{text}</p>)}
      {result.status === 'draft' && result.draft && <>
        <dl><dt>Target</dt><dd>{result.draft.target_balance_eth} ETH</dd>
          <dt>Recipient alias</dt><dd>{result.draft.recipient_alias}</dd>
          <dt>Resolved destination</dt><dd><code>{result.resolved_recipient}</code></dd>
          <dt>Maximum actions per UTC day</dt><dd>{result.draft.max_actions_per_day}</dd></dl>
        <button type="button" className="btn btn-outline" disabled={disabled || busy || !result.resolved_recipient}
          onClick={() => { onApply(result); setApplied(true); }}>Use these values</button>
        <p role="status">{applied ? 'Values filled in below. Review them, then save the mandate. Nothing has been saved or enabled.' : 'Use these values to fill the form below. Missing limits must be entered before saving.'}</p>
      </>}
    </div>}
  </section>;
}
