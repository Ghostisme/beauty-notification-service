/**
 * 抖音生活服务「订单查询」接口封装
 *
 * 官方文档: https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/
 *           OpenAPI/general-capabilities/order.query/query
 * 接口: GET /goodlife/v1/trade/order/query/  scope: life.capacity.order.query
 *
 * 全项目对该接口的唯一出口。此前 api.js 与 order-processor.js 各自实现过一遍
 * 同样的 HTTP 调用,参数拼法和错误处理都不一致,改一处必漏一处 —— 收敛到这里。
 *
 * 文档中的三种查询姿势,分别对应本模块的三个方法:
 *   1. 商户 + order_id/ext_order_id      → queryByOrderId / queryByExtOrderId(订单详情)
 *   2. 商户 + 状态 + 时间区间             → queryPage / iterate(对账、增量拉单)
 *   3. 商户 + open_id + 时间区间          → queryPage({ openId })(查某用户的订单)
 * 注:接口不支持酒店行业订单。
 */

const logger = require('../../utils/logger');

/** 接口路径 */
const ORDER_QUERY_PATH = '/goodlife/v1/trade/order/query/';

/**
 * 订单状态枚举(订单维度)。
 * 文档口径:0 初始化 / 100 待支付(15 分钟等待期) / 101 支付取消 / 200 已支付 /
 * 201 待使用(发码成功) / 1 已完成(履约完成或全部退款) / 150 部分支付。
 */
const ORDER_STATUS = {
  INIT: 0,
  WAIT_PAY: 100,
  PAY_CANCELED: 101,
  PAID: 200,
  WAIT_USE: 201,
  FINISHED: 1,
  PARTIAL_PAID: 150,
};

/** 文档规定 page_size 取值 1~100 */
const PAGE_SIZE_MAX = 100;
const PAGE_SIZE_DEFAULT = 20;
/**
 * page 翻页的深度上限:文档要求 page_num × page_size ≤ 10000,
 * 超过必须改用 cursor 翻页,否则抖音直接报参数不合法。
 */
const PAGE_DEPTH_LIMIT = 10000;
/** cursor 翻页的首页游标,文档规定传 "0" */
const CURSOR_FIRST_PAGE = '0';
/** iterate 的默认页数上限,防止配置失误导致无限翻页打爆频控 */
const DEFAULT_MAX_PAGES = 50;

class OrderQueryAPI {
  /**
   * @param {import('./http-client')} httpClient - 统一请求层(已内置 token 刷新/重试/节流)
   */
  constructor(httpClient) {
    this.http = httpClient;
  }

  /**
   * 查询一页订单。
   *
   * @param {Object} options
   * @param {string} options.accountId - 来客商户根账户 ID(必填)
   * @param {number} [options.pageNum=1] - 页码,从 1 开始
   * @param {number} [options.pageSize=20] - 每页条数,1~100
   * @param {number} [options.orderStatus] - 订单状态,见 ORDER_STATUS
   * @param {string} [options.orderId] - 抖音生活服务订单 ID
   * @param {string} [options.extOrderId] - 开发者系统中的订单号
   * @param {string} [options.openId] - 抖音用户唯一标识
   * @param {number} [options.createTimeStart] - 创单起始时间(秒级时间戳)
   * @param {number} [options.createTimeEnd] - 创单结束时间(秒级时间戳)
   * @param {number} [options.updateTimeStart] - 订单修改起始时间(秒级时间戳)
   * @param {number} [options.updateTimeEnd] - 订单修改结束时间(秒级时间戳)
   * @param {string|string[]} [options.cursor] - 游标翻页;首页传 "0",后续传上一页返回的 nextCursor
   * @param {string} [options.lifeAccountId] - Rpc-Transit-Life-Account 头,少数场景需要
   * @returns {Promise<{orders: Array<Object>, page: {pageNum: number, pageSize: number, total: number},
   *   nextCursor: string|null, hasMore: boolean, raw: Object}>}
   */
  async queryPage(options = {}) {
    const params = this._buildParams(options);
    const headers = options.lifeAccountId
      ? { 'Rpc-Transit-Life-Account': options.lifeAccountId }
      : {};

    const data = await this.http.get(ORDER_QUERY_PATH, params, { headers });

    return this._normalize(data, params);
  }

  /**
   * 按订单 ID 查询详情。
   *
   * 文档口径:该维度只返回订单维度信息,不支持券维度。查询时间与订单完成时间接近时
   * 可能查不到(数据同步延迟),文档建议延迟 2~3 秒或加重试 —— 这由调用方按业务决定,
   * 本方法不隐式等待,以免拖慢批量场景。
   *
   * @param {string} orderId - 抖音生活服务订单 ID
   * @param {string} accountId - 来客商户根账户 ID
   * @returns {Promise<Object|null>} 订单对象,不存在时返回 null
   */
  async queryByOrderId(orderId, accountId) {
    if (typeof orderId !== 'string' || !orderId.trim()) throw new Error('[订单查询] orderId 必须为非空字符串');
    const { orders } = await this.queryPage({
      accountId,
      orderId,
      pageNum: 1,
      pageSize: 1,
    });

    if (orders.length === 0) {
      logger.warn('[订单查询] 订单不存在', { orderId, accountId });
      return null;
    }

    return orders[0];
  }

