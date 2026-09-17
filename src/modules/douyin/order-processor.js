/**
 * 抖音订单处理器
 * 负责多商户订单的获取、解密和字段提取
 */

const fs = require('fs');
const path = require('path');
const logger = require('../../utils/logger');

class OrderProcessor {
  constructor(douyinModule) {
    this.douyin = douyinModule;
    this.accountsConfig = null;
  }

  /**
   * 加载商户账户配置
   */
  loadAccountsConfig() {
    try {
      const configPath = path.join(__dirname, '../../../data/accounts.json');
      const data = fs.readFileSync(configPath, 'utf-8');
      this.accountsConfig = JSON.parse(data);

      // 只加载启用的账户
      const enabledAccounts = this.accountsConfig.filter(acc => acc.enabled);
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
   * 查询单个商户的订单列表
   * @param {string} accountId - 商户账户ID
   * @param {number} pageSize - 每页订单数
   * @returns {Promise<Array>} 订单列表
   */
  async getAccountOrders(accountId, pageSize = 20) {
    try {
      const token = await this.douyin.api.getAccessToken();

      logger.info('[订单处理器] 查询商户订单:', { accountId, pageSize });

      const axios = require('axios');
      const response = await axios.get(
        'https://open.douyin.com/goodlife/v1/trade/order/query/',
        {
          headers: {
            'access-token': token,
            'content-type': 'application/json',
          },
          params: {
            account_id: accountId,
            page_num: 1,
            page_size: pageSize,
          },
        }
      );

      if (response.data.extra.error_code !== 0) {
        throw new Error(
          `查询失败: ${response.data.extra.description} (${response.data.extra.error_code})`
        );
      }

      const orders = response.data.data.orders || [];
      logger.info('[订单处理器] 商户订单查询成功:', {
        accountId,
        count: orders.length,
      });

      return orders;
    } catch (error) {
      logger.error('[订单处理器] 查询商户订单失败:', {
        accountId,
        error: error.message,
      });
      throw error;
    }
  }

  /**
   * 处理单个订单(获取详情、解密、提取字段)
   * @param {string} orderId - 订单ID
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 处理后的订单数据
   */
  async processOrder(orderId, accountId) {
    try {
      // 1. 获取订单详情
      const order = await this.douyin.getOrderDetail(orderId, accountId);

      if (!order) {
        throw new Error('订单不存在');
      }

      // 2. 收集需要解密的字段
      const encryptedFields = [];
      if (order.contacts?.[0]?.phone && order.contacts[0].phone.startsWith('Enc.')) {
        encryptedFields.push(order.contacts[0].phone);
      }

      // 3. 批量解密
      let decryptedData = {};
      if (encryptedFields.length > 0) {
        logger.info('[订单处理器] 开始解密字段:', {
          orderId,
          count: encryptedFields.length,
        });
        decryptedData = await this.douyin.decryptFields(encryptedFields, accountId);
      }

      // 4. 提取格式化字段
      const extracted = this.douyin.extractOrderFields(order, decryptedData);

      logger.info('[订单处理器] 订单处理完成:', {
        orderId,
        customerPhone: extracted.customerPhone,
        productName: extracted.productName,
      });

      return extracted;
    } catch (error) {
      logger.error('[订单处理器] 处理订单失败:', {
        orderId,
        accountId,
        error: error.message,
      });
      throw error;
    }
  }

  /**
   * 批量处理多个商户的订单
   * @param {Object} options - 选项
   * @param {number} options.ordersPerAccount - 每个商户获取的订单数
   * @param {boolean} options.processDetails - 是否处理订单详情(解密+提取字段)
   * @returns {Promise<Object>} 处理结果
   */
  async processMultipleAccounts(options = {}) {
    const {
      ordersPerAccount = 10,
      processDetails = true,
    } = options;

    try {
      // 1. 获取access_token(所有商户共用)
      logger.info('[订单处理器] ========== 步骤1: 获取access_token ==========');
      await this.douyin.init();
      const token = this.douyin.api.accessToken;
      logger.info('[订单处理器] ✅ Token获取成功:', token.substring(0, 30) + '...');

      // 2. 加载商户配置
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

      // 3. 遍历每个商户
      logger.info('[订单处理器] ========== 步骤3: 处理各商户订单 ==========');

      for (const account of accounts) {
        logger.info(`\n[订单处理器] --- 处理商户: ${account.accountName} (${account.accountId}) ---`);

        try {
          // 3.1 获取该商户的订单列表
          const orders = await this.getAccountOrders(
            account.accountId,
            ordersPerAccount
          );

          results.totalOrders += orders.length;

          const accountResult = {
            accountId: account.accountId,
            accountName: account.accountName,
            storeId: account.storeId,
            region: account.region,
            ordersCount: orders.length,
            processedOrders: [],
            failedOrders: [],
          };

          // 3.2 如果需要处理详情
          if (processDetails && orders.length > 0) {
            logger.info(`[订单处理器] 开始处理 ${orders.length} 个订单详情...`);

            for (let i = 0; i < orders.length; i++) {
              const order = orders[i];

              try {
                logger.info(`[订单处理器] [${i + 1}/${orders.length}] 处理订单: ${order.order_id}`);

                const processed = await this.processOrder(
                  order.order_id,
                  account.accountId
                );

                // 添加商户信息
                processed.accountId = account.accountId;
                processed.accountName = account.accountName;
                processed.storeId = account.storeId;
                processed.region = account.region;

                accountResult.processedOrders.push(processed);
                results.processedOrders++;

                logger.info(`[订单处理器] ✅ 订单处理成功`);

                // 避免频繁请求
                if (i < orders.length - 1) {
                  await new Promise(resolve => setTimeout(resolve, 500));
                }
              } catch (error) {
                logger.error(`[订单处理器] ❌ 订单处理失败: ${error.message}`);
                accountResult.failedOrders.push({
                  orderId: order.order_id,
                  error: error.message,
                });
                results.failedOrders++;
              }
            }
          }

          results.accountResults.push(accountResult);
          results.processedAccounts++;

          logger.info(`[订单处理器] ✅ 商户处理完成: ${accountResult.processedOrders.length}/${orders.length} 成功`);

        } catch (error) {
          logger.error(`[订单处理器] ❌ 商户处理失败: ${error.message}`);
          results.accountResults.push({
            accountId: account.accountId,
            accountName: account.accountName,
            error: error.message,
            ordersCount: 0,
            processedOrders: [],
            failedOrders: [],
          });
        }
      }

      // 4. 汇总结果
      logger.info('[订单处理器] ========== 处理完成 ==========');
      logger.info('[订单处理器] 汇总:', {
        商户数: results.processedAccounts,
        总订单数: results.totalOrders,
        成功处理: results.processedOrders,
        失败: results.failedOrders,
      });

      return results;
    } catch (error) {
      logger.error('[订单处理器] 批量处理失败:', error);
      throw error;
    }
  }
}

module.exports = OrderProcessor;
