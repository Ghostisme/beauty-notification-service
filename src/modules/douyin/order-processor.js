/**
 * 抖音订单处理器
 *
 * 职责:按 data/accounts.json 里的商户列表批量拉单 → 解密敏感字段 → 提取推送所需字段。
 *
 * 注意本文件不做以下事情,它们已下沉到更底层的单职责模块,在这里重复实现只会不一致:
 *   - HTTP 调用与错误码判定 → http-client
 *   - token 获取/刷新       → token-manager
 *   - 请求节流与退避         → http-client(故此处不再手写 setTimeout 限速)
 *   - order.query 参数拼装   → order-query
 *   - 加密字段的收集与回填   → sensitive-fields
 */

const fs = require('fs');
const path = require('path');
const logger = require('../../utils/logger');
const { collectEncryptedValues, applyDecryptedValues } = require('./sensitive-fields');

/** 商户配置文件路径,相对本文件定位,避免受进程工作目录影响 */
const ACCOUNTS_CONFIG_PATH = path.join(__dirname, '../../../data/accounts.json');

class OrderProcessor {
  /**
   * @param {import('./index')} douyinModule - 抖音模块入口,提供 api / 解密 / 字段提取能力
   */
  constructor(douyinModule) {
    this.douyin = douyinModule;
    this.accountsConfig = null;
  }

  /**
   * 加载并返回启用中的商户账户配置。
   * @returns {Array<Object>} enabled 为 true 的商户列表
   * @throws {Error} 配置文件缺失或格式非法
   */
  loadAccountsConfig() {
    try {
      const data = fs.readFileSync(ACCOUNTS_CONFIG_PATH, 'utf-8');
      this.accountsConfig = JSON.parse(data);

      const enabledAccounts = this.accountsConfig.filter((acc) => acc.enabled);
      logger.info('[订单处理器] 已加载商户配置:', {
        total: this.accountsConfig.length,
        enabled: enabledAccounts.length,
      });

      return enabledAccounts;
    } catch (error) {
      logger.error('[订单处理器] 加载商户配置失败:', error);
      throw new Error('无法加载商户配置文件');
    }
  }

  /**
   * 查询单个商户的订单列表。
   *
   * @param {string} accountId - 商户账户 ID
   * @param {number} [pageSize=20] - 每页订单数(1~100)
   * @param {Object} [filters] - 附加筛选条件,见 OrderQueryAPI#queryPage
   * @returns {Promise<Array<Object>>} 订单列表
   */
  async getAccountOrders(accountId, pageSize = 20, filters = {}) {
    logger.info('[订单处理器] 查询商户订单:', { accountId, pageSize });

    const { orders } = await this.douyin.api.queryOrders({
      ...filters,
      accountId,
      pageNum: 1,
      pageSize,
    });

    logger.info('[订单处理器] 商户订单查询成功:', {
      accountId,
      count: orders.length,
    });

    return orders;
  }

  /**
   * 处理单个订单:拉详情 → 解密敏感字段 → 提取推送字段。
   *
   * @param {string} orderId - 订单 ID
   * @param {string} accountId - 商户账户 ID
   * @returns {Promise<Object>} 格式化后的订单信息,见 DouyinModule#extractOrderFields
   * @throws {Error} 订单不存在,或详情查询失败
   */
  async processOrder(orderId, accountId) {
    const order = await this.douyin.getOrderDetail(orderId, accountId);

    if (!order) {
      throw new Error('订单不存在');
    }

    return this.decryptAndExtract(order, accountId);
  }

  /**
   * 对已拿到的订单对象做解密与字段提取。
   *
   * 单独抽出来是因为列表接口返回的订单已含全部字段,批量场景下不必再逐单查详情;
   * processOrder 只是它"先查详情"的变体。
   *
   * @param {Object} order - 订单对象(会被就地回填明文)
   * @param {string} accountId - 商户账户 ID
   * @returns {Promise<Object>} 格式化后的订单信息
   */
  async decryptAndExtract(order, accountId) {
    const encryptedValues = collectEncryptedValues(order);

    if (encryptedValues.length > 0) {
      logger.info('[订单处理器] 开始解密字段:', {
        orderId: order.order_id,
        count: encryptedValues.length,
      });

      const decryptedMap = await this.douyin.decryptFields(encryptedValues, accountId);
      // 原地回填,后续 extractOrderFields 直接读到明文,不必再传解密映射
      const filled = applyDecryptedValues(order, decryptedMap);

      const remaining = collectEncryptedValues(order).length;
      if (remaining > 0) {
        // 部分字段解不出属预期内降级(如无解密权限),记 warn 便于排查而非中断
        logger.warn('[订单处理器] 部分字段未解密成功,将保持密文:', {
          orderId: order.order_id,
          expected: encryptedValues.length,
          filled,
          remaining,
        });
      }
    }

    const extracted = this.douyin.extractOrderFields(order);
    extracted.decryptionStatus = encryptedValues.length === 0 ? 'not_needed'
      : collectEncryptedValues(order).length === 0 ? 'complete' : 'incomplete';

    logger.info('[订单处理器] 订单处理完成:', {
      orderId: extracted.orderId,
      productName: extracted.productName,
    });

    return extracted;
  }

