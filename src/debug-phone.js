/**
 * 调试脚本 - 查看订单中手机号的原始格式
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');

const douyin = new DouyinModule();

async function main() {
  await douyin.init();

  const accountId = '7605435122824890377'; // 超柔皮肤定制管理
  const orderId = '1091962674194265394'; // 第一个订单

  const order = await douyin.getOrderDetail(orderId, accountId);

  console.log('\n=== 订单中的联系人信息 ===\n');
  console.log('contacts:', JSON.stringify(order.contacts, null, 2));

  if (order.contacts && order.contacts[0]) {
    const phone = order.contacts[0].phone;
    console.log('\n手机号原始值:', phone);
    console.log('是否加密(Enc.开头):', phone.startsWith('Enc.'));
    console.log('手机号长度:', phone.length);
  }

  console.log('\n=== 完整订单数据 ===\n');
  console.log(JSON.stringify(order, null, 2));
}

main();
