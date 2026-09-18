/**
 * 测试会员手机号变更接口,获取 logid
 * 用于配置"餐综合会员手机号变更"校验
 */

const axios = require('axios');
require('dotenv').config();

async function testMobileMemberUpdate() {
  try {
    console.log('🔄 正在调用会员手机号变更接口...\n');

    const response = await axios.post(
      'https://open.douyin.com/goodlife/v1/member/user/update/',
      {
        account_id: process.env.DOUYIN_ACCOUNT_ID || '请填写你的商户账户ID',
        members: [
          {
            open_id: 'test_openid_mobile_12345',
            new_mobile: '13800138000', // 测试手机号
            update_time: Math.floor(Date.now() / 1000),
          },
        ],
      },
      {
        headers: {
          'access-token': process.env.DOUYIN_ACCESS_TOKEN || 'clt.73991a2d4ac0dfad0078be3da6fc9d64m9fF6hkOnJVJdb7tMOaX7ayZuFEy_lf',
          'content-type': 'application/json',
        },
      }
    );

    console.log('✅ 接口调用成功!\n');
    console.log('📋 完整响应:');
    console.log(JSON.stringify(response.data, null, 2));
    console.log('\n');

    // 提取 logid
    const logid = response.data.logid || response.data.extra?.logid;

    if (logid) {
      console.log('🎯 请复制以下 logid 填入"餐综合会员手机号变更"配置页面:\n');
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      console.log(logid);
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
    } else {
      console.log('⚠️  未找到 logid,请检查响应结构\n');
    }
  } catch (error) {
    console.error('❌ 接口调用失败:\n');
    if (error.response) {
      console.error('状态码:', error.response.status);
      console.error('响应数据:', JSON.stringify(error.response.data, null, 2));

      // 即使失败也可能有 logid
      const logid =
        error.response.data.logid || error.response.data.extra?.logid;
      if (logid) {
        console.log('\n🎯 失败响应中的 logid:\n');
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        console.log(logid);
        console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
        console.log('💡 即使业务失败,这个 logid 也可以用于配置校验\n');
      }
    } else {
      console.error('错误:', error.message);
    }
  }
}

// 执行测试
testMobileMemberUpdate();
