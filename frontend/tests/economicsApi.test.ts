import assert from 'node:assert/strict';
import test from 'node:test';
import { api, KiteShieldAPIError } from '../src/api/client.ts';

const payload = {
  value_wei: '10000000000000001',
  estimated_gas: 21000,
  gas_price_gwei: '20.000000001',
  max_gas_price_gwei: '100',
};
const result = {
  ...payload,
  advisory_only: true,
  estimate_source: 'CALLER_SUPPLIED',
  is_economically_viable: true,
  gas_cost_wei: '420000000021000',
  gas_cost_eth: '0.000420000000021',
  gas_to_value_ratio: '0.0420',
  warnings: [],
};

test('fee check preserves exact amounts and uses the authenticated advisory endpoint only', async (context) => {
  api.setApiKey('synthetic-fee-test-key');
  const controller = new AbortController();
  const request = context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/v1/security/economic-check');
    assert.equal(options.method, 'POST');
    assert.equal((options.headers as Record<string, string>)['X-API-Key'], 'synthetic-fee-test-key');
    assert.equal(options.signal, controller.signal);
    assert.deepEqual(JSON.parse(options.body as string), payload);
    return Response.json({ data: result });
  });
  try {
    assert.deepEqual(await api.checkEconomics(payload, controller.signal), result);
    assert.equal(request.mock.callCount(), 1);
  } finally { api.setApiKey(''); }
});

test('high fees remain advisory warnings, not transaction decisions', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ data: {
    ...result, is_economically_viable: false, warnings: ['GAS_FEE_EXCEEDS_TRANSFER_VALUE'],
  } }));
  const response = await api.checkEconomics(payload);
  assert.equal(response.advisory_only, true);
  assert.equal(response.is_economically_viable, false);
  assert.deepEqual(response.warnings, ['GAS_FEE_EXCEEDS_TRANSFER_VALUE']);
});

test('zero-value calls retain an unavailable ratio', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => Response.json({ data: {
    ...result, value_wei: '0', gas_to_value_ratio: null, warnings: ['ZERO_VALUE_RATIO_UNAVAILABLE'],
  } }));
  assert.equal((await api.checkEconomics({ ...payload, value_wei: '0' })).gas_to_value_ratio, null);
});

test('failed and malformed fee checks never return a successful assessment', async (context) => {
  const request = context.mock.method(globalThis, 'fetch', async () => Response.json({ error: { code: 'INVALID_API_KEY', message: 'Invalid API key' } }, { status: 401 }));
  await assert.rejects(() => api.checkEconomics(payload), (err: unknown) => err instanceof KiteShieldAPIError && err.status === 401);
  for (const data of [null, {}, { ...result, advisory_only: false }, { ...result, gas_cost_wei: 123 }, { ...result, warnings: ['warning', null] }]) {
    request.mock.mockImplementation(async () => Response.json({ data }));
    await assert.rejects(() => api.checkEconomics(payload), (err: unknown) => err instanceof KiteShieldAPIError && err.code === 'INVALID_ECONOMIC_RESPONSE');
  }
});
