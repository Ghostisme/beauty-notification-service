/**
 * 调试脚本 - 查看完整订单数据结构
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');

const douyin = new DouyinModule();

async function main() {
  await douyin.init();

  const orderId = '1086675889370262734';
  const accountId = '7523898493467904038';

  const order = await douyin.getOrderDetail(orderId, accountId);

  console.log('\n完整订单数据结构:\n');
  console.log(JSON.stringify(order, null, 2));
}

main();
