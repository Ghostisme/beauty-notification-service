/**
 * 抖音敏感字段解密
 *
 * 接口: POST /goodlife/v1/open/common_biz/crypto/decrypt/batch
 * 返回未脱敏的完整明文(手机号、姓名、证件号等)。
 *
 * 设计要点:
 *   1. 不再自己发 HTTP,走统一请求层 —— token 失效重取、频控退避、业务错误码
 *      判定都已在 http-client 里做过一遍,这里重复实现只会漏。
 *   2. 解密失败绝不向上抛:通知链路的主体价值是"订单到了",手机号拿不到应当
 *      降级展示(见 index.js 的手机号降级链),不能让整条推送因此中断。
 */

const logger = require('../../utils/logger');
const { isEncrypted } = require('./sensitive-fields');
const { DouyinAPIError } = require('./errors');

/** 批量解密接口路径 */
const DECRYPT_BATCH_PATH = '/goodlife/v1/open/common_biz/crypto/decrypt/batch';
/**
 * 单次请求提交的密文条数上限。
 * 文档未明确给出该上限,取 50 作保守值:一批过大既可能被判参数不合法,
 * 也会让单次失败牵连过多字段。确认官方上限后可直接调大。
 */
const DEFAULT_BATCH_SIZE = 50;

class DouyinDecrypt {
  /**
   * @param {import('./http-client')} [httpClient] - 统一请求层;也可事后用 setHttpClient 注入
   * @param {Object} [options]
   * @param {number} [options.batchSize] - 单次请求提交的密文条数
   */
  constructor(httpClient = null, options = {}) {
    this.http = httpClient;
    this.batchSize = options.batchSize || DEFAULT_BATCH_SIZE;
    if (!Number.isInteger(this.batchSize) || this.batchSize < 1) throw new Error('batchSize 必须为正整数');
  }

  /**
   * 注入统一请求层。
   * @param {import('./http-client')} httpClient - DouyinHttpClient 实例
   */
  setHttpClient(httpClient) {
    this.http = httpClient;
  }

  /**
   * 兼容旧的注入方式。
   *
   * 早先注入的是整个 DouyinAPI 实例(为了从它身上取 access_token),
   * 现在只需要它内部的统一请求层;保留该方法避免改动既有调用方。
   *
   * @param {Object} apiInstance - DouyinAPI 实例
   */
  setAPIInstance(apiInstance) {
    this.http = apiInstance?.http || null;
  }

  /**
   * 批量解密(完整解密,不脱敏)。
   *
   * @param {Array<string>} encryptedValues - 密文数组,非 `Enc.` 前缀的值会被自动过滤
   * @param {string} accountId - 商户账户 ID
   * @returns {Promise<Object<string, string>>} {密文: 明文};整体失败时返回 {}
   */
  async decryptBatch(encryptedValues, accountId, { strict = false } = {}) {
    if (!Array.isArray(encryptedValues) || encryptedValues.length === 0) {
      return {};
    }

    // 去重后再提交:同一手机号常出现在多个字段,重复提交白耗调用额度
    const needDecrypt = [...new Set(encryptedValues.filter(isEncrypted))];
    if (needDecrypt.length === 0) {
      return {};
    }

    if (!this.http) {
      if (strict) throw new Error('[抖音解密] 未注入请求层');
      logger.error('[抖音解密] 未注入请求层,跳过解密');
      return {};
    }

    logger.info('[抖音解密] 开始解密字段:', {
      count: needDecrypt.length,
      accountId,
    });

    const result = {};

    // 分批提交:某一批失败只损失该批字段,其余仍能解出
    for (let i = 0; i < needDecrypt.length; i += this.batchSize) {
      const chunk = needDecrypt.slice(i, i + this.batchSize);
      Object.assign(result, await this._decryptChunk(chunk, accountId, strict));
    }

    logger.info('[抖音解密] 解密完成:', {
      requested: needDecrypt.length,
      decrypted: Object.keys(result).length,
    });

    return result;
  }

  /**
   * 解密一批密文。
   *
   * 失败时只记日志并返回空结果,不抛异常 —— 见文件头说明:
   * 解密是通知链路的增强项,不是必要条件。
   *
   * @param {Array<string>} chunk - 本批密文
   * @param {string} accountId - 商户账户 ID
   * @returns {Promise<Object<string, string>>} {密文: 明文}
   */
  async _decryptChunk(chunk, accountId, strict = false) {
    try {
      const data = await this.http.post(DECRYPT_BATCH_PATH, {
        account_id: accountId,
        encrypted_data_list: chunk,
      });

      const decryptedList = data.decrypted_data_list;
      if (!Array.isArray(decryptedList)) throw new Error('[抖音解密] 响应缺少 decrypted_data_list 数组');
      const mapping = {};

      for (const item of decryptedList) {
        // 个别字段解密失败时抖音会返回空明文,这类条目不入表,
        // 让下游的 isEncrypted 判定仍能识别出"这个字段没解出来"
        if (chunk.includes(item?.encrypted_data) && typeof item.decrypted_data === 'string'
          && item.decrypted_data && !isEncrypted(item.decrypted_data)) {
          mapping[item.encrypted_data] = item.decrypted_data;
        }
      }
      if (strict && Object.keys(mapping).length !== chunk.length) {
        throw new Error(`[抖音解密] 部分字段未解密: ${Object.keys(mapping).length}/${chunk.length}`);
      }

      return mapping;
    } catch (error) {
      const isBizError = error instanceof DouyinAPIError;
      logger.error('[抖音解密] 批次解密失败,该批字段保持密文:', {
        accountId,
        count: chunk.length,
        ...(isBizError ? error.toJSON() : { message: error.message }),
      });
      if (strict) throw error;
      return {};
    }
  }
}

module.exports = DouyinDecrypt;
module.exports.DECRYPT_BATCH_PATH = DECRYPT_BATCH_PATH;
