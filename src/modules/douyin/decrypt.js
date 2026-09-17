/**
 * 抖音解密模块
 * 处理加密字段的解密(手机号等敏感信息)
 */

const axios = require('axios');
const config = require('../../config');
const logger = require('../../utils/logger');

class DouyinDecrypt {
  constructor() {
    this.baseURL = 'https://open.douyin.com';
    this.apiInstance = null; // 会从外部注入DouyinAPI实例
  }

  /**
   * 设置API实例(用于获取access_token)
   * @param {Object} apiInstance - DouyinAPI实例
   */
  setAPIInstance(apiInstance) {
    this.apiInstance = apiInstance;
  }

  /**
   * 批量解密(完整解密,不脱敏)
   * @param {Array<string>} encryptedValues - 加密值数组
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 解密结果 {原始加密值: 完整解密值}
   */
  async decryptBatch(encryptedValues, accountId) {
    if (!encryptedValues || encryptedValues.length === 0) {
      return {};
    }

    // 过滤出Enc.开头的加密字段
    const needDecrypt = encryptedValues.filter((v) =>
      v.startsWith('Enc.')
    );

    if (needDecrypt.length === 0) {
      return {};
    }

    try {
      if (!this.apiInstance) {
        throw new Error('API实例未设置');
      }

      const token = await this.apiInstance.getAccessToken();

      logger.info('[抖音解密] 开始完整解密字段:', {
        count: needDecrypt.length,
        accountId,
      });

      // 使用完整解密API(decrypt/batch),返回未脱敏的完整数据
      const response = await axios.post(
        `${this.baseURL}/goodlife/v1/open/common_biz/crypto/decrypt/batch`,
        {
          account_id: accountId,
          encrypted_data_list: needDecrypt,
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
        const decryptedList = response.data.data.decrypted_data_list || [];

        decryptedList.forEach((item) => {
          // 返回完整的未脱敏数据
          result[item.encrypted_data] = item.decrypted_data;
        });

        logger.info('[抖音解密] 完整解密成功:', {
          count: Object.keys(result).length,
        });

        return result;
      }

      logger.warn('[抖音解密] 解密失败:', response.data);
      return {};
    } catch (error) {
      logger.error('[抖音解密] 解密异常:', {
        message: error.message,
        response: error.response?.data,
      });
      // 解密失败不影响主流程,返回空对象
      return {};
    }
  }
}

module.exports = DouyinDecrypt;
