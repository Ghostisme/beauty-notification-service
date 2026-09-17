/**
 * 抖音模块 - 入口文件
 * 负责与抖音开放平台的所有交互
 */

const DouyinAPI = require('./api');
const DouyinSPI = require('./spi');
const DouyinDecrypt = require('./decrypt');

class DouyinModule {
  constructor() {
    this.api = new DouyinAPI();
    this.spi = new DouyinSPI();
    this.decrypt = new DouyinDecrypt();
    // 注入API实例到解密模块
    this.decrypt.setAPIInstance(this.api);
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
  async decryptFields(encryptedValues, accountId) {
    return await this.decrypt.decryptBatch(encryptedValues, accountId);
  }

  /**
   * 提取用户需要的订单字段
   * @param {Object} order - 完整订单对象
   * @param {Object} decryptedData - 解密数据映射
   * @returns {Object} 格式化后的订单信息
   */
  extractOrderFields(order, decryptedData = {}) {
    const product = order.products?.[0] || {};

    // 提取客户手机号
    let customerPhone = '未获取';
    if (order.contacts?.[0]?.phone) {
      // 联系人手机号
      customerPhone = order.contacts[0].phone;
      // 如果已解密,使用解密后的
      if (decryptedData[customerPhone]) {
        customerPhone = decryptedData[customerPhone];
      }
    } else if (order.open_id) {
      // 如果没有手机号,使用open_id
      customerPhone = `用户ID: ${order.open_id}`;
    }

    // 提取价格信息(订单维度)
    const orderPrice = order.original_amount ? (order.original_amount / 100).toFixed(2) : '0.00';
    const actualPrice = order.pay_amount ? (order.pay_amount / 100).toFixed(2) : '0.00';

    // 提取店铺名称
    let shopName = '未知店铺';
    let shopId = '';
    if (order.order_sale_info?.transfer_nickName) {
      shopName = order.order_sale_info.transfer_nickName;
    }
    // 店铺ID从poi_id获取
    if (order.intention_poi_id) {
      shopId = order.intention_poi_id;
    }

    return {
      // 1. 客户手机号
      customerPhone,

      // 2. 下单时间
      orderTime: this._formatTimestamp(order.create_order_time),
      orderTimeRaw: order.create_order_time,

      // 3. 团购名称和ID
      productName: product.product_name || order.sku_name || '未知商品',
      productId: product.product_id || order.sku_id || '',

      // 4. 下单价格
      orderPrice, // 原价
      actualPrice, // 实付金额

      // 5. 店铺名称
      shopName,
      shopId,

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