  /**
   * 按开发者侧订单号查询详情。
   * @param {string} extOrderId - 开发者系统中的订单号
   * @param {string} accountId - 来客商户根账户 ID
   * @returns {Promise<Object|null>} 订单对象,不存在时返回 null
   */
  async queryByExtOrderId(extOrderId, accountId) {
    if (typeof extOrderId !== 'string' || !extOrderId.trim()) throw new Error('[订单查询] extOrderId 必须为非空字符串');
    const { orders } = await this.queryPage({
      accountId,
      extOrderId,
      pageNum: 1,
      pageSize: 1,
    });

    return orders[0] || null;
  }

  /**
   * 翻页遍历订单,自动选择 page / cursor 翻页方式。
   *
   * 翻页策略:默认走 page_num 递增;一旦下一页的 page_num × page_size 触及文档的
   * 10000 深度上限,就切换为 cursor 翻页(cursor 模式下 page_num/page_size 仍需必传)。
   * 这样浅翻页保留 total 可读性,深翻页不会撞上参数校验。
   *
   * @param {Object} options - 同 queryPage,外加下列控制项
   * @param {number} [options.maxPages=50] - 最多翻多少页,防御性上限
   * @param {number} [options.maxOrders] - 累计取到多少条订单后停止
   * @yields {Object} 单个订单对象
   */
  async *iterate(options) {
    const {
      maxPages = DEFAULT_MAX_PAGES,
      maxOrders = Infinity,
      ...queryOptions
    } = options;

    let pageNum = queryOptions.pageNum || 1;
    const pageSize = this._normalizePageSize(queryOptions.pageSize);
    let cursor = queryOptions.cursor || null;
    let emitted = 0;
    if (maxOrders === 0) return;
    if (!(maxOrders > 0) || !Number.isInteger(maxPages) || maxPages < 1) {
      throw new Error('[订单查询] maxOrders / maxPages 参数不合法');
    }
    const seenCursors = new Set(cursor ? [String(cursor)] : []);

    for (let page = 0; page < maxPages; page++) {
      const result = await this.queryPage({
        ...queryOptions,
        pageNum,
        pageSize,
        cursor,
      });

      for (const order of result.orders) {
        yield order;
        if (++emitted >= maxOrders) return;
      }

      if (!result.hasMore) return;

      // 触及 page 翻页深度上限则改用 cursor,否则继续递增页码
      if (cursor !== null || (pageNum + 1) * pageSize > PAGE_DEPTH_LIMIT) {
        if (!result.nextCursor) {
          logger.warn('[订单查询] 已达 page 翻页深度上限且无可用游标,停止翻页', {
            accountId: queryOptions.accountId,
            pageNum,
            pageSize,
          });
          throw new Error('[订单查询] 深翻页缺少下一页游标,结果未完整获取');
        }
        if (seenCursors.has(result.nextCursor)) throw new Error('[订单查询] 平台返回重复游标,已停止翻页');
        seenCursors.add(result.nextCursor);
        cursor = result.nextCursor;
      } else {
        pageNum += 1;
      }
    }

    logger.warn('[订单查询] 达到翻页上限,提前结束', {
      accountId: queryOptions.accountId,
      maxPages,
      emitted,
    });
  }

  /**
   * 一次性取回满足条件的订单列表(iterate 的便捷包装)。
   * @param {Object} options - 同 iterate
   * @returns {Promise<Array<Object>>} 订单数组
   */
  async queryAll(options) {
    const orders = [];
    for await (const order of this.iterate(options)) {
      orders.push(order);
    }
    return orders;
  }

