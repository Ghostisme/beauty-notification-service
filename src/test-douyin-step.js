/**
 * 抖音模块分步测试
 * 先测试access_token,再测试订单查询
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');
const logger = require('./utils/logger');

const douyin = new DouyinModule();
const OrderProcessor = require('./modules/douyin/order-processor');
const processor = new OrderProcessor(douyin);

// 你的商户账户ID
const ACCOUNT_ID = '7523898493467904038';

/**
 * 步骤1: 测试获取access_token
 */
async function step1_testAccessToken() {
  console.log('\n========================================');
  console.log('步骤1: 测试获取 access_token');
  console.log('========================================\n');

  console.log('配置信息:');
  console.log('  CLIENT_KEY:', process.env.DOUYIN_CLIENT_KEY || '未配置');
  console.log('  CLIENT_SECRET:', process.env.DOUYIN_CLIENT_SECRET ? '已配置(隐藏)' : '未配置');
  console.log('');

  try {
    console.log('正在调用接口...');
    const token = await douyin.api.getAccessToken();

    console.log('\n✅ access_token 获取成功!\n');
    console.log('Token信息:');
    console.log('  Token长度:', token.length);
    // 过期时间由 TokenManager 统一维护,不再从 api 实例上读裸属性
    console.log('  Token状态:', douyin.api.getTokenStatus());
    console.log('');

    return token;
  } catch (error) {
    console.error('\n❌ 获取 access_token 失败!\n');
    console.error('错误信息:', error.message);
    if (error.response?.data) {
      console.error('API返回:', JSON.stringify(error.response.data, null, 2));
    }
    console.error('');
    throw error;
  }
}

/**
 * 步骤2: 测试查询订单列表(不指定订单ID)
 *
 * 走 api.queryOrders 而非自己发请求:token 注入、频控节流、错误码判定与
 * 处置指引(如 2119013 的 IP 白名单提示)都在统一请求层里,自己拼 axios 会全部丢掉。
 * 因此这里也不再需要 token 实参 —— 凭证由 TokenManager 按需取用。
 */
async function step2_testOrderList(accountId) {
  console.log('\n========================================');
  console.log('步骤2: 查询订单列表');
  console.log('========================================\n');

  console.log('请求参数:');
  console.log('  account_id:', accountId);
  console.log('  page_num: 1');
  console.log('  page_size: 10');
  console.log('');

  try {
    console.log('正在调用订单查询API...');

    const { orders, page } = await douyin.api.queryOrders({
      accountId,
      pageNum: 1,
      pageSize: 10,
    });

    console.log('\n✅ API调用成功!\n');
    console.log('响应信息:');
    console.log('  本页订单数:', orders.length);
    console.log('  订单总数:', page.total);
    console.log('');

    if (orders.length === 0) {
      console.log('⚠️  没有查询到订单');
      console.log('');
      console.log('可能原因:');
      console.log('  1. 该商户下没有订单');
      console.log('  2. 应用未获得商户授权');
      console.log('  3. 账户ID不正确');
      console.log('');
      return null;
    }

    console.log('📦 查询到的订单列表:\n');
    orders.forEach((order, index) => {
      console.log(`订单 ${index + 1}:`);
      console.log('  订单ID:', order.order_id);
      console.log('  状态:', douyin._getOrderStatusText(order.order_status));
      console.log('  创建时间:', new Date(order.create_order_time * 1000).toLocaleString());
      if (order.products?.[0]) {
        console.log('  商品:', order.products[0].product_name);
      }
      if (order.amount_info) {
        console.log('  金额:', (order.amount_info.origin_amount / 100).toFixed(2), '元');
      }
      console.log('');
    });

    return orders;
  } catch (error) {
    // DouyinAPIError 的 message 已拼好「错误码 + 描述 + 处置指引」,直接打即可
    console.error('\n❌ 查询订单失败!\n');
    console.error('错误信息:', error.message);
    if (error.logId) {
      console.error('logid(报障时提供给抖音):', error.logId);
    }
    console.error('');
    throw error;
  }
}

/**
 * 步骤3: 查询指定订单详情
 */
async function step3_testOrderDetail(orderId, accountId) {
  console.log('\n========================================');
  console.log('步骤3: 查询指定订单详情');
  console.log('========================================\n');

  console.log('请求参数:');
  console.log('  order_id:', orderId);
  console.log('  account_id:', accountId);
  console.log('');

  try {
    const order = await douyin.getOrderDetail(orderId, accountId);

    if (!order) {
      console.log('⚠️  订单不存在或查询失败');
      return null;
    }

    console.log('\n✅ 订单详情查询成功!\n');

    // 提取字段
    const extracted = await processor.decryptAndExtract(order, accountId);
    console.log('   手机号状态:', extracted.customerPhoneStatus, '解密状态:', extracted.decryptionStatus);

    console.log('📋 提取的核心字段:\n');
    console.log('1. 客户手机号:', extracted.customerPhone);
    console.log('2. 下单时间:', extracted.orderTime);
    console.log('3. 团购名称:', extracted.productName);
    console.log('   团购ID:', extracted.productId);
    console.log('4. 下单价格:', extracted.orderPrice, '元');
    console.log('   实付金额:', extracted.actualPrice, '元');
    console.log('5. 店铺名称:', extracted.shopName);
    console.log('   店铺ID:', extracted.shopId);
    console.log('');

    return extracted;
  } catch (error) {
    console.error('\n❌ 查询订单详情失败!\n');
    console.error('错误信息:', error.message);
    console.error('');
    throw error;
  }
}

/**
 * 主流程
 */
async function main() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║      抖音模块分步测试                  ║');
  console.log('╚════════════════════════════════════════╝');

  try {
    // 步骤1: 获取access_token(仅为验证凭证链路,后续请求的 token 由 TokenManager 自行注入)
    await step1_testAccessToken();

    // 步骤2: 查询订单列表
    const orders = await step2_testOrderList(ACCOUNT_ID);

    if (!orders || orders.length === 0) {
      console.log('⚠️  无法继续测试,因为没有订单数据');
      console.log('');
      console.log('建议:');
      console.log('  1. 检查商户是否已授权应用');
      console.log('     路径: 抖音来客 > 店铺管理 > 服务应用授权');
      console.log('  2. 确认账户ID是否正确');
      console.log('     路径: 抖音来客 > 右上角头像 > 个人信息');
      console.log('  3. 确认该商户下是否有订单');
      console.log('');
      process.exit(0);
    }

    // 等待1秒
    await new Promise(resolve => setTimeout(resolve, 1000));

    // 步骤3: 查询第一个订单的详情
    const firstOrder = orders[0];
    console.log('选择测试订单:', firstOrder.order_id);
    await step3_testOrderDetail(firstOrder.order_id, ACCOUNT_ID);

    console.log('\n╔════════════════════════════════════════╗');
    console.log('║      ✅ 所有测试完成                   ║');
    console.log('╚════════════════════════════════════════╝\n');

  } catch (error) {
    console.log('\n╔════════════════════════════════════════╗');
    console.log('║      ❌ 测试失败                       ║');
    console.log('╚════════════════════════════════════════╝\n');
    process.exit(1);
  }
}

// 运行测试
main();
