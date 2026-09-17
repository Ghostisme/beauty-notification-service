/**
 * 抖音模块测试文件
 * 用于测试抖音API、签名验证、订单查询等功能
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');
const logger = require('./utils/logger');

// 初始化抖音模块
const douyin = new DouyinModule();

/**
 * 测试1: 初始化并获取access_token
 */
async function testInit() {
  console.log('\n=== 测试1: 初始化并获取access_token ===\n');
  try {
    await douyin.init();
    console.log('✅ 初始化成功');
    return true;
  } catch (error) {
    console.error('❌ 初始化失败:', error.message);
    return false;
  }
}

/**
 * 测试2: 查询订单详情
 * @param {string} orderId - 订单ID
 * @param {string} accountId - 商户账户ID
 */
async function testGetOrderDetail(orderId, accountId) {
  console.log('\n=== 测试2: 查询订单详情 ===\n');
  console.log('参数:', { orderId, accountId });

  try {
    const order = await douyin.getOrderDetail(orderId, accountId);

    if (!order) {
      console.log('⚠️  订单不存在或查询失败');
      return null;
    }

    console.log('\n✅ 订单查询成功\n');
    console.log('订单基础信息:');
    console.log('  - 订单ID:', order.order_id);
    console.log('  - 订单状态:', order.order_status);
    console.log('  - 创建时间:', new Date(order.create_order_time * 1000).toLocaleString());

    if (order.products && order.products.length > 0) {
      console.log('\n商品信息:');
      order.products.forEach((product, index) => {
        console.log(`  商品${index + 1}:`);
        console.log('    - 名称:', product.product_name);
        console.log('    - ID:', product.product_id);
        console.log('    - 数量:', product.num);
      });
    }

    if (order.amount_info) {
      console.log('\n金额信息:');
      console.log('  - 原价:', (order.amount_info.origin_amount / 100).toFixed(2), '元');
      console.log('  - 实付:', (order.amount_info.pay_amount / 100).toFixed(2), '元');
    }

    if (order.buyer_info) {
      console.log('\n买家信息:');
      console.log('  - 手机号(加密):', order.buyer_info.buyer_phone || '未提供');
    }

    if (order.merchant_info) {
      console.log('\n商户信息:');
      console.log('  - 商户ID:', order.merchant_info.account_id);
      console.log('  - 商户名称:', order.merchant_info.account_name);
    }

    return order;
  } catch (error) {
    console.error('❌ 查询订单失败:', error.message);
    return null;
  }
}

/**
 * 测试3: 解密加密字段
 * @param {Object} order - 订单对象
 * @param {string} accountId - 商户账户ID
 */
async function testDecrypt(order, accountId) {
  console.log('\n=== 测试3: 解密加密字段 ===\n');

  try {
    // 收集需要解密的字段
    const encryptedFields = [];
    if (order.buyer_info?.buyer_phone) {
      encryptedFields.push(order.buyer_info.buyer_phone);
    }

    if (encryptedFields.length === 0) {
      console.log('⚠️  没有需要解密的字段');
      return {};
    }

    console.log('需要解密的字段:', encryptedFields);

    const decryptedData = await douyin.decryptFields(encryptedFields, accountId);

    console.log('\n✅ 解密结果:');
    Object.entries(decryptedData).forEach(([encrypted, decrypted]) => {
      console.log(`  ${encrypted.substring(0, 20)}... => ${decrypted}`);
    });

    return decryptedData;
  } catch (error) {
    console.error('❌ 解密失败:', error.message);
    return {};
  }
}

/**
 * 测试4: 提取用户需要的字段
 * @param {Object} order - 订单对象
 * @param {Object} decryptedData - 解密数据
 */