  /**
   * 把驼峰入参映射为抖音的下划线 query 参数。
   *
   * 两条文档硬约束在这里兜住:
   *   - 时间区间必须成对传入,只传一侧会被判参数不合法,故单侧传入时直接忽略并告警
   *   - cursor 为数组时需拼成逗号分隔字符串(文档示例 ["0","1"] → "0,1")
   *
   * @param {Object} options - queryPage 的入参
   * @returns {Object} query 参数对象
   */
  _buildParams(options) {
    const {
      accountId,
      pageNum = 1,
      pageSize,
      orderStatus,
      orderId,
      extOrderId,
      openId,
      cursor,
    } = options;

    if (typeof accountId !== 'string' || !accountId.trim()) {
      throw new Error('[订单查询] accountId 必须为非空字符串,避免长 ID 精度丢失');
    }
    if (!Number.isInteger(Number(pageNum)) || Number(pageNum) < 1) throw new Error('[订单查询] pageNum 必须为正整数');

    const params = {
      account_id: accountId,
      page_num: Number(pageNum),
      page_size: this._normalizePageSize(pageSize),
    };

    if (orderId) params.order_id = orderId;
    if (extOrderId) params.ext_order_id = extOrderId;
    if (openId) params.open_id = openId;
    if (typeof orderStatus === 'number') params.order_status = orderStatus;

    this._applyTimeRange(
      params,
      'create_order',
      options.createTimeStart,
      options.createTimeEnd
    );
    this._applyTimeRange(
      params,
      'update_order',
      options.updateTimeStart,
      options.updateTimeEnd
    );

    if (cursor) {
      params.cursor = Array.isArray(cursor) ? cursor.join(',') : String(cursor);
    }
    if (!params.cursor && params.page_num * params.page_size > PAGE_DEPTH_LIMIT) {
      throw new Error('[订单查询] page_num × page_size 超过 10000,请使用 cursor');
    }

    return params;
  }

  /**
   * 写入一组时间区间参数,成对校验。
   * @param {Object} params - 待写入的 query 参数对象
   * @param {string} prefix - 参数前缀(create_order / update_order)
   * @param {number} [start] - 起始秒级时间戳
   * @param {number} [end] - 结束秒级时间戳
   */
  _applyTimeRange(params, prefix, start, end) {
    if (start == null && end == null) return;

    if (start == null || end == null || !Number.isInteger(start) || !Number.isInteger(end)
      || start < 0 || end < start || end > 9999999999) {
      throw new Error(`[订单查询] ${prefix} 时间区间须为成对、递增的秒级时间戳`);
    }

    params[`${prefix}_start_time`] = Math.floor(start);
    params[`${prefix}_end_time`] = Math.floor(end);
  }

  /** 把 page_size 夹到文档允许的 1~100 区间 */
  _normalizePageSize(pageSize) {
    const size = Number(pageSize) || PAGE_SIZE_DEFAULT;
    return Math.min(PAGE_SIZE_MAX, Math.max(1, Math.floor(size)));
  }

  /**
   * 把抖音响应整理成统一形状,屏蔽 page / cursor 两套翻页元数据的差异。
   *
   * hasMore 的判定按可靠性排序:
   *   1. page.total 可信时用 已取条数 vs total 判断(page 翻页的常规路径)
   *   2. 否则看是否拿到新游标(cursor 翻页路径,样本响应里只有 search_after 没有 total)
   *   3. 都没有时退化为"本页是否装满",装满则认为后面可能还有
   *
   * @param {Object} data - 响应体的 data 字段
   * @param {Object} params - 本次请求的 query 参数,用于回推页码
   * @returns {Object} 归一化结果
   */
  _normalize(data, params) {
    if (!Array.isArray(data.orders)) throw new Error('[订单查询] 响应缺少 orders 数组');
    const orders = data.orders;
    const page = data.page || {};
    const pageNum = Number(page.page_num) || params.page_num;
    const pageSize = Number(page.page_size) || params.page_size;
    const total = Number(page.total) || 0;

    const nextCursor = this._extractCursor(data.search_after);

    let hasMore;
    if (params.cursor !== undefined) {
      hasMore = orders.length >= pageSize && Boolean(nextCursor);
    } else if (page.total !== undefined && Number.isFinite(Number(page.total))) {
      hasMore = pageNum * pageSize < total;
    } else if (nextCursor) {
      hasMore = orders.length > 0;
    } else {
      hasMore = orders.length >= pageSize;
    }

    return {
      orders,
      page: { pageNum, pageSize, total },
      nextCursor,
      hasMore,
      raw: data,
    };
  }

  /**
   * 从 search_after 中提取下一页游标。
   * 抖音返回 CursorValue 为数组,下一次请求需拼成逗号分隔字符串;
   * 字段名大小写在不同版本响应里出现过差异,故两种写法都兜。
   *
   * @param {Object} [searchAfter] - data.search_after
   * @returns {string|null} 下一页游标,无则 null
   */
  _extractCursor(searchAfter) {
    if (!searchAfter) return null;

    const cursorValue = searchAfter.CursorValue || searchAfter.cursor_value;
    if (!cursorValue) return null;

    const values = Array.isArray(cursorValue) ? cursorValue : [cursorValue];
    const joined = values.filter((v) => v !== null && v !== undefined).join(',');

    // 首页游标本身不代表"还有下一页",过滤掉避免原地打转
    return joined && joined !== CURSOR_FIRST_PAGE ? joined : null;
  }
}

module.exports = OrderQueryAPI;
module.exports.ORDER_STATUS = ORDER_STATUS;
module.exports.ORDER_QUERY_PATH = ORDER_QUERY_PATH;
module.exports.CURSOR_FIRST_PAGE = CURSOR_FIRST_PAGE;
