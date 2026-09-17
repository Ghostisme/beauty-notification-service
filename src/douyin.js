const crypto = require('crypto');

/**
 * 抖音 Webhook 处理
 */
class DouyinWebhook {
  constructor(appSecret, logger) {
    this.appSecret = appSecret;
    this.logger = logger;
  }

  /**
   * 验证抖音签名
   * 防止伪造请求
   */
  verifySignature(body, signature, timestamp) {
    if (!signature || !timestamp) {
      this.logger.warn('缺少签名或时间戳');
      return false;
    }

    // 检查时间戳（防重放攻击，5分钟有效期）
    const now = Math.floor(Date.now() / 1000);
    const requestTime = parseInt(timestamp);

    if (Math.abs(now - requestTime) > 300) {
      this.logger.warn({
        now,
        requestTime,
        diff: now - requestTime
      }, '请求时间戳过期');
      return false;
    }

    // 计算签名
    const rawData = JSON.stringify(body);
    const signStr = `${rawData}${timestamp}${this.appSecret}`;
    const calculatedSignature = crypto
      .createHash('sha256')
      .update(signStr)
      .digest('hex');

    const isValid = calculatedSignature === signature;

    if (!isValid) {
      this.logger.warn({
        expected: calculatedSignature.substring(0, 16) + '...',
        received: signature.substring(0, 16) + '...'
      }, '签名验证失败');
    }

    return isValid;
  }

  /**
   * 解析抖音订单数据
   * 适配抖音生活服务订单格式
   */
  parseOrderData(body) {
    try {
      // 抖音可能发送不同类型的事件
      const { event_type, data } = body;

      // 订单创建事件
      if (event_type === 'order.create' || event_type === 'order.paid') {
        return this._parseOrder(data);
      }

      // 团购核销事件
      if (event_type === 'coupon.verify') {
        return this._parseCoupon(data);
      }

      // 其他事件类型
      this.logger.info({ event_type }, '收到其他类型事件');
      return null;

    } catch (error) {
      this.logger.error({
        error: error.message,
        body
      }, '解析订单数据失败');
      return null;
    }
  }

  /**
   * 解析订单数据
   */
  _parseOrder(data) {
    return {
      orderId: data.order_id || data.id,
      storeId: this._extractStoreId(data),
      customerName: data.customer_name || data.receiver_name,
      phone: data.customer_phone || data.receiver_phone,
      service: data.product_name || data.sku_name,
      amount: data.total_amount || data.pay_amount,
      appointmentTime: data.appointment_time || data.service_time,
      source: '抖音订单',
      note: data.note || data.remark,
      createdAt: data.create_time || new Date().toISOString()
    };
  }

  /**
   * 解析团购券核销数据
   */
  _parseCoupon(data) {
    return {
      orderId: data.coupon_code || data.verify_token,
      storeId: this._extractStoreId(data),
      customerName: data.customer_name,
      phone: data.customer_phone,
      service: data.product_name,
      amount: data.coupon_amount,
      source: '抖音团购',
      note: '客户已到店，团购券已核销',
      createdAt: data.verify_time || new Date().toISOString()
    };
  }

  /**
   * 从订单数据中提取门店ID
   * 根据实际的抖音数据字段调整
   */
  _extractStoreId(data) {
    // 方案1: 抖音返回的 POI ID（门店ID）
    if (data.poi_id) {
      return `store_${data.poi_id}`;
    }

    // 方案2: 门店编号
    if (data.shop_id || data.store_id) {
      return data.shop_id || data.store_id;
    }

    // 方案3: 从备注或扩展字段提取
    if (data.ext_info && data.ext_info.store_id) {
      return data.ext_info.store_id;
    }

    // 默认返回（需要在配置中映射）
    this.logger.warn({ data }, '无法提取门店ID');
    return 'unknown';
  }

  /**
   * 处理抖音的验证请求
   * 首次配置回调地址时，抖音会发送验证请求
   */
  handleVerification(query) {
    const { echostr, signature, timestamp, nonce } = query;

    if (!echostr) {
      return null;
    }

    // 验证签名（具体算法根据抖音文档）
    const items = [this.appSecret, timestamp, nonce].sort();
    const signStr = items.join('');
    const calculatedSignature = crypto
      .createHash('sha1')
      .update(signStr)
      .digest('hex');

    if (calculatedSignature === signature) {
      this.logger.info('抖音回调验证成功');
      return echostr;
    }

    this.logger.warn('抖音回调验证失败');
    return null;
  }
}

module.exports = { DouyinWebhook };
