/** Read-only live check: no database writes, messages, or plaintext output. */
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../.env') });
const DouyinModule = require('../src/modules/douyin');
const { collectEncryptedValues, applyDecryptedValues } = require('../src/modules/douyin/sensitive-fields');

async function main() {
  const douyin = new DouyinModule();
  const report = { checkedAt: new Date().toISOString(), token: {}, accounts: [] };
  const [accountId, orderId] = process.argv.slice(2);
  const accounts = accountId ? [{ accountId }] : require('../data/accounts.json').filter(a => a.enabled);
  try {
    const first = await douyin.api.getAccessToken();
    const cached = await douyin.api.getAccessToken();
    report.token = { status: 'passed', cacheReused: first === cached, ...douyin.api.getTokenStatus() };
  } catch (e) {
    report.token = { status: 'failed', message: e.message };
    process.exitCode = 1;
    console.log(JSON.stringify(report, null, 2));
    return;
  }
  for (const account of accounts) {
    const result = { accountId: account.accountId, list: 'not_reached', detail: 'not_reached', phone: 'not_reached' };
    let stage = 'list';
    try {
      const { orders } = await douyin.api.queryOrders({ accountId: account.accountId, pageSize: 10 });
      result.list = 'passed';
      result.orderCount = orders.length;
      const selected = orderId || orders.find(o => collectEncryptedValues(o).length)?.order_id || orders[0]?.order_id;
      if (!selected) {
        result.detail = result.phone = 'no_sample';
        process.exitCode = 2;
        continue;
      }
      stage = 'detail';
      const order = await douyin.getOrderDetail(selected, account.accountId);
      if (!order) throw new Error('订单详情为空');
      result.detail = 'passed';
      stage = 'phone';
      const encrypted = collectEncryptedValues(order);
      result.encryptedFieldCount = encrypted.length;
      if (encrypted.length) {
        const mapping = await douyin.decryptFields(encrypted, account.accountId, { strict: true });
        applyDecryptedValues(order, mapping);
      }
      result.phoneStatus = douyin.extractOrderFields(order).customerPhoneStatus;
      result.phone = result.phoneStatus === 'available'
        ? (encrypted.length ? 'passed' : 'plaintext_no_decrypt_sample') : 'unavailable';
      if (result.phone !== 'passed') process.exitCode = process.exitCode || 2;
    } catch (e) {
      result[stage] = 'failed';
      result.error = e.toJSON ? e.toJSON() : { message: e.message };
      process.exitCode = 1;
    } finally {
      report.accounts.push(result);
    }
  }
  if (!accounts.length) process.exitCode = 2;
  console.log(JSON.stringify(report, null, 2));
}

main().catch(e => { console.error(e.message); process.exitCode = 1; });
