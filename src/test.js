/**
 * 测试脚本
 * 用于测试各个模块功能
 */

const axios = require('axios');
const config = require('./config');
const logger = require('./utils/logger');

// 测试服务器地址
const BASE_URL = `http://localhost:${config.server.port}`;

class Tester {
  /**
   * 测试健康检查
   */
  async testHealth() {
    logger.info('测试健康检查...');
    try {
      const response = await axios.get(`${BASE_URL}/api/health`);
      logger.success('健康检查通过', response.data);
    } catch (error) {
      logger.error('健康检查失败', error.message);
    }
  }

  /**
   * 测试获取店铺列表
   */
  async testGetShops() {
    logger.info('测试获取店铺列表...');
    try {
      const response = await axios.get(`${BASE_URL}/admin/shops`);
      logger.success('获取店铺列表成功', response.data);
      return response.data.data;
    } catch (error) {
      logger.error('获取店铺列表失败', error.message);
      return [];
    }
  }

  /**
   * 测试获取企微群列表
   */
  async testGetWeworkChats() {
    logger.info('测试获取企微群列表...');
    try {
      const response = await axios.get(`${BASE_URL}/admin/wework/chats`);
      logger.success('获取企微群列表成功', response.data);
      return response.data.data;
    } catch (error) {
      logger.error('获取企微群列表失败', error.message);
      return [];
    }
  }

  /**
   * 测试推送消息
   */
  async testPushMessage(shopId) {
    logger.info('测试推送消息...', { shopId });
    try {
      const response = await axios.post(`${BASE_URL}/test/push`, {
        shopId,
        testMessage: `🔔 【测试消息】

📱 店铺：测试店铺
👤 顾客：测试顾客_${Date.now()}
⏰ 时间：${new Date().toLocaleString('zh-CN')}
💬 内容：这是一条测试消息

请及时回复！`,
      });

      logger.success('测试消息发送成功', response.data);
    } catch (error) {
      logger.error('测试消息发送失败', error.response?.data || error.message);
    }
  }

  /**
   * 运行所有测试
   */
  async runAll() {
    logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    logger.success('开始运行测试套件');
    logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    logger.info('');

    // 1. 健康检查
    await this.testHealth();
    logger.info('');

    // 2. 获取店铺列表
    const shops = await this.testGetShops();
    logger.info('');

    // 3. 获取企微群列表
    await this.testGetWeworkChats();
    logger.info('');

    // 4. 测试推送(如果有店铺)
    if (shops.length > 0) {
      const firstShop = shops[0];
      if (firstShop.wework_chat_id) {
        await this.testPushMessage(firstShop.shop_id);
      } else {
        logger.warn('第一个店铺未配置企微群,跳过推送测试');
      }
    } else {
      logger.warn('没有店铺数据,跳过推送测试');
    }

    logger.info('');
    logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
    logger.success('测试套件运行完成');
    logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
  }
}

// 运行测试
const tester = new Tester();
tester.runAll().catch(error => {
  logger.error('测试运行失败', error);
  process.exit(1);
});
