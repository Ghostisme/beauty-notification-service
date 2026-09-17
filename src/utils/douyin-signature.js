/**
 * 抖音生活服务签名验证工具
 * 支持新版Header签名验证(推荐)和旧版URL签名验证
 */

const crypto = require('crypto');
const config = require('../config');

/**
 * 验证抖音SPI回调的新版Header签名
 * @param {Object} headers - 请求头
 * @param {Object} query - URL查询参数
 * @param {string} rawBody - 原始请求体(字符串)
 * @returns {boolean} 签名是否有效
 */
function verifyHeaderSignature(headers, query, rawBody) {
  const clientKey = headers['x-life-clientkey'];
  const receivedSign = headers['x-life-sign'];

  if (!clientKey || !receivedSign) {
    console.error('[签名验证] 缺少必要的Header参数');
    return false;
  }

  // 验证clientKey是否匹配
  if (clientKey !== config.douyin.clientKey) {
    console.error('[签名验证] clientKey不匹配');
    return false;
  }

  try {
    // 1. 以client_secret开头
    let signString = config.douyin.clientSecret;

    // 2. 将URL参数(除sign外)按key字典序排列
    const sortedKeys = Object.keys(query)
      .filter(key => key !== 'sign')
      .sort();

    for (const key of sortedKeys) {
      const value = query[key];
      if (Array.isArray(value)) {
        // 多个值按字典序排列
        value.sort().forEach(v => {
          signString += `&${key}=${v}`;
        });
      } else {
        signString += `&${key}=${value}`;
      }
    }

    // 3. POST请求末尾追加&http_body=原始内容
    if (rawBody) {
      signString += `&http_body=${rawBody}`;
    }

    // 4. 计算SHA-256哈希值(十六进制小写)
    const calculatedSign = crypto
      .createHash('sha256')
      .update(signString)
      .digest('hex');

    // 5. 验证签名
    const isValid = calculatedSign === receivedSign;

    if (!isValid) {
      console.error('[签名验证] 签名不匹配');
      console.error('待签名字符串:', signString);
      console.error('计算得到:', calculatedSign);
      console.error('接收到的:', receivedSign);
    }

    return isValid;
  } catch (error) {
    console.error('[签名验证] 验证过程出错:', error);
    return false;
  }
}

/**
 * 验证抖音WebHook的X-Douyin-Signature签名
 * @param {Object} headers - 请求头
 * @param {string} rawBody - 原始请求体
 * @returns {boolean} 签名是否有效
 */
function verifyWebhookSignature(headers, rawBody) {
  const receivedSign = headers['x-douyin-signature'];

  if (!receivedSign) {
    console.error('[Webhook验证] 缺少X-Douyin-Signature');
    return false;
  }

  try {
    // 使用client_secret + rawBody计算签名
    const signString = config.douyin.clientSecret + rawBody;
    const calculatedSign = crypto
      .createHash('sha256')
      .update(signString)
      .digest('hex');

    const isValid = calculatedSign === receivedSign;

    if (!isValid) {
      console.error('[Webhook验证] 签名不匹配');
    }

    return isValid;
  } catch (error) {
    console.error('[Webhook验证] 验证过程出错:', error);
    return false;
  }
}

module.exports = {
  verifyHeaderSignature,
  verifyWebhookSignature,
};
