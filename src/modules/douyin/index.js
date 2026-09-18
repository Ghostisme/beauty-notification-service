/**
 * 抖音模块 - 入口文件
 * 负责与抖音开放平台的所有交互
 */

const DouyinAPI = require('./api');
const DouyinSPI = require('./spi');
const DouyinDecrypt = require('./decrypt');
const { isEncrypted } = require('./sensitive-fields');

class DouyinModule {
  constructor(options = {}) {
    this.api = new DouyinAPI(options);
    this.spi = new DouyinSPI();
    // 解密走 api 内部的统一请求层,与业务接口共用 token 刷新、频控退避和错误码判定
    this.decrypt = new DouyinDecrypt(this.api.http);
  }

  /**
   * 初始化模块
   */
  async init() {
    await this.api.init();
  }

  /**
   * 处理SPI回调请求
   * @param {Object} req - Express请求对象
   * @returns {Object} 处理结果 {success, data, error}
   */
  async handleSPICallback(req) {
    return await this.spi.handleCallback(req);
  }

  /**
   * 获取订单详情
   * @param {string} orderId - 订单ID
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 订单详情
   */
  async getOrderDetail(orderId, accountId) {
    return await this.api.getOrderDetail(orderId, accountId);
  }

  /**
   * 解密加密字段
   * @param {Array<string>} encryptedValues - 加密值数组
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object>} 解密结果映射
   */
  async decryptFields(encryptedValues, accountId, options = {}) {
    return await this.decrypt.decryptBatch(encryptedValues, accountId, options);
  }

  /**
   * 提取用户需要的订单字段
   * @param {Object} order - 完整订单对象
   * @param {Object} [decryptedData] - 解密映射 {密文: 明文};订单已被 applyDecryptedValues
   *   原地回填时可省略,仅为兼容"自行解密后直接传表"的旧调用方保留
   * @returns {Object} 格式化后的订单信息
   */
  extractOrderFields(order, decryptedData = {}) {
    const product = order.products?.[0] || {};

    return {
      // 1. 客户手机号
      customerPhone: this._resolveCustomerPhone(order, decryptedData),
      customerPhoneStatus: this._phoneStatus(this._resolveCustomerPhone(order, decryptedData)),

      // 2. 下单时间
      orderTime: this._formatTimestamp(order.create_order_time),
      orderTimeRaw: order.create_order_time,

      // 3. 团购名称和ID
      productName: product.product_name || order.sku_name || '未知商品',
      productId: product.product_id || order.sku_id || '',

      // 4. 下单价格
      orderPrice: this._formatAmount(order.original_amount ?? order.amount_info?.origin_amount), // 原价
      actualPrice: this._formatAmount(order.pay_amount ?? order.amount_info?.pay_amount), // 实付金额

      // 5. 店铺名称
      shopName: order.merchant_info?.account_name || order.order_sale_info?.transfer_nickName || '未知店铺',
      shopId: order.intention_poi_id || order.merchant_info?.account_id || '',

      // 其他有用字段
      orderId: order.order_id,
      orderStatus: this._getOrderStatusText(order.order_status),
      orderStatusCode: order.order_status, // 原始状态码
      orderType: this._getOrderTypeText(order.order_type), // 订单类型
      orderTypeCode: order.order_type, // 原始订单类型码
      quantity: product.num || order.count || 1,
      openId: order.open_id,

      // 销售信息
      orderSource: this._getOrderSourceText(order.order_sale_info?.order_source),
      saleChannel: order.order_sale_info?.sale_channel || '',
      saleRole: order.order_sale_info?.sale_role || '',
    };
  }

  /**
   * 解析客户手机号,按可用性逐级降级。
   *
   * 正常链路里 order-processor 已用 applyDecryptedValues 把明文原地回填,
   * 此处第一候选直接就是明文;查表仅兜住两种情况:调用方自带解密表,
   * 或某字段解密失败仍是密文(此时降级到 open_id,避免把 `Enc.xxx` 推给客服)。
   *
   * @private
   * @param {Object} order - 订单对象
   * @param {Object} decryptedData - 解密映射
   * @returns {string} 手机号明文,或降级后的替代标识
   */
  _resolveCustomerPhone(order, decryptedData) {
    const candidates = [
      order.contacts?.[0]?.phone,
      order.contacts?.[0]?.phone_encrypt,
      order.buyer_info?.buyer_real_phone,
      order.buyer_info?.buyer_phone,
    ];

    let masked = null;
    for (const raw of candidates) {
      if (!raw) continue;

      const plain = decryptedData[raw] || raw;
      // 仍是密文说明该字段没解出来,继续看下一个候选
      if (typeof plain !== 'string' || isEncrypted(plain)) continue;
      if (this._phoneStatus(plain) === 'available') return plain;
      if (this._phoneStatus(plain) === 'masked') masked ||= plain;
    }

    return masked || (order.open_id ? `用户ID: ${order.open_id}` : '未获取');
  }

  _phoneStatus(value) {
    if (typeof value !== 'string') return 'unavailable';
    if (/^[+\d][\d ()-]{5,20}$/.test(value)) return 'available';
    if (/^[\d+][\d* -]+$/.test(value) && value.includes('*')) return 'masked';
    return 'unavailable';
  }

  /**
   * 分转元并保留两位小数。
   * @private
   * @param {number|undefined} amountInCents - 以分为单位的金额
   * @returns {string}
   */
  _formatAmount(amountInCents) {
    return amountInCents ? (amountInCents / 100).toFixed(2) : '0.00';
  }

  /**
   * 格式化时间戳
   * @private
   */
  _formatTimestamp(timestamp) {
    if (!timestamp) return '未知时间';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  }

  /**
   * 获取订单状态文本
   * @private
   */
  _getOrderStatusText(status) {
    const statusMap = {
      0: '初始化',
      100: '待支付',
      101: '支付取消',
      200: '已支付',
      201: '待使用',
      1: '已完成',
      150: '部分支付',
    };
    return statusMap[status] || `未知状态(${status})`;
  }

  /**
   * 获取订单来源文本
   * @private
   */
  _getOrderSourceText(source) {
    const sourceMap = {
      1: '抖音',
      2: '头条',
      3: '西瓜',
    };
    return sourceMap[source] || `未知来源(${source})`;
  }

  /**
   * 获取订单类型文本
   * @private
   */
  _getOrderTypeText(type) {
    const typeMap = {
      1: '团购订单',
      2: '预约订单',
      3: '买单订单',
      11: '酒旅订单',
      12: '门票订单',
      21: '验券订单',
      30: '套餐订单',
      31: '充值订单',
      32: '次卡订单',
      33: '卡项订单',
    };
    return typeMap[type] || `其他订单(${type})`;
  }
}

module.exports = DouyinModule;
