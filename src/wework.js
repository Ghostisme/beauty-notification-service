const axios = require('axios');

/**
 * 企业微信群机器人推送
 */
class WeworkNotifier {
  constructor(logger) {
    this.logger = logger;
    this.axiosInstance = axios.create({
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  /**
   * 发送文本消息到企业微信群
   * @param {string} webhook - 企微群机器人 Webhook 地址
   * @param {string} message - 消息内容
   */
  async send(webhook, message) {
    try {
      const response = await this.axiosInstance.post(webhook, {
        msgtype: 'text',
        text: {
          content: message
        }
      });

      // 检查企微返回的错误码
      if (response.data.errcode !== 0) {
        throw new Error(`企微返回错误: ${response.data.errmsg} (errcode: ${response.data.errcode})`);
      }

      return response.data;

    } catch (error) {
      // 区分网络错误和业务错误
      if (error.response) {
        // HTTP 错误（4xx, 5xx）
        this.logger.error({
          status: error.response.status,
          data: error.response.data,
          webhook: this._maskWebhook(webhook)
        }, '企微推送 HTTP 错误');
        throw new Error(`HTTP ${error.response.status}: ${error.response.statusText}`);

      } else if (error.request) {
        // 网络超时或无响应
        this.logger.error({
          error: error.message,
          webhook: this._maskWebhook(webhook)
        }, '企微推送网络错误');
        throw new Error('网络超时或无法连接企微服务器');

      } else {
        // 其他错误
        this.logger.error({
          error: error.message,
          webhook: this._maskWebhook(webhook)
        }, '企微推送未知错误');
        throw error;
      }
    }
  }

  /**
   * 发送 Markdown 消息（企微支持）
   */
  async sendMarkdown(webhook, content) {
    try {
      const response = await this.axiosInstance.post(webhook, {
        msgtype: 'markdown',
        markdown: {
          content: content
        }
      });

      if (response.data.errcode !== 0) {
        throw new Error(`企微返回错误: ${response.data.errmsg}`);
      }

      return response.data;

    } catch (error) {
      this.logger.error({
        error: error.message,
        webhook: this._maskWebhook(webhook)
      }, 'Markdown 推送失败');
      throw error;
    }
  }

  /**
   * 批量推送到多个群
   */
  async sendBatch(webhooks, message) {
    const results = await Promise.allSettled(
      webhooks.map(webhook => this.send(webhook, message))
    );

    const success = results.filter(r => r.status === 'fulfilled').length;
    const failed = results.filter(r => r.status === 'rejected').length;

    this.logger.info({ success, failed, total: webhooks.length }, '批量推送完成');

    return {
      success,
      failed,
      total: webhooks.length,
      results
    };
  }

  /**
   * 验证 Webhook 地址格式
   */
  validateWebhook(webhook) {
    const pattern = /^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=[a-zA-Z0-9-]+$/;
    return pattern.test(webhook);
  }

  /**
   * 掩码 Webhook 地址（日志安全）
   */
  _maskWebhook(webhook) {
    if (!webhook) return 'N/A';

    const keyMatch = webhook.match(/key=([a-zA-Z0-9-]+)/);
    if (keyMatch) {
      const key = keyMatch[1];
      const masked = key.substring(0, 8) + '***' + key.substring(key.length - 4);
      return webhook.replace(key, masked);
    }

    return webhook.substring(0, 50) + '...';
  }
}

module.exports = { WeworkNotifier };
