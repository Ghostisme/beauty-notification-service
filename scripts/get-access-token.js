/**
 * 获取抖音开放平台 access_token
 * 用于调用需要认证的 API 接口
 */

const axios = require('axios');
require('dotenv').config();

async function getAccessToken() {
  try {
    console.log('🔄 正在获取 access_token...\n');

    const response = await axios.post(
      'https://open.douyin.com/oauth/client_token/',
      {
        client_key: process.env.DOUYIN_CLIENT_KEY,
        client_secret: process.env.DOUYIN_CLIENT_SECRET,
        grant_type: 'client_credential',
      },
      {
        headers: {
          'Content-Type': 'application/json',
        },
      }
    );

    console.log('✅ 获取成功!\n');
    console.log('📋 完整响应:');
    console.log(JSON.stringify(response.data, null, 2));
    console.log('\n');

    if (response.data.data?.access_token) {
      const accessToken = response.data.data.access_token;
      const expiresIn = response.data.data.expires_in;

      console.log('🎯 Access Token:\n');
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      console.log(accessToken);
      console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n');
      console.log(`⏰ 有效期: ${expiresIn} 秒 (约 ${Math.floor(expiresIn / 3600)} 小时)\n`);
      console.log('💡 请将此 token 添加到 .env 文件:\n');
      console.log(`DOUYIN_ACCESS_TOKEN=${accessToken}\n`);
    } else {
      console.log('⚠️  未找到 access_token,请检查响应结构\n');
    }
  } catch (error) {
    console.error('❌ 获取失败:\n');
    if (error.response) {
      console.error('状态码:', error.response.status);
      console.error('响应数据:', JSON.stringify(error.response.data, null, 2));
    } else {
      console.error('错误:', error.message);
    }
    console.error('\n💡 请检查 .env 文件中的配置:');
    console.error('- DOUYIN_CLIENT_KEY');
    console.error('- DOUYIN_CLIENT_SECRET\n');
  }
}

// 执行
getAccessToken();
