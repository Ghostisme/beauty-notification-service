/**
 * 抖音 API 组合层
 *
 * 本文件不再自己发 HTTP 请求,只负责把下列单职责模块装配起来并对外暴露稳定接口:
 *   token-manager  → access_token 的获取/提前刷新/失效作废/并发去重
 *   http-client    → 统一请求出口(业务错误码判定、退避重试、QPS 节流)
 *   order-query    → order.query 接口封装(分页、游标、多种查询维度)
 *
 * 保持 init / getAccessToken / getOrderDetail 的既有签名不变:
 * debug-order.js、debug-phone.js、douyin-flow.js、test-douyin*.js 都在直接调用它们。
 */

const TokenManager = require('./token-manager');
const DouyinHttpClient = require('./http-client');
const OrderQueryAPI = require('./order-query');
const logger = require('../../utils/logger');

class DouyinAPI {
  /**
   * @param {Object} [options] - 透传给 TokenManager / DouyinHttpClient 的覆盖项,便于测试注入
   * @param {string} [options.baseURL] - 抖音开放平台域名
   * @param {string} [options.clientKey] - 覆盖配置中的 client_key
   * @param {string} [options.clientSecret] - 覆盖配置中的 client_secret
   * @param {number} [options.minRequestInterval] - 相邻请求最小间隔(毫秒)
   */
  constructor(options = {}) {
    this.baseURL = options.baseURL || 'https://open.douyin.com';

    this.tokenManager = new TokenManager({
      baseURL: this.baseURL,
      clientKey: options.clientKey,
      clientSecret: options.clientSecret,
      refreshAdvanceSeconds: options.refreshAdvanceSeconds,
      maxRetries: options.tokenMaxRetries,
      timeout: options.tokenTimeout,
    });

    this.http = new DouyinHttpClient(this.tokenManager, {
      baseURL: this.baseURL,
      minRequestInterval: options.minRequestInterval,
      maxRetries: options.httpMaxRetries,
      timeout: options.httpTimeout,
    });

    this.orderQuery = new OrderQueryAPI(this.http);
  }

  /**
   * 初始化:预热 access_token,让配置错误在启动期暴露而不是等第一笔订单进来才炸。
   * @returns {Promise<void>}
   */
  async init() {
    try {
      await this.getAccessToken();
      logger.info('[抖音API] 初始化成功');
    } catch (error) {
      logger.error('[抖音API] 初始化失败:', { message: error.message });
      throw error;
    }
  }

  /**
   * 获取可用的 access_token。
   *
   * 缓存与刷新策略全部下沉到 TokenManager,这里只做转发。
   *
   * @param {Object} [options]
   * @param {boolean} [options.forceRefresh=false] - 忽略缓存强制换新
   * @returns {Promise<string>} access_token
   */
  getAccessToken(options = {}) {
    return this.tokenManager.getToken(options);
  }

  /**
   * token 状态快照,供健康检查/诊断使用。
   * @returns {{hasToken: boolean, expireAt: string|null, remainSeconds: number, refreshing: boolean}}
   */
  getTokenStatus() {
    return this.tokenManager.getStatus();
  }

  /**
   * 查询订单详情。
   *
   * @param {string} orderId - 抖音生活服务订单 ID
   * @param {string} accountId - 来客商户根账户 ID
   * @returns {Promise<Object|null>} 订单对象,不存在时返回 null
   */
  async getOrderDetail(orderId, accountId) {
    logger.info('[抖音API] 开始查询订单详情:', { orderId, accountId });

    const order = await this.orderQuery.queryByOrderId(orderId, accountId);
    if (order) {
      logger.info('[抖音API] 订单详情获取成功:', {
        orderId: order.order_id,
        productName: order.products?.[0]?.product_name,
      });
    }

    return order;
  }

  /**
   * 分页查询订单列表。
   * @param {Object} options - 见 OrderQueryAPI#queryPage
   * @returns {Promise<Object>} 归一化的分页结果
   */
  queryOrders(options) {
    return this.orderQuery.queryPage(options);
  }

  /**
   * 遍历取回满足条件的全部订单(自动翻页,深翻页时自动切游标)。
   * @param {Object} options - 见 OrderQueryAPI#iterate
   * @returns {Promise<Array<Object>>} 订单数组
   */
  queryAllOrders(options) {
    return this.orderQuery.queryAll(options);
  }
}

module.exports = DouyinAPI;
