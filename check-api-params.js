require('dotenv').config();
const axios = require('axios');
const DouyinModule = require('./src/modules/douyin');

const douyin = new DouyinModule();

async function testDifferentParams() {
  await douyin.init();
  
  const accountId = '7605435122824890377';
  const orderId = '1091962674194265394';
  
  console.log('\n=== 测试1: 当前查询方式 ===\n');
  const order1 = await douyin.getOrderDetail(orderId, accountId);
  console.log('返回的顶层字段:', Object.keys(order1));
  console.log('是否有buyer_info:', 'buyer_info' in order1);
  console.log('是否有receiver_info:', 'receiver_info' in order1);
  
  console.log('\n=== 测试2: 尝试不同的查询参数 ===\n');
  
  const token = await douyin.api.getAccessToken();
  
  // 测试添加更多查询参数
  try {
    const response = await axios.get(
      'https://open.douyin.com/goodlife/v1/trade/order/query/',
      {
        headers: {
          'access-token': token,
          'content-type': 'application/json',
        },
        params: {
          account_id: accountId,
          order_id: orderId,
          page_num: 1,
          page_size: 1,
        },
      }
    );
    
    if (response.data.data?.orders?.[0]) {
      const order = response.data.data.orders[0];
      console.log('完整订单字段:', Object.keys(order));
      console.log('\n检查关键字段:');
      console.log('- buyer_info:', order.buyer_info ? 'EXISTS' : 'NOT FOUND');
      console.log('- receiver_info:', order.receiver_info ? 'EXISTS' : 'NOT FOUND');
      console.log('- contacts:', order.contacts ? 'EXISTS' : 'NOT FOUND');
      
      if (order.buyer_info) {
        console.log('\nbuyer_info内容:', JSON.stringify(order.buyer_info, null, 2));
      }
      
      if (order.receiver_info) {
        console.log('\nreceiver_info内容:', JSON.stringify(order.receiver_info, null, 2));
      }
    }
  } catch (error) {
    console.error('查询失败:', error.message);
  }
}

testDifferentParams();
