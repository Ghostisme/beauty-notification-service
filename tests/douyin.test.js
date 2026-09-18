const test = require('node:test');
const assert = require('node:assert/strict');
const TokenManager = require('../src/modules/douyin/token-manager');
const HttpClient = require('../src/modules/douyin/http-client');
const OrderQuery = require('../src/modules/douyin/order-query');
const { DouyinAPIError } = require('../src/modules/douyin/errors');
const { collectEncryptedValues, applyDecryptedValues } = require('../src/modules/douyin/sensitive-fields');
const DouyinModule = require('../src/modules/douyin');

test('token manager caches and refreshes concurrently without duplicate calls', async () => {
  const token = new TokenManager({ clientKey: 'k', clientSecret: 's', refreshAdvanceSeconds: 300 });
  let calls = 0;
  token._refresh = async () => { calls++; return token._acceptToken({ data: { access_token: `t${calls}`, expires_in: 7200 } }); };
  const values = await Promise.all(Array.from({ length: 20 }, () => token.getToken()));
  assert.equal(calls, 1); assert.ok(values.every(v => v === 't1'));
  assert.equal(await token.getToken(), 't1');
  assert.equal(calls, 1);
  assert.equal(token.invalidate('stale'), false);
  assert.equal(await token.getToken(), 't1');
  token.invalidate('t1');
  assert.equal(await token.getToken(), 't2'); assert.equal(calls, 2);
});

test('HTTP client retries token errors once and does not retry IP whitelist errors', async () => {
  const token = new TokenManager({ clientKey: 'k', clientSecret: 's' });
  let issued = 0; token.getToken = async ({ forceRefresh } = {}) => forceRefresh ? `fresh${++issued}` : (issued ? `fresh${issued}` : `old`);
  const client = new HttpClient(token, { minRequestInterval: 0, retryBaseDelay: 0 });
  let calls = 0;
  const axios = require('axios'); const original = axios.request;
  axios.request = async ({ headers }) => { calls++; if (calls === 1) return { data: { extra: { error_code: 2190002, description: 'expired' } } }; return { data: { extra: { error_code: 0 }, data: { ok: true } } }; };
  try { assert.deepEqual(await client.get('/x'), { ok: true }); assert.equal(calls, 2); }
  finally { axios.request = original; }
  assert.throws(() => client._unwrap({ extra: { error_code: 2119013, description: 'IP' } }, '/x'),
    (error) => error instanceof DouyinAPIError && error.errorCode === 2119013 && !error.retryable);
});

test('order query validates IDs/time ranges and prevents cursor loops', async () => {
  const calls = []; const http = { get: async (_p, params) => { calls.push(params); return { orders: Array.from({ length: 20 }, (_, i) => ({ order_id: String(i) })), search_after: { CursorValue: ['a'] }, page: {} }; } };
  const q = new OrderQuery(http);
  await assert.rejects(() => q.queryPage({ accountId: '123', createTimeStart: 1 }), /时间区间/);
  await assert.rejects(() => q.queryByOrderId(123, '123'), /orderId/);
  await assert.rejects(async () => { for await (const _ of q.iterate({ accountId: '123', cursor: 'a', maxPages: 2 })) {} }, /重复游标/);
  assert.equal(calls.length, 1);
});

test('sensitive fields are collected and applied in place; phone status distinguishes masked values', () => {
  const order = { contacts: [{ phone: 'Enc.phone' }], buyer_info: { buyer_real_phone: 'Enc.phone' } };
  assert.deepEqual(collectEncryptedValues(order), ['Enc.phone']);
  assert.equal(applyDecryptedValues(order, { 'Enc.phone': '13800138000' }), 2);
  const module = new DouyinModule({ minRequestInterval: 0 });
  const extracted = module.extractOrderFields(order);
  assert.equal(extracted.customerPhone, '13800138000'); assert.equal(extracted.customerPhoneStatus, 'available');
});