  /**
   * 批量处理多个商户的订单。
   *
   * 商户之间串行执行:失败隔离在单个商户内,某商户未授权不影响其余商户出单。
   * 请求间隔由 http-client 的全局节流统一保证,这里不再额外 sleep。
   *
   * @param {Object} [options]
   * @param {number} [options.ordersPerAccount=10] - 每个商户拉取的订单数
   * @param {boolean} [options.processDetails=true] - 是否解密并提取字段
   * @param {Object} [options.filters] - 透传给订单查询的筛选条件(状态、时间区间等)
   * @returns {Promise<Object>} 汇总结果
   */
  async processMultipleAccounts(options = {}) {
    const {
      ordersPerAccount = 10,
      processDetails = true,
      filters = {},
    } = options;

    // 预热 token,让凭证/网络问题在拉单前就暴露,而不是散落到每个商户的错误里
    logger.info('[订单处理器] ========== 步骤1: 获取access_token ==========');
    await this.douyin.init();
    logger.info('[订单处理器] ✅ Token就绪:', this.douyin.api.getTokenStatus());

    logger.info('[订单处理器] ========== 步骤2: 加载商户配置 ==========');
    const accounts = this.loadAccountsConfig();

    const results = {
      totalAccounts: accounts.length,
      processedAccounts: 0,
      totalOrders: 0,
      processedOrders: 0,
      failedOrders: 0,
      accountResults: [],
    };

    logger.info('[订单处理器] ========== 步骤3: 处理各商户订单 ==========');

    for (const account of accounts) {
      logger.info(`[订单处理器] --- 处理商户: ${account.accountName} (${account.accountId}) ---`);

      const accountResult = await this._processAccount(account, {
        ordersPerAccount,
        processDetails,
        filters,
      });

      results.accountResults.push(accountResult);
      results.totalOrders += accountResult.ordersCount;
      results.processedOrders += accountResult.processedOrders.length;
      results.failedOrders += accountResult.failedOrders.length;
      if (!accountResult.error) results.processedAccounts++;
    }

    logger.info('[订单处理器] ========== 处理完成 ==========');
    logger.info('[订单处理器] 汇总:', {
      商户数: results.processedAccounts,
      总订单数: results.totalOrders,
      成功处理: results.processedOrders,
      失败: results.failedOrders,
    });

    return results;
  }

  /**
   * 处理单个商户的全部订单,异常收敛在返回值里不外抛。
   *
   * @param {Object} account - 商户配置项
   * @param {Object} options - 见 processMultipleAccounts
   * @returns {Promise<Object>} 该商户的处理结果
   */
  async _processAccount(account, { ordersPerAccount, processDetails, filters }) {
    const accountResult = {
      accountId: account.accountId,
      accountName: account.accountName,
      storeId: account.storeId,
      region: account.region,
      ordersCount: 0,
      processedOrders: [],
      failedOrders: [],
    };

    let orders;
    try {
      orders = await this.getAccountOrders(account.accountId, ordersPerAccount, filters);
    } catch (error) {
      // 商户级失败(未授权、IP 未加白等)只影响该商户,记录后继续下一个
      logger.error(`[订单处理器] ❌ 商户处理失败: ${error.message}`);
      accountResult.error = error.message;
      return accountResult;
    }

    accountResult.ordersCount = orders.length;

    if (!processDetails || orders.length === 0) {
      return accountResult;
    }

    logger.info(`[订单处理器] 开始处理 ${orders.length} 个订单详情...`);

    for (let i = 0; i < orders.length; i++) {
      const order = orders[i];

      try {
        logger.info(`[订单处理器] [${i + 1}/${orders.length}] 处理订单: ${order.order_id}`);

        // 列表返回的订单已是完整对象,直接解密提取,省掉一次详情查询
        const processed = await this.decryptAndExtract(order, account.accountId);

        Object.assign(processed, {
          accountId: account.accountId,
          accountName: account.accountName,
          storeId: account.storeId,
          region: account.region,
        });

        accountResult.processedOrders.push(processed);
        logger.info('[订单处理器] ✅ 订单处理成功');
      } catch (error) {
        logger.error(`[订单处理器] ❌ 订单处理失败: ${error.message}`);
        accountResult.failedOrders.push({
          orderId: order.order_id,
          error: error.message,
        });
      }
    }

    logger.info(
      `[订单处理器] ✅ 商户处理完成: ${accountResult.processedOrders.length}/${orders.length} 成功`
    );

    return accountResult;
  }
}

module.exports = OrderProcessor;
