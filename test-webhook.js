/**
 * Webhook 接口测试脚本
 * 用于测试抖音 Webhook 接口是否正常工作
 */

const axios = require('axios');
const crypto = require('crypto');

// 配置
const BASE_URL = process.env.TEST_BASE_URL || 'http://localhost:3000';
const SPI_TOKEN = process.env.DOUYIN_SPI_TOKEN || 'test_token_123';

/**
 * 生成抖音签名
 */
function generateSignature(body, token) {
  const jsonStr = JSON.stringify(body);
  return crypto
    .createHmac('sha256', token)
    .update(jsonStr)
    .digest('hex');
}

/**
 * 测试健康检查接口
 */
async function testHealth() {
  console.log('\n🔍 测试健康检查接口...');
  try {
    const response = await axios.get(`${BASE_URL}/api/health`);
    console.log('✅ 健康检查通过:', response.data);
    return true;
  } catch (error) {
    console.error('❌ 健康检查失败:', error.message);
    return false;
  }
}

/**
 * 测试 Webhook 接口
 */
async function testWebhook() {
  console.log('\n🔍 测试 Webhook 接口...');

  // 模拟抖音推送的消息
  const webhookBody = {
    type: 'order_new',
    timestamp: Date.now(),
    data: {
      shop_id: 'test_shop_001',
      order_id: 'order_' + Date.now(),
      customer_id: 'customer_001',
      customer_nickname: '测试顾客',
      message: '预约了美容服务',
      created_at: new Date().toISOString()
    }
  };

  // 生成签名
  const signature = generateSignature(webhookBody, SPI_TOKEN);

  try {
    const response = await axios.post(
      `${BASE_URL}/api/douyin/webhook`,
      webhookBody,
      {
        headers: {
          'Content-Type': 'application/json',
          'X-Douyin-Signature': signature
        }
      }
    );

    console.log('✅ Webhook 接口响应:', response.data);
    return true;
  } catch (error) {
    if (error.response) {
      console.error('❌ Webhook 接口错误:', error.response.status, error.response.data);
    } else {
      console.error('❌ 请求失败:', error.message);
    }
    return false;
  }
}

/**
 * 测试管理后台接口
 */
async function testAdminAPI() {
  console.log('\n🔍 测试管理后台接口...');

  try {
    // 测试获取店铺列表
    const shopsRes = await axios.get(`${BASE_URL}/api/admin/shops`);
    console.log('✅ 店铺列表:', shopsRes.data);

    // 测试获取统计数据
    const statsRes = await axios.get(`${BASE_URL}/api/admin/statistics`);
    console.log('✅ 统计数据:', statsRes.data);

    return true;
  } catch (error) {
    if (error.response) {
      console.error('❌ 管理接口错误:', error.response.status, error.response.data);
    } else {
      console.error('❌ 请求失败:', error.message);
    }
    return false;
  }
}

/**
 * 主测试流程
 */
async function runTests() {
  console.log('========================================');
  console.log('美容店来客通知系统 - Webhook 测试');
  console.log('========================================');
  console.log(`目标地址: ${BASE_URL}`);
  console.log(`SPI Token: ${SPI_TOKEN.substring(0, 10)}...`);

  const results = {
    health: false,
    webhook: false,
    admin: false
  };

  // 运行测试
  results.health = await testHealth();

  if (results.health) {
    results.webhook = await testWebhook();
    results.admin = await testAdminAPI();
  } else {
    console.log('\n⚠️  健康检查失败，跳过其他测试');
  }

  // 输出测试结果
  console.log('\n========================================');
  console.log('测试结果汇总');
  console.log('========================================');
  console.log(`健康检查: ${results.health ? '✅ 通过' : '❌ 失败'}`);
  console.log(`Webhook 接口: ${results.webhook ? '✅ 通过' : '❌ 失败'}`);
  console.log(`管理接口: ${results.admin ? '✅ 通过' : '❌ 失败'}`);
  console.log('========================================');

  const allPassed = results.health && results.webhook && results.admin;

  if (allPassed) {
    console.log('\n✅ 所有测试通过! 系统已准备就绪');
    console.log('\n📝 下一步:');
    console.log('1. 在抖音开放平台配置 Webhook 地址');
    console.log('2. 授权店铺并配置企微群');
    console.log('3. 访问管理后台: ' + BASE_URL + '/admin/dashboard/');
  } else {
    console.log('\n❌ 部分测试失败，请检查:');
    if (!results.health) console.log('   - 服务器是否正常启动');
    if (!results.webhook) console.log('   - Webhook 路由和签名验证');
    if (!results.admin) console.log('   - 数据库连接和表结构');
  }

  process.exit(allPassed ? 0 : 1);
}

// 运行测试
runTests().catch(error => {
  console.error('\n💥 测试执行出错:', error);
  process.exit(1);
});