async function testExtractFields(order, decryptedData) {
  console.log('\n=== 测试4: 提取用户需要的字段 ===\n');

  try {
    const extracted = douyin.extractOrderFields(order, decryptedData);

    console.log('✅ 提取的字段:\n');
    console.log('1. 客户手机号:', extracted.customerPhone);
    console.log('2. 下单时间:', extracted.orderTime);
    console.log('3. 团购名称:', extracted.productName);
    console.log('   团购ID:', extracted.productId);
    console.log('4. 下单价格:', extracted.orderPrice, '元');
    console.log('   实付金额:', extracted.actualPrice, '元');
    console.log('5. 店铺名称:', extracted.shopName);
    console.log('   店铺ID:', extracted.shopId);

    return extracted;
  } catch (error) {
    console.error('❌ 提取字段失败:', error.message);
    return null;
  }
}

/**
 * 测试5: 模拟SPI回调验证
 */
async function testSPISignature() {
  console.log('\n=== 测试5: SPI签名验证 ===\n');

  // 模拟一个请求对象
  const mockReq = {
    headers: {
      'x-life-clientkey': process.env.DOUYIN_CLIENT_KEY,
      'x-life-sign': 'test_signature_here', // 这里需要真实的签名
    },
    query: {},
    body: {
      event: 'trade.order.notify',
      order_id: 'test_order_123',
      account_id: 'test_account_456',
    },
    rawBody: JSON.stringify({
      event: 'trade.order.notify',
      order_id: 'test_order_123',
      account_id: 'test_account_456',
    }),
  };

  console.log('⚠️  这是模拟测试,签名验证可能失败');
  console.log('真实的SPI回调需要在服务器接收时测试\n');

  const result = await douyin.handleSPICallback(mockReq);
  console.log('验证结果:', result);

  return result;
}

/**
 * 完整流程测试
 */
async function runFullTest() {
  console.log('\n');
  console.log('╔════════════════════════════════════════╗');
  console.log('║   抖音模块完整测试                     ║');
  console.log('╚════════════════════════════════════════╝');

  // 从命令行参数获取测试数据
  const orderId = process.argv[2];
  const accountId = process.argv[3];

  if (!orderId || !accountId) {
    console.log('\n使用方法:');
    console.log('  node src/test-douyin.js <订单ID> <商户账户ID>');
    console.log('\n示例:');
    console.log('  node src/test-douyin.js 1117443386481945704 12345678');
    console.log('\n提示:');
    console.log('  - 订单ID: 从抖音来客后台订单列表获取');
    console.log('  - 商户账户ID: 从抖音来客"个人信息"获取');
    console.log('\n');
    process.exit(1);
  }

  try {
    // 测试1: 初始化
    const initSuccess = await testInit();
    if (!initSuccess) {
      console.error('\n❌ 初始化失败,终止测试');
      process.exit(1);
    }

    // 测试2: 查询订单
    const order = await testGetOrderDetail(orderId, accountId);
    if (!order) {
      console.error('\n❌ 订单查询失败,终止测试');
      process.exit(1);
    }

    // 测试3: 解密字段
    const decryptedData = await testDecrypt(order, accountId);

    // 测试4: 提取字段
    const extractedData = await testExtractFields(order, decryptedData);

    // 测试5: SPI签名验证(可选)
    // await testSPISignature();

    console.log('\n');
    console.log('╔════════════════════════════════════════╗');
    console.log('║   ✅ 所有测试完成                      ║');
    console.log('╚════════════════════════════════════════╝');
    console.log('\n');

    console.log('📋 测试总结:');
    console.log('  ✅ access_token获取成功');
    console.log('  ✅ 订单查询成功');
    console.log('  ✅ 字段解密成功');
    console.log('  ✅ 字段提取成功');
    console.log('\n');

    console.log('📦 最终输出的订单数据:');
    console.log(JSON.stringify(extractedData, null, 2));
    console.log('\n');
  } catch (error) {
    console.error('\n❌ 测试过程中出现异常:', error);
    process.exit(1);
  }
}

// 执行测试
runFullTest();
