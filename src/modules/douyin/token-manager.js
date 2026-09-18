/**
 * 抖音 access_token 生命周期管理
 *
 * 服务商应用用 client_token 模式(不需要用户授权),token 有效期 7200 秒。
 * 失效有两条独立路径,必须都覆盖,否则整批请求会成片失败:
 *   1. 时间到期 —— 主动提前刷新(本模块的 refreshAdvanceSeconds)
 *   2. 服务端吊销 —— 抖音返回 2190002/2190008,由调用方触发 invalidate() 后强制刷新
 * 只做第 1 条在时钟漂移或抖音侧提前吊销时会漏。
 */

const axios = require('axios');
const config = require('../../config');
const logger = require('../../utils/logger');
const { isRetryableNetworkError } = require('./errors');

/** token 有效期结束前多久就主动换新,留足够余量给在途请求 */
const DEFAULT_REFRESH_ADVANCE_SECONDS = 300;
/** client_token 接口自身的网络重试次数 */
const DEFAULT_MAX_RETRIES = 3;
/** 拿不到 expires_in 时的兜底有效期,与文档一致 */
const FALLBACK_EXPIRES_IN = 7200;

/**
 * 把环境变量解析为非负整数,非法值回落到默认值。
 * @param {string|undefined} raw - 环境变量原始值
 * @param {number} fallback - 解析失败时的默认值
 * @returns {number}
 */
function toPositiveInt(raw, fallback) {
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : fallback;
}

class TokenManager {
  /**
   * @param {Object} [options]
   * @param {string} [options.baseURL] - 抖音开放平台域名
   * @param {string} [options.clientKey] - 应用 client_key,默认取配置
   * @param {string} [options.clientSecret] - 应用 client_secret,默认取配置
   * @param {number} [options.refreshAdvanceSeconds] - 提前刷新秒数
   * @param {number} [options.maxRetries] - 获取 token 的网络重试次数
   * @param {number} [options.timeout] - 单次请求超时(毫秒)
   */
  constructor(options = {}) {
    this.baseURL = options.baseURL || 'https://open.douyin.com';
    this.clientKey = options.clientKey ?? config.douyin.clientKey;
    this.clientSecret = options.clientSecret ?? config.douyin.clientSecret;
    // 不能写成 `?? Number(env) ?? DEFAULT`:env 缺失时 Number(undefined) 得到 NaN,
    // 而 NaN 不是 nullish,兜底分支不会生效,会一路算出 NaN 的过期时间
    this.refreshAdvanceSeconds = options.refreshAdvanceSeconds
      ?? toPositiveInt(process.env.DOUYIN_TOKEN_REFRESH_ADVANCE, DEFAULT_REFRESH_ADVANCE_SECONDS);
    this.maxRetries = Math.max(1, toPositiveInt(options.maxRetries, DEFAULT_MAX_RETRIES));
    this.timeout = options.timeout ?? 10000;

    this.accessToken = null;
    this.tokenExpireTime = 0;
    this.tokenRefreshTime = 0;

    // 并发去重:多个请求同时发现 token 过期时,只允许一次真实刷新,其余复用同一 promise。
    // 不做这层会并发打多次 client_token,抖音侧后发的 token 顶掉先发的,先发方拿到已失效的 token。
    this._refreshPromise = null;
  }

  /**
   * 获取可用的 access_token。
   *
   * @param {Object} [options]
   * @param {boolean} [options.forceRefresh=false] - 忽略缓存强制换新,用于处理服务端吊销
   * @returns {Promise<string>} access_token
   */
  async getToken({ forceRefresh = false } = {}) {
    if (this._refreshPromise) return this._refreshPromise;
    if (!forceRefresh && this._isCacheValid()) {
      return this.accessToken;
    }

    // 已有刷新在途则直接搭车,避免并发风暴
    if (this._refreshPromise) {
      return this._refreshPromise;
    }

    this._refreshPromise = this._refresh().finally(() => {
      this._refreshPromise = null;
    });

    return this._refreshPromise;
  }

