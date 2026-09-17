/**
 * 抖音完整链路脚本
 * 从 access_token -> 订单列表 -> 订单详情 的完整流程
 *
 * 使用方法:
 * 1. 查询指定商户的所有订单:
 *    node src/douyin-flow.js list <商户账户ID>
 *
 * 2. 查询指定订单详情:
 *    node src/douyin-flow.js detail <订单ID> <商户账户ID>
 *
 * 3. 批量提取订单信息:
 *    node src/douyin-flow.js batch <商户账户ID> [数量]
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');
const logger = require('./utils/logger');

const douyin = new DouyinModule();

/**
 * 步骤1: 获取 access_token
 */
async function step1_getAccessToken() {
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('步骤 1/3: 获取 access_token');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  try {
    const token = await douyin.api.getAccessToken();
    console.log('✅ access_token 获取成功');
    console.log('   Token:', token.substring(0, 30) + '...');
    console.log('   过期时间:', new Date(douyin.api.tokenExpireTime).toLocaleString());
    return token;
  } catch (error) {
    console.error('❌ 获取 access_token 失败:', error.message);
    throw error;
  }
}

/**
 * 步骤2: 查询订单列表
 */
async function step2_getOrderList(token, accountId, pageSize = 20) {
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('步骤 2/3: 查询订单列表');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  console.log('参数:');
  console.log('   商户ID:', accountId);
  console.log('   每页数量:', pageSize);
  console.log('');

  try {
    const axios = require('axios');
    const response = await axios.get(
      'https://open.douyin.com/goodlife/v1/trade/order/query/',
      {
        headers: {
          'access-token': token,
          'content-type': 'application/json',
        },
        params: {
          account_id: accountId,
          page_num: 1,
          page_size: pageSize,
        },
      }
    );

    if (response.data.extra.error_code !== 0) {
      throw new Error(
        `API错误: ${response.data.extra.description} (${response.data.extra.error_code})`
      );
    }

    const orders = response.data.data.orders || [];
    console.log(`✅ 查询成功,共 ${orders.length} 个订单\n`);

    return orders;
  } catch (error) {
    console.error('❌ 查询订单列表失败:', error.message);
    throw error;
  }
}

/**
 * 步骤3: 查询订单详情并提取字段
 */
async function step3_getOrderDetail(orderId, accountId) {
  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('步骤 3/3: 查询订单详情');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  console.log('参数:');
  console.log('   订单ID:', orderId);
  console.log('   商户ID:', accountId);
  console.log('');

  try {
    const order = await douyin.getOrderDetail(orderId, accountId);

    if (!order) {
      throw new Error('订单不存在或查询失败');
    }

    const extracted = douyin.extractOrderFields(order, {});

    console.log('✅ 订单详情查询成功\n');

    return extracted;
  } catch (error) {
    console.error('❌ 查询订单详情失败:', error.message);
    throw error;
  }
}

/**
 * 打印订单信息
 */
function printOrderInfo(orderData) {
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('📋 订单信息');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  console.log('1️⃣  客户手机号:', orderData.customerPhone);
  console.log('2️⃣  下单时间:', orderData.orderTime);
  console.log('3️⃣  团购名称:', orderData.productName);
  console.log('    团购ID:', orderData.productId);
  console.log('4️⃣  下单价格:', orderData.orderPrice, '元');
  console.log('    实付金额:', orderData.actualPrice, '元');
  console.log('5️⃣  店铺名称:', orderData.shopName);
  console.log('    店铺ID:', orderData.shopId);
  console.log('');
  console.log('其他信息:');
  console.log('    订单ID:', orderData.orderId);
  console.log('    订单状态:', orderData.orderStatus);
  console.log('    购买数量:', orderData.quantity);
  console.log('    订单来源:', orderData.orderSource);
  console.log('    销售渠道:', orderData.saleChannel);
  console.log('');
}

/**
 * 命令: 查询订单列表
 */
async function commandList(accountId, pageSize = 20) {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   抖音订单列表查询                     ║');
  console.log('╚════════════════════════════════════════╝');

  await douyin.init();
  const token = await step1_getAccessToken();
  const orders = await step2_getOrderList(token, accountId, pageSize);

  console.log('订单列表:\n');
  orders.forEach((order, index) => {
    console.log(`${index + 1}. 订单ID: ${order.order_id}`);
    console.log(`   状态: ${douyin._getOrderStatusText(order.order_status)}`);
    console.log(`   时间: ${new Date(order.create_order_time * 1000).toLocaleString()}`);
    console.log(`   商品: ${order.products?.[0]?.product_name || order.sku_name || '未知'}`);
    console.log(`   金额: ${(order.pay_amount / 100).toFixed(2)} 元`);
    console.log('');
  });

  console.log(`\n总计: ${orders.length} 个订单\n`);
}

