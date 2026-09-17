// 测试推送脚本
// 使用方法: node test-send.js

const axios = require('axios');

const SERVICE_URL = process.env.SERVICE_URL || 'http://localhost:3000';

// 测试消息模板
const testMessages = [
  {
    name: '订单通知',
    content: `🔔 新订单提醒

订单号: #DO20240101001
顾客: 张小姐
商品: 美甲套餐 × 1
金额: ¥299
时间: ${new Date().toLocaleTimeString('zh-CN')}

请及时联系顾客确认!`
  },
  {
    name: '咨询提醒',
    content: `💬 新顾客咨询

来源: 抖音
顾客ID: dy_user_12345
时间: ${new Date().toLocaleTimeString('zh-CN')}
内容: 请问今天有空位吗?

请及时回复!`
  },
  {
    name: '简单测试',
    content: '🧪 这是一条测试消息'
  }
];

async function testSend(messageIndex = 0) {
  try {
    console.log('🚀 开始测试推送...\n');

    const message = testMessages[messageIndex] || testMessages[0];

    console.log(`📝 测试消息: ${message.name}`);
    console.log(`📡 目标地址: ${SERVICE_URL}/test/send\n`);

    const response = await axios.post(`${SERVICE_URL}/test/send`, {
      message: message.content
    });

    console.log('✅ 推送成功!\n');
    console.log('📊 结果:');
    console.log(`  - 成功: ${response.data.results.success.length} 个群`);
    console.log(`  - 失败: ${response.data.results.failed.length} 个群\n`);

    if (response.data.results.failed.length > 0) {
      console.log('❌ 失败的群:');
      response.data.results.failed.forEach(fail => {
        console.log(`  - ${fail.chatId}: ${fail.error}`);
      });
    }

    return response.data;

  } catch (error) {
    console.error('❌ 测试失败:');
    if (error.response) {
      console.error(`  状态码: ${error.response.status}`);
      console.error(`  错误信息: ${JSON.stringify(error.response.data, null, 2)}`);
    } else {
      console.error(`  ${error.message}`);
    }
    console.error('\n💡 提示:');
    console.error('  1. 确保服务已启动: npm start');
    console.error('  2. 确保已配置 .env 文件');
    console.error('  3. 确保已同步群列表: curl -X POST http://localhost:3000/groups/sync\n');
    process.exit(1);
  }
}

// 命令行参数
const args = process.argv.slice(2);
const messageIndex = args[0] ? parseInt(args[0]) : 0;

console.log(`
╔════════════════════════════════════════════╗
║  企业微信客户群推送测试工具               ║
╚════════════════════════════════════════════╝
`);

if (args.includes('--list')) {
  console.log('📋 可用的测试消息:\n');
  testMessages.forEach((msg, index) => {
    console.log(`  ${index}. ${msg.name}`);
  });
  console.log('\n使用方法: node test-send.js [消息编号]\n');
  process.exit(0);
}

testSend(messageIndex);
