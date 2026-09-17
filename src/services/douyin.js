/**
 * 抖音生活服务API服务
 * 负责与抖音开放平台的所有交互
 */

const axios = require('axios');
const crypto = require('crypto');
const config = require('../config');
const logger = require('../utils/logger');

class DouyinService {
  constructor() {
    this.baseURL = 'https://open.douyin.com';
    this.accessToken = null;
    this.tokenExpireTime = 0;
  }

  /**
   * 获取access_token(client_token方式)
   * 服务商应用使用client_token,不需要用户授权
   */
  async getAccessToken() {
    // 如果token未过期,直接返回
    if (this.accessToken && Date.now() < this.tokenExpireTime) {
      return this.accessToken;
    }

    try {
      const response = await axios.post(`${this.baseURL}/oauth/client_token/`, {
        client_key: config.douyin.clientKey,
        client_secret: config.douyin.clientSecret,
        grant_type: 'client_credential',
      });

      if (response.data.data) {
        this.accessToken = response.data.data.access_token;
        // token有效期7200秒,提前5分钟刷新
        this.tokenExpireTime = Date.now() + (response.data.data.expires_in - 300) * 1000;
        logger.info('[抖音] access_token获取成功');
        return this.accessToken;
      }

      throw new Error('获取access_token失败: ' + JSON.stringify(response.data));
    } catch (error) {
      logger.error('[抖音] 获取access_token失败:', error);
      throw error;
    }
  }

  /**
   * 查询订单详情
   * @param {string} orderId - 抖音订单ID
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 订单详情
   */
  async getOrderDetail(orderId, accountId) {
    try {
      const token = await this.getAccessToken();

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

      if (response.data.extra.error_code === 0 && response.data.data.orders?.length > 0) {
        const order = response.data.data.orders[0];
        logger.info(`[抖音] 订单详情查询成功: ${orderId}`);
        return order;
      }

      logger.warn(`[抖音] 订单不存在或查询失败: ${orderId}`, response.data);
      return null;
    } catch (error) {
      logger.error(`[抖音] 查询订单详情失败: ${orderId}`, error);
      throw error;
    }
  }

  /**
   * 解密加密字段(使用在线解密API)
   * @param {Array<string>} encryptedValues - 加密值数组(Enc.开头)
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 解密结果 {原始值: 脱敏值}
   */
  async decryptFields(encryptedValues, accountId) {
    if (!encryptedValues || encryptedValues.length === 0) {
      return {};
    }

    try {
      const token = await this.getAccessToken();

      // 使用脱敏解密API(不消耗配额,推荐)
      const response = await axios.post(
        `${this.baseURL}/goodlife/v1/open/common_biz/crypto/decrypt_mask/batch`,
        {
          account_id: accountId,
          encrypted_data_list: encryptedValues,
        },
        {
          headers: {
            'access-token': token,
            'content-type': 'application/json',
          },
        }
      );

      if (response.data.extra.error_code === 0) {
        const result = {};
        response.data.data.decrypted_data_list.forEach((item) => {
          result[item.encrypted_data] = item.decrypted_data;
        });
        logger.info(`[抖音] 字段解密成功,共${encryptedValues.length}个`);
        return result;
      }

      logger.warn('[抖音] 字段解密失败', response.data);
      return {};
    } catch (error) {
      logger.error('[抖音] 解密字段失败', error);
      // 解密失败不影响主流程,返回空对象
      return {};
    }
  }

  /**
   * 提取用户需要的订单字段
   * @param {Object} order - 完整订单对象
   * @param {Object} decryptedData - 解密数据映射
   * @returns {Object} 格式化后的订单信息
   */
  extractOrderFields(order, decryptedData = {}) {
    const product = order.products?.[0] || {};
    const amountInfo = order.amount_info || {};
    const buyerInfo = order.buyer_info || {};
    const merchantInfo = order.merchant_info || {};

    // 提取客户手机号(优先使用解密后的)
    let customerPhone = '未获取';
    if (buyerInfo.buyer_phone) {
      customerPhone = decryptedData[buyerInfo.buyer_phone] || buyerInfo.buyer_phone;
    }

    return {
      // 1. 客户手机号
      customerPhone,

      // 2. 下单时间
      orderTime: this.formatTimestamp(order.create_order_time),
      orderTimeRaw: order.create_order_time,

      // 3. 团购名称和ID
      productName: product.product_name || '未知商品',
      productId: product.product_id || '',

      // 4. 下单价格
      orderPrice: (amountInfo.origin_amount / 100).toFixed(2), // 分转元
      actualPrice: (amountInfo.pay_amount / 100).toFixed(2), // 实付金额

      // 5. 店铺名称
      shopName: merchantInfo.account_name || '未知店铺',
      shopId: merchantInfo.account_id || '',

      // 其他有用的字段
      orderId: order.order_id,
      orderStatus: this.getOrderStatusText(order.order_status),
      quantity: product.num || 1,
    };
  }

  /**
   * 格式化时间戳为可读格式
   * @param {number} timestamp - 秒级时间戳
   * @returns {string} 格式化后的时间
   */
  formatTimestamp(timestamp) {
    if (!timestamp) return '未知时间';

    const date = new Date(timestamp * 1000);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    const second = String(date.getSeconds()).padStart(2, '0');

    return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
  }

  /**
   * 获取订单状态文本
   * @param {number} status - 订单状态码
   * @returns {string} 状态文本
   */
  getOrderStatusText(status) {
    const statusMap = {
      0: '初始化',
      100: '待支付',
      101: '支付取消',
      200: '已支付',
      201: '待使用',
      1: '已完成',
      150: '部分支付',
    };
    return statusMap[status] || `未知状态(${status})`;
  }
}

module.exports = new DouyinService();