/**
 * 命令: 查询订单详情
 */
async function commandDetail(orderId, accountId) {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   抖音订单详情查询                     ║');
  console.log('╚════════════════════════════════════════╝');

  await douyin.init();
  const token = await step1_getAccessToken();
  // 验证token可用
  await step2_getOrderList(token, accountId, 1);
  const orderData = await step3_getOrderDetail(orderId, accountId);

  printOrderInfo(orderData);

  console.log('JSON格式:\n');
  console.log(JSON.stringify(orderData, null, 2));
  console.log('');
}

/**
 * 命令: 批量提取订单信息
 */
async function commandBatch(accountId, count = 5) {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   批量提取订单信息                     ║');
  console.log('╚════════════════════════════════════════╝');

  await douyin.init();
  const token = await step1_getAccessToken();
  const orders = await step2_getOrderList(token, accountId, count);

  console.log(`开始提取前 ${Math.min(count, orders.length)} 个订单的详细信息...\n`);

  const results = [];

  for (let i = 0; i < Math.min(count, orders.length); i++) {
    const order = orders[i];
    console.log(`[${i + 1}/${Math.min(count, orders.length)}] 正在查询订单: ${order.order_id}`);

    try {
      const orderData = await step3_getOrderDetail(order.order_id, accountId);
      results.push(orderData);
      console.log('   ✅ 成功\n');
    } catch (error) {
      console.error(`   ❌ 失败: ${error.message}\n`);
    }

    // 避免频繁请求,间隔500ms
    if (i < Math.min(count, orders.length) - 1) {
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  }

  console.log('\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  console.log('📊 批量提取结果');
  console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');

  results.forEach((orderData, index) => {
    console.log(`订单 ${index + 1}:`);
    console.log(`  客户: ${orderData.customerPhone}`);
    console.log(`  时间: ${orderData.orderTime}`);
    console.log(`  商品: ${orderData.productName}`);
    console.log(`  金额: ${orderData.actualPrice} 元`);
    console.log('');
  });

  console.log(`成功提取: ${results.length}/${Math.min(count, orders.length)} 个订单\n`);

  // 保存到文件
  const fs = require('fs');
  const outputFile = `orders_${accountId}_${Date.now()}.json`;
  fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));
  console.log(`已保存到文件: ${outputFile}\n`);
}

/**
 * 主函数
 */
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command) {
    console.log('\n抖音完整链路脚本');
    console.log('═══════════════════════════════════════\n');
    console.log('使用方法:\n');
    console.log('1. 查询订单列表:');
    console.log('   node src/douyin-flow.js list <商户账户ID> [每页数量]\n');
    console.log('2. 查询订单详情:');
    console.log('   node src/douyin-flow.js detail <订单ID> <商户账户ID>\n');
    console.log('3. 批量提取订单:');
    console.log('   node src/douyin-flow.js batch <商户账户ID> [数量]\n');
    console.log('示例:\n');
    console.log('   node src/douyin-flow.js list 7523898493467904038');
    console.log('   node src/douyin-flow.js detail 1086675889370262734 7523898493467904038');
    console.log('   node src/douyin-flow.js batch 7523898493467904038 10\n');
    process.exit(0);
  }

  try {
    switch (command) {
      case 'list':
        if (!args[1]) {
          console.error('❌ 缺少参数: 商户账户ID');
          process.exit(1);
        }
        await commandList(args[1], parseInt(args[2]) || 20);
        break;

      case 'detail':
        if (!args[1] || !args[2]) {
          console.error('❌ 缺少参数: 订单ID 和 商户账户ID');
          process.exit(1);
        }
        await commandDetail(args[1], args[2]);
        break;

      case 'batch':
        if (!args[1]) {
          console.error('❌ 缺少参数: 商户账户ID');
          process.exit(1);
        }
        await commandBatch(args[1], parseInt(args[2]) || 5);
        break;

      default:
        console.error(`❌ 未知命令: ${command}`);
        console.log('可用命令: list, detail, batch');
        process.exit(1);
    }

    console.log('✅ 执行完成\n');
  } catch (error) {
    console.error('\n❌ 执行失败:', error.message);
    process.exit(1);
  }
}

main();
