/**
 * 抖音开放平台统一请求层
 *
 * 所有 goodlife 业务接口都必须走这里,原因是抖音有三类失败需要统一处置,
 * 散落在各接口里写会不可避免地漏掉某一类:
 *   1. token 被服务端判定失效(2190002/2190008) → 作废缓存 + 强制刷新 + 重试一次
 *   2. 频控与瞬时故障(2119003/2119002/5000001…) → 指数退避重试
 *   3. 配置/权限/参数错误(2119013/2190004…) → 立即失败,并附带运维处置指引
 * 同时在这里做全局 QPS 节流:官方限单服务商应用默认 20 QPS。
 */

const axios = require('axios');
const logger = require('../../utils/logger');
const {
  ERROR_CODE_SUCCESS,
  DouyinAPIError,
  isRetryableNetworkError,
} = require('./errors');

/** 业务失败的默认重试次数(不含首次请求) */
const DEFAULT_MAX_RETRIES = 2;
/** 退避基数(毫秒),实际等待为 base * 2^(n-1) 并叠加抖动 */
const DEFAULT_RETRY_BASE_DELAY = 800;
/**
 * 相邻请求的最小间隔。官方单服务商应用默认 20 QPS,取 60ms(≈16 QPS)留出安全余量,
 * 避免多商户串行拉单时把自己打成 2119003。
 */
const DEFAULT_MIN_REQUEST_INTERVAL = 60;

/**
 * 把环境变量解析为非负整数,非法值回落到默认值。
 * @param {string|undefined} raw - 环境变量原始值
 * @param {number} fallback - 解析失败时的默认值
 * @returns {number}
 */
function toNonNegativeInt(raw, fallback) {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : fallback;
}

class DouyinHttpClient {
  /**
   * @param {import('./token-manager')} tokenManager - token 管理器,用于取/作废 token
   * @param {Object} [options]
   * @param {string} [options.baseURL] - 抖音开放平台域名
   * @param {number} [options.timeout] - 单次请求超时(毫秒)
   * @param {number} [options.maxRetries] - 可重试错误的最大重试次数
   * @param {number} [options.minRequestInterval] - 相邻请求最小间隔(毫秒),用于 QPS 节流
   */
  constructor(tokenManager, options = {}) {
    this.tokenManager = tokenManager;
    this.baseURL = options.baseURL || 'https://open.douyin.com';
    this.timeout = options.timeout ?? 15000;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.retryBaseDelay = options.retryBaseDelay ?? DEFAULT_RETRY_BASE_DELAY;
    // 注意不能写成 `?? Number(env) || DEFAULT`:?? 与 || 混用是语法错误,
    // 且 Number(undefined) 得到的 NaN 不是 nullish,兜不住环境变量缺失的情况
    this.minRequestInterval = options.minRequestInterval
      ?? toNonNegativeInt(process.env.DOUYIN_MIN_REQUEST_INTERVAL, DEFAULT_MIN_REQUEST_INTERVAL);

    // 串行节流队列的"上一个请求允许发出的时刻"。用时间戳而非定时器,
    // 这样并发调用会各自排到不同的时间片上,天然形成匀速发送。
    this._nextAvailableAt = 0;
  }

  /**
   * GET 请求业务接口。
   * @param {string} path - 接口路径,如 /goodlife/v1/trade/order/query/
   * @param {Object} [params] - query 参数
   * @param {Object} [options] - 透传给 request 的选项
   * @returns {Promise<Object>} 响应体的 data 字段
   */
  get(path, params = {}, options = {}) {
    return this.request({ method: 'GET', path, params, ...options });
  }

  /**
   * POST 请求业务接口。
   * @param {string} path - 接口路径
   * @param {Object} [body] - JSON 请求体
   * @param {Object} [options] - 透传给 request 的选项
   * @returns {Promise<Object>} 响应体的 data 字段
   */
  post(path, body = {}, options = {}) {
    return this.request({ method: 'POST', path, body, ...options });
  }

