/**
 * 抖音SPI模块
 * 处理SPI回调请求的验证和解析
 */

const crypto = require('crypto');
const config = require('../../config');
const logger = require('../../utils/logger');

class DouyinSPI {
  /**
   * 处理SPI回调
   * @param {Object} req - Express请求对象
   * @returns {Object} {success, data, error}
   */
  async handleCallback(req) {
    try {
      // 1. 验证签名
      if (!this.verifySignature(req)) {
        logger.error('[抖音SPI] 签名验证失败');
        return {
          success: false,
          error: 'signature_invalid',
        };
      }

      // 2. 解析回调数据
      const callbackData = req.body;
      const eventType = callbackData.event || callbackData.msg_type;

      logger.info('[抖音SPI] 收到回调:', {
        eventType,
        orderId: callbackData.order_id,
        accountId: callbackData.account_id,
      });

      return {
        success: true,
        data: {
          eventType,
          orderId: callbackData.order_id,
          accountId: callbackData.account_id,
          rawData: callbackData,
        },
      };
    } catch (error) {
      logger.error('[抖音SPI] 处理回调异常:', error);
      return {
        success: false,
        error: error.message,
      };
    }
  }

  /**
   * 验证新版Header签名
   * @param {Object} req - Express请求对象
   * @returns {boolean}
   */
  verifySignature(req) {
    const clientKey = req.headers['x-life-clientkey'];
    const receivedSign = req.headers['x-life-sign'];

    if (!clientKey || !receivedSign) {
      logger.error('[抖音SPI] 缺少签名Header');
      return false;
    }

    // 验证clientKey
    if (clientKey !== config.douyin.clientKey) {
      logger.error('[抖音SPI] clientKey不匹配');
      return false;
    }

    try {
      // 构造待签名字符串
      let signString = config.douyin.clientSecret;

      // URL参数按字典序排列
      const sortedKeys = Object.keys(req.query)
        .filter((key) => key !== 'sign')
        .sort();

      for (const key of sortedKeys) {
        const value = req.query[key];
        if (Array.isArray(value)) {
          value.sort().forEach((v) => {
            signString += `&${key}=${v}`;
          });
        } else {
          signString += `&${key}=${value}`;
        }
      }

      // POST请求追加body
      if (req.rawBody) {
        signString += `&http_body=${req.rawBody}`;
      }

      // 计算SHA-256签名
      const calculatedSign = crypto
        .createHash('sha256')
        .update(signString)
        .digest('hex');

      const isValid = calculatedSign === receivedSign;

      if (!isValid) {
        logger.error('[抖音SPI] 签名不匹配:', {
          calculated: calculatedSign.substring(0, 20) + '...',
          received: receivedSign.substring(0, 20) + '...',
        });
      }

      return isValid;
    } catch (error) {
      logger.error('[抖音SPI] 签名验证异常:', error);
      return false;
    }
  }
}

module.exports = DouyinSPI;
