/**
 * 企业微信API服务
 * 负责向企业微信外部客户群发送消息
 */

const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

class WeworkService {
  constructor() {
    this.baseURL = 'https://qyapi.weixin.qq.com';
    this.accessToken = null;
    this.tokenExpireTime = 0;
  }

  /**
   * 获取企业微信access_token
   */
  async getAccessToken() {
    // 如果token未过期,直接返回
    if (this.accessToken && Date.now() < this.tokenExpireTime) {
      return this.accessToken;
    }

    try {
      const response = await axios.get(`${this.baseURL}/cgi-bin/gettoken`, {
        params: {
          corpid: config.wework.corpId,
          corpsecret: config.wework.secret,
        },
      });

      if (response.data.errcode === 0) {
        this.accessToken = response.data.access_token;
        // token有效期7200秒,提前5分钟刷新
        this.tokenExpireTime = Date.now() + (response.data.expires_in - 300) * 1000;
        logger.info('[企业微信] access_token获取成功');
        return this.accessToken;
      }

      throw new Error(`获取access_token失败: ${response.data.errmsg}`);
    } catch (error) {
      logger.error('[企业微信] 获取access_token失败:', error);
      throw error;
    }
  }

  /**
   * 构建订单通知消息文本
   * @param {Object} orderData - 订单数据
   * @returns {string} 格式化的消息文本
   */
  buildOrderMessage(orderData) {
    const {
      customerPhone,
      orderTime,
      productName,
      productId,
      orderPrice,
      actualPrice,
      shopName,
      orderId,
      orderStatus,
      quantity,
    } = orderData;

    // 构建消息文本
    let message = `📢 【新订单通知】\n\n`;
    message += `👤 客户手机号: ${customerPhone}\n`;
    message += `⏰ 下单时间: ${orderTime}\n`;
    message += `🛍️ 团购名称: ${productName}\n`;
    message += `🆔 团购ID: ${productId}\n`;
    message += `💰 下单价格: ¥${orderPrice}\n`;
    message += `💵 实付金额: ¥${actualPrice}\n`;
    message += `🏪 店铺名称: ${shopName}\n`;
    message += `📦 购买数量: ${quantity}\n`;
    message += `📋 订单状态: ${orderStatus}\n`;
    message += `🔖 订单号: ${orderId}\n`;

    return message;
  }

  /**
   * 发送文本消息到外部客户群
   * @param {string} chatId - 外部客户群ID
   * @param {string} content - 消息内容
   * @returns {Promise<boolean>} 是否发送成功
   */
  async sendMessageToExternalChat(chatId, content) {
    try {
      const token = await this.getAccessToken();

      const response = await axios.post(
        `${this.baseURL}/cgi-bin/externalcontact/message/send`,
        {
          chat_id: chatId,
          msgtype: 'text',
          text: {
            content: content,
          },
          sender: config.wework.senderUserId,
        },
        {
          params: {
            access_token: token,
          },
        }
      );

      if (response.data.errcode === 0) {
        logger.info(`[企业微信] 消息发送成功到群: ${chatId}`);
        return true;
      }

      logger.error(
        `[企业微信] 消息发送失败: ${response.data.errmsg}`,
        response.data
      );
      return false;
    } catch (error) {
      logger.error('[企业微信] 发送消息异常:', error);
      return false;
    }
  }

  /**
   * 发送订单通知到指定群
   * @param {string} chatId - 企业微信群ID
   * @param {Object} orderData - 订单数据
   * @returns {Promise<boolean>} 是否发送成功
   */
  async sendOrderNotification(chatId, orderData) {
    const message = this.buildOrderMessage(orderData);
    return await this.sendMessageToExternalChat(chatId, message);
  }

  /**
   * 获取外部客户群列表(用于配置和调试)
   * @returns {Promise<Array>} 群列表
   */
  async getExternalChatList() {
    try {
      const token = await this.getAccessToken();

      const response = await axios.post(
        `${this.baseURL}/cgi-bin/externalcontact/groupchat/list`,
        {
          status_filter: 0, // 0-所有群 1-正常 2-离职
          offset: 0,
          limit: 100,
        },
        {
          params: {
            access_token: token,
          },
        }
      );

      if (response.data.errcode === 0) {
        logger.info(`[企业微信] 获取群列表成功,共${response.data.group_chat_list?.length || 0}个群`);
        return response.data.group_chat_list || [];
      }

      logger.error(`[企业微信] 获取群列表失败: ${response.data.errmsg}`);
      return [];
    } catch (error) {
      logger.error('[企业微信] 获取群列表异常:', error);
      return [];
    }
  }
}

module.exports = new WeworkService();