  /**
   * 发起一次带完整容错的抖音接口调用。
   *
   * @param {Object} options
   * @param {string} options.method - HTTP 方法
   * @param {string} options.path - 接口路径
   * @param {Object} [options.params] - query 参数
   * @param {Object} [options.body] - 请求体
   * @param {Object} [options.headers] - 追加的请求头,如 Rpc-Transit-Life-Account
   * @param {number} [options.maxRetries] - 覆盖默认重试次数
   * @returns {Promise<Object>} 响应体的 data 字段(已确认 error_code === 0)
   * @throws {DouyinAPIError} 业务错误且不可重试,或重试耗尽
   */
  async request({ method, path, params, body, headers = {}, maxRetries }) {
    const retryLimit = maxRetries ?? this.maxRetries;
    let tokenReplayed = false;
    let transientRetries = 0;
    let attempt = 0;

    while (true) {
      // Token fetch failures use TokenManager's own retry budget.
      await this._throttle();
      const token = await this.tokenManager.getToken();
      attempt++;
      try {
        const response = await axios.request({
          method,
          url: `${this.baseURL}${path}`,
          params,
          data: body,
          timeout: this.timeout,
          headers: { ...headers, 'access-token': token, 'content-type': 'application/json' },
        });
        return this._unwrap(response.data, path);
      } catch (error) {
        const isBizError = error instanceof DouyinAPIError;
        const tokenError = isBizError && error.needRefreshToken;
        if (tokenError) {
          this.tokenManager.invalidate(token);
        }
        // One auth replay independent of the network retry budget. Stale
        // failures reuse an already-refreshed token rather than force-refreshing it.
        const retryToken = tokenError && !tokenReplayed;
        const retryTransient = !tokenError && transientRetries < retryLimit
          && (isBizError ? error.retryable : isRetryableNetworkError(error));
        logger.error('[抖音请求] 调用失败', {
          api: path, attempt, willRetry: retryToken || retryTransient,
          ...(isBizError ? error.toJSON() : { message: error.message, status: error.response?.status }),
        });
        if (retryToken) {
          tokenReplayed = true;
          continue;
        }
        if (!retryTransient) throw error;
        await this._sleep(this._backoffDelay(transientRetries++));
      }
    }
  }

  /**
   * 校验抖音响应并剥出 data。
   *
   * 抖音把业务错误码放在 extra 里且 HTTP 恒为 200,所以这里是成败的唯一判定点。
   * extra 缺失时按"网关异常"处理 —— 直接读 extra.error_code 会抛 TypeError,
   * 把真实原因(通常是被前置网关拦截)掩盖成一个看不懂的类型错误。
   *
   * @param {Object} payload - 响应体
   * @param {string} api - 接口路径,用于错误上下文
   * @returns {Object} data 字段
   */
  _unwrap(payload, api) {
    const extra = payload?.extra;
    const data = payload?.data;
    const statuses = [extra, data].filter((part) => part && part.error_code !== undefined);
    if (!statuses.length) {
      throw new DouyinAPIError({ errorCode: -1, description: '响应缺少 error_code', api });
    }
    for (const status of statuses) {
      const code = Number(status.error_code);
      if (!Number.isFinite(code) || status.error_code === null || status.error_code === '') {
        throw new DouyinAPIError({ errorCode: -1, description: '响应 error_code 格式异常', api });
      }
      if (code !== ERROR_CODE_SUCCESS) {
        throw new DouyinAPIError({
          errorCode: code, description: status.description,
          subErrorCode: status.sub_error_code, subDescription: status.sub_description,
          logId: extra?.logid || status.logid, api,
        });
      }
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new DouyinAPIError({ errorCode: -1, description: '成功响应缺少有效 data', api });
    }
    return data;
  }

  /**
   * QPS 节流:把请求排到距上一次至少 minRequestInterval 毫秒之后。
   * 先占位再等待,使并发调用者依次拿到不同时间片,而非同时醒来。
   */
  async _throttle() {
    if (this.minRequestInterval <= 0) return;

    const now = Date.now();
    const scheduledAt = Math.max(now, this._nextAvailableAt);
    this._nextAvailableAt = scheduledAt + this.minRequestInterval;

    const waitMs = scheduledAt - now;
    if (waitMs > 0) await this._sleep(waitMs);
  }

  /**
   * 指数退避 + 随机抖动。
   * 抖动用于打散多商户并发重试的同步效应,否则它们会在同一时刻再次撞上频控。
   * @param {number} attempt - 已失败的次数(从 0 开始)
   * @returns {number} 等待毫秒数
   */
  _backoffDelay(attempt) {
    const base = this.retryBaseDelay * 2 ** attempt;
    return base + Math.floor(Math.random() * 300);
  }

  _sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

module.exports = DouyinHttpClient;
