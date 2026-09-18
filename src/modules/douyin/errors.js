/**
 * 抖音开放平台错误码定义与异常封装
 *
 * 抖音的业务错误码放在 HTTP 200 响应体的 extra.error_code 里,HTTP 状态码本身
 * 反映不了成败(权限不足、IP 未加白、token 过期全都是 200)。所以所有接口调用
 * 都必须经过本模块判定,不能只靠 try/catch 捕获网络异常。
 */

/**
 * 错误码 → 处置策略表。
 *
 * - refreshToken: 该错误说明手里的 access_token 已不可用,需强制刷新后重试一次
 * - retryable:    抖音侧的瞬时故障/频控,退避后原样重试有意义
 * - 两者都没有:   配置或参数问题,重试只会放大无效流量,必须直接失败并给出处置指引
 *
 * hint 是给运维看的"下一步做什么",区别于抖音返回的 description(只说现象不说处置)。
 */
const ERROR_POLICY = {
  2190002: {
    refreshToken: true,
    hint: 'access_token 无效;请求层最多重新获取并重试一次',
  },
  2190008: {
    refreshToken: true,
    hint: 'access_token 已过期;请求层最多重新获取并重试一次',
  },
  2190004: {
    hint: '应用未获得 life.capacity.order.query 能力,需到服务商平台「控制台 → 应用详情 → 解决方案」申请接口权限',
  },
  2119005: {
    hint: '应用未获得该商家授权,需商家在来客后台发起授权,再由服务商后台同意',
  },
  2119013: {
    hint: '请求来源 IP 不在白名单。需到服务商平台「基础配置 → IP白名单配置」添加服务器公网出口 IP;'
      + '注意添加的是抖音实际看到的出口 IP;代理分流和动态拨号可能导致出口变化,建议使用固定出口',
  },
  2119001: {
    hint: '请求参数不合法,核对 account_id、分页参数(page_size 1~100)、时间区间是否成对传入',
  },
  2119002: { retryable: true, hint: '抖音系统繁忙,退避后重试' },
  2119003: { retryable: true, hint: '请求过于频繁,单服务商应用默认 20 QPS,退避后重试' },
  2100001: { retryable: true, hint: '抖音未知错误,重试 3 次仍失败需联系抖音技术支持' },
  2100004: { retryable: true, hint: '抖音系统繁忙,退避后重试' },
  2100005: { hint: '请求参数不合法,核对参数枚举值是否在文档允许范围内' },
  5000001: { retryable: true, hint: '抖音服务异常,重试仍失败需联系抖音处理' },
};

/** 业务成功的 error_code */
const ERROR_CODE_SUCCESS = 0;

/**
 * 抖音接口业务异常。
 *
 * 与网络异常(axios error)区分开:本异常一定意味着"请求打通了,但抖音拒绝了",
 * 因此携带 logId 便于向抖音技术支持提单排查。
 */
class DouyinAPIError extends Error {
  /**
   * @param {Object} options
   * @param {number} options.errorCode - extra.error_code
   * @param {string} [options.description] - 抖音返回的错误描述
   * @param {number} [options.subErrorCode] - extra.sub_error_code
   * @param {string} [options.subDescription] - extra.sub_description
   * @param {string} [options.logId] - extra.logid,提单排查用
   * @param {string} [options.api] - 触发异常的接口路径,便于定位
   */
  constructor({ errorCode, description, subErrorCode, subDescription, logId, api }) {
    const policy = ERROR_POLICY[errorCode] || {};
    const parts = [`[${errorCode}] ${description || '未知错误'}`];
    if (subDescription) parts.push(`(子错误 ${subErrorCode}: ${subDescription})`);
    if (policy.hint) parts.push(`→ ${policy.hint}`);

    super(parts.join(' '));

    this.name = 'DouyinAPIError';
    this.errorCode = errorCode;
    this.description = description;
    this.subErrorCode = subErrorCode;
    this.subDescription = subDescription;
    this.logId = logId;
    this.api = api;
    /** 是否可退避重试 */
    this.retryable = Boolean(policy.retryable);
    /** 是否需要先强制刷新 access_token 再重试 */
    this.needRefreshToken = Boolean(policy.refreshToken);
    /** 面向运维的处置建议 */
    this.hint = policy.hint || '';
  }

  /** 结构化输出,供 logger 记录 */
  toJSON() {
    return {
      errorCode: this.errorCode,
      description: this.description,
      subErrorCode: this.subErrorCode,
      logId: this.logId,
      api: this.api,
      retryable: this.retryable,
      needRefreshToken: this.needRefreshToken,
      hint: this.hint,
    };
  }
}

/**
 * 判断 axios 抛出的网络层异常是否值得重试。
 *
 * 连接类错误(超时、连接重置、DNS 抖动)和 5xx 是瞬时的;4xx 说明请求本身有问题,
 * 重试无意义。注意抖音的业务错误走 200,不会落到这里。
 *
 * @param {Error} error - axios 异常
 * @returns {boolean}
 */
function isRetryableNetworkError(error) {
  const TRANSIENT_CODES = ['ECONNABORTED', 'ETIMEDOUT', 'ECONNRESET', 'EAI_AGAIN', 'ENOTFOUND', 'ECONNREFUSED'];
  if (TRANSIENT_CODES.includes(error.code)) return true;

  const status = error.response?.status;
  return typeof status === 'number' && status >= 500;
}

module.exports = {
  ERROR_CODE_SUCCESS,
  ERROR_POLICY,
  DouyinAPIError,
  isRetryableNetworkError,
};