  /**
   * 标记当前 token 已失效。
   *
   * 由请求层在收到 2190002/2190008 时调用:抖音认为 token 不可用,本地缓存的
   * 过期时间就不可信了,必须清掉,否则 _isCacheValid() 会继续返回死 token。
   */
  invalidate(expectedToken = null) {
    // A request can fail after another concurrent request has already refreshed
    // the token.  Do not let the stale request wipe out the newer token.
    if (!this.accessToken || (expectedToken && this.accessToken !== expectedToken)) return false;

    logger.warn('[抖音Token] 主动作废当前 access_token(服务端判定失效)');
    this.accessToken = null;
    this.tokenExpireTime = 0;
    this.tokenRefreshTime = 0;
    return true;
  }

  /**
   * 当前 token 状态快照,供健康检查/诊断接口使用。
   * @returns {{hasToken: boolean, expireAt: string|null, remainSeconds: number, refreshing: boolean}}
   */
  getStatus() {
    const remainMs = this.tokenExpireTime - Date.now();
    return {
      hasToken: Boolean(this.accessToken),
      expireAt: this.tokenExpireTime ? new Date(this.tokenExpireTime).toISOString() : null,
      refreshAt: this.tokenRefreshTime ? new Date(this.tokenRefreshTime).toISOString() : null,
      remainSeconds: Math.max(0, Math.floor(remainMs / 1000)),
      refreshing: Boolean(this._refreshPromise),
    };
  }

  /** 缓存是否仍在有效期内(已扣除提前刷新余量) */
  _isCacheValid() {
    return Boolean(this.accessToken) && Date.now() < this.tokenRefreshTime;
  }

  /**
   * 真正调用 client_token 接口换取新 token,带网络层退避重试。
   * @returns {Promise<string>}
   */
  async _refresh() {
    if (!this.clientKey || !this.clientSecret) {
      throw new Error('[抖音Token] 缺少 DOUYIN_CLIENT_KEY / DOUYIN_CLIENT_SECRET 配置');
    }

    let lastError;

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        const requestedAt = Date.now();
        const response = await axios.post(
          `${this.baseURL}/oauth/client_token/`,
          {
            client_key: this.clientKey,
            client_secret: this.clientSecret,
            grant_type: 'client_credential',
          },
          {
            headers: { 'Content-Type': 'application/json' },
            timeout: this.timeout,
          }
        );

        return this._acceptToken(response.data, requestedAt);
      } catch (error) {
        lastError = error;

        const canRetry = attempt < this.maxRetries && isRetryableNetworkError(error);
        logger.error('[抖音Token] 获取 access_token 失败', {
          attempt,
          maxRetries: this.maxRetries,
          willRetry: canRetry,
          message: error.message,
        });

        if (!canRetry) break;

        // 指数退避:1s → 2s → 4s,避开抖音侧的瞬时抖动
        await this._sleep(1000 * 2 ** (attempt - 1));
      }
    }

    throw lastError;
  }

  /**
   * 校验并缓存 client_token 响应。
   * @param {Object} payload - 接口原始响应体
   * @returns {string} access_token
   */
  _acceptToken(payload, requestedAt = Date.now()) {
    const token = payload?.data?.access_token;
    const code = payload?.extra?.error_code || payload?.data?.error_code;
    if (typeof token !== 'string' || !token || (code && Number(code) !== 0)) {
      // 这里不重试:响应结构不对通常是 client_key/secret 配错,重试只是放大错误
      throw new Error(`[抖音Token] client_token 响应异常: error_code=${code ?? 'missing'}, logid=${payload?.extra?.logid || ''}`);
    }

    const expiresIn = Number(payload.data.expires_in ?? FALLBACK_EXPIRES_IN);
    if (!Number.isFinite(expiresIn) || expiresIn <= 0) {
      throw new Error('[抖音Token] expires_in 必须为正数');
    }
    // Never extend a short-lived token beyond its actual expiry.
    const advance = Math.min(Math.max(0, this.refreshAdvanceSeconds), expiresIn / 2);
    const effectiveLifetime = expiresIn - advance;
    if (requestedAt + effectiveLifetime * 1000 <= Date.now()) {
      throw new Error('[抖音Token] 响应耗时超过 token 可用期');
    }

    this.accessToken = token;
    this.tokenExpireTime = requestedAt + expiresIn * 1000;
    this.tokenRefreshTime = requestedAt + effectiveLifetime * 1000;

    logger.info('[抖音Token] access_token 获取成功', {
      expiresIn,
      effectiveLifetime,
      expireAt: new Date(this.tokenExpireTime).toISOString(),
    });

    return token;
  }

  _sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

module.exports = TokenManager;
