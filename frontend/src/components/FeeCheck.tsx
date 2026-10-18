import React, { useEffect, useId, useRef, useState } from 'react';
import { api } from '../api/client.ts';
import type { EconomicCheckResult } from '../types/index.ts';

const warningLabels: Record<string, string> = {
  GAS_PRICE_ABOVE_CEILING: 'The gas price exceeds your warning threshold.',
  GAS_FEE_EXCEEDS_TRANSFER_VALUE: 'The estimated gas fee exceeds the transfer amount.',
  HIGH_GAS_TO_VALUE_RATIO: 'The estimated gas fee exceeds half the transfer amount.',
  ZERO_VALUE_RATIO_UNAVAILABLE: 'A fee-to-transfer ratio is unavailable for a zero-value transaction.',
};

export const FeeCheck: React.FC<{ valueWei: string }> = ({ valueWei }) => {
  const id = useId();
  const [gasUnits, setGasUnits] = useState('');
  const [gasPrice, setGasPrice] = useState('');
  const [ceiling, setCeiling] = useState('100');
  const [result, setResult] = useState<EconomicCheckResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);

  useEffect(() => () => { request.current?.abort(); }, []);

  const invalidate = () => {
    request.current?.abort();
    request.current = null;
    setResult(null);
    setError(null);
    setLoading(false);
  };

  const calculate = async (event: React.FormEvent) => {
    event.preventDefault();
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.checkEconomics({
        value_wei: valueWei,
        estimated_gas: Number(gasUnits),
        gas_price_gwei: gasPrice,
        max_gas_price_gwei: ceiling,
      }, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
      if (request.current === controller && !controller.signal.aborted) setResult(data);
    } catch (err: unknown) {
      if (request.current === controller && !controller.signal.aborted) setError(err instanceof Error ? err.message : 'Unable to check fees. Retry.');
    } finally {
      if (request.current === controller && !controller.signal.aborted) setLoading(false);
    }
  };

  return <section className="fee-check" aria-labelledby={id + '-title'}>
    <h3 id={id + '-title'}>Estimated fees</h3>
    <p className="fee-check-description">Enter your own gas estimates. This calculator does not fetch live network fees or change the transaction.</p>
    <form onSubmit={calculate}>
      <div className="fee-check-fields">
        <label htmlFor={id + '-units'}>Estimated gas units
          <input id={id + '-units'} type="number" min="1" max="30000000" step="1" required value={gasUnits}
            onChange={(event) => { invalidate(); setGasUnits(event.target.value); }} />
        </label>
        <label htmlFor={id + '-price'}>Gas price (Gwei)
          <input id={id + '-price'} type="number" min="0" max="1000000000" step="0.000000001" required value={gasPrice}
            onChange={(event) => { invalidate(); setGasPrice(event.target.value); }} />
        </label>
        <label htmlFor={id + '-ceiling'}>Warning threshold (Gwei)
          <input id={id + '-ceiling'} type="number" min="0" max="1000000000" step="0.000000001" required value={ceiling}
            onChange={(event) => { invalidate(); setCeiling(event.target.value); }} />
        </label>
      </div>
      <button type="submit" className="btn btn-outline" disabled={loading}>{loading ? 'Calculating…' : 'Check estimated fees'}</button>
    </form>
    {loading && <p className="fee-check-description" role="status">Calculating from your supplied estimates…</p>}
    {error && <p className="audit-error" role="alert">{error}</p>}
    {result && <div className="fee-check-result" role="status">
      <dl className="audit-facts">
        <dt>Estimated gas fee</dt><dd><strong>{result.gas_cost_eth} ETH</strong><span className="fee-check-exact">{result.gas_cost_wei} wei</span></dd>
        <dt>Fee / transfer amount</dt><dd>{result.gas_to_value_ratio === null ? 'Unavailable for a zero-value transfer' : result.gas_to_value_ratio + '×'}</dd>
        <dt>Fee assessment</dt><dd>{result.is_economically_viable ? 'Within fee limits for these estimates' : 'Potentially uneconomic — review fees'}</dd>
      </dl>
      {result.warnings.length > 0 && <ul className="fee-check-warnings">{result.warnings.map((warning) => <li key={warning}>{warningLabels[warning] || 'An additional fee warning was returned. Review your estimates.'}</li>)}</ul>}
      <p className="fee-check-description">Advisory only. Policy evaluation and any required approvals still apply.</p>
    </div>}
  </section>;
};
