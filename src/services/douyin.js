/**
 * 抖音生活服务API服务
 * 负责与抖音开放平台的所有交互
 */

const DouyinModule = require('../modules/douyin');
const { DouyinWebhook } = require('../douyin');
const config = require('../config');
const logger = require('../utils/logger');

// The server and CLI must use the same token refresh/error-handling path.
class DouyinService {
  constructor() {
    this.module = new DouyinModule();
    this.api = this.module.api;
    this.webhook = new DouyinWebhook(config.douyin.clientSecret, logger);
  }

  getAccessToken(options = {}) { return this.api.getAccessToken(options); }
  getTokenStatus() { return this.api.getTokenStatus(); }
  queryOrders(options) { return this.api.queryOrders(options); }
  getOrderDetail(orderId, accountId) { return this.api.getOrderDetail(orderId, accountId); }
  decryptFields(values, accountId, options = {}) {
    return this.module.decryptFields(values, accountId, options);
  }
  verifySignature(body, signature, timestamp) {
    return this.webhook.verifySignature(body, signature, timestamp);
  }
  handleWebhook(body) {
    return this.webhook.parseOrderData(body);
  }

  /**
   * 提取用户需要的订单字段
   * @param {Object} order - 完整订单对象
   * @param {Object} decryptedData - 解密数据映射
   * @returns {Object} 格式化后的订单信息
   */
  extractOrderFields(order, decryptedData = {}) {
    return this.module.extractOrderFields(order, decryptedData);
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
