/**
 * 抖音API模块
 * 负责调用抖音开放平台的HTTP API
 */

const axios = require('axios');
const logger = require('../../utils/logger');

class DouyinAPI {
  constructor() {
    this.baseURL = 'https://open.douyin.com';
    this.accessToken = null;
    this.tokenExpireTime = 0;
    // 直接从环境变量读取配置
    this.clientKey = process.env.DOUYIN_CLIENT_KEY;
    this.clientSecret = process.env.DOUYIN_CLIENT_SECRET;
  }

  /**
   * 初始化(获取access_token)
   */
  async init() {
    try {
      await this.getAccessToken();
      logger.info('[抖音API] 初始化成功');
    } catch (error) {
      logger.error('[抖音API] 初始化失败:', error);
      throw error;
    }
  }

  /**
   * 获取access_token
   * 服务商应用使用client_token模式
   */
  async getAccessToken() {
    // Token未过期则直接返回
    if (this.accessToken && Date.now() < this.tokenExpireTime) {
      return this.accessToken;
    }

    try {
      logger.info('[抖音API] 正在获取access_token...');

      const response = await axios.post(
        `${this.baseURL}/oauth/client_token/`,
        {
          client_key: this.clientKey,
          client_secret: this.clientSecret,
          grant_type: 'client_credential',
        },
        {
          headers: {
            'Content-Type': 'application/json',
          },
        }
      );

      if (response.data.data && response.data.data.access_token) {
        this.accessToken = response.data.data.access_token;
        const expiresIn = response.data.data.expires_in || 7200;
        // 提前5分钟刷新
        this.tokenExpireTime = Date.now() + (expiresIn - 300) * 1000;

        logger.info('[抖音API] access_token获取成功', {
          expiresIn,
          token: this.accessToken.substring(0, 20) + '...',
        });

        return this.accessToken;
      }

      throw new Error(
        `获取access_token失败: ${JSON.stringify(response.data)}`
      );
    } catch (error) {
      logger.error('[抖音API] 获取access_token失败:', {
        message: error.message,
        response: error.response?.data,
      });
      throw error;
    }
  }

  /**
   * 查询订单详情
   * @param {string} orderId - 抖音订单ID
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object|null>} 订单详情
   */
  async getOrderDetail(orderId, accountId) {
    try {
      const token = await this.getAccessToken();

      logger.info('[抖音API] 开始查询订单详情:', { orderId, accountId });

      const response = await axios.get(
        `${this.baseURL}/goodlife/v1/trade/order/query/`,
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

      logger.info('[抖音API] 订单查询响应:', {
        error_code: response.data.extra?.error_code,
        order_count: response.data.data?.orders?.length || 0,
      });

      if (
        response.data.extra.error_code === 0 &&
        response.data.data.orders?.length > 0
      ) {
        const order = response.data.data.orders[0];
        logger.info('[抖音API] 订单详情获取成功:', {
          orderId: order.order_id,
          productName: order.products?.[0]?.product_name,
        });
        return order;
      }

      logger.warn('[抖音API] 订单不存在或查询失败:', {
        orderId,
        response: response.data,
      });
      return null;
    } catch (error) {
      logger.error('[抖音API] 查询订单详情异常:', {
        orderId,
        message: error.message,
        response: error.response?.data,
      });
      throw error;
    }
  }
}

module.exports = DouyinAPI;
