/**
 * 数据库操作模块
 * 管理商户配置和消息日志
 */

const mysql = require('mysql2/promise');
const config = require('../config');
const logger = require('../utils/logger');

class Database {
  constructor() {
    this.pool = null;
  }

  /**
   * 初始化数据库连接池
   */
  async init() {
    try {
      this.pool = mysql.createPool({
        host: config.database.host,
        port: config.database.port,
        user: config.database.user,
        password: config.database.password,
        database: config.database.database,
        waitForConnections: true,
        connectionLimit: 10,
        queueLimit: 0,
      });

      // 测试连接
      const conn = await this.pool.getConnection();
      await conn.ping();
      conn.release();

      logger.info('[数据库] 连接池初始化成功');
      await this.createTables();
    } catch (error) {
      logger.error('[数据库] 初始化失败:', error);
      throw error;
    }
  }

  /**
   * 创建数据库表
   */
  async createTables() {
    const createShopsTable = `
      CREATE TABLE IF NOT EXISTS shops (
        id INT AUTO_INCREMENT PRIMARY KEY,
        account_id VARCHAR(100) NOT NULL UNIQUE COMMENT '抖音商户账户ID',
        account_name VARCHAR(200) COMMENT '商户名称',
        wework_chat_id VARCHAR(100) COMMENT '企业微信群ID',
        wework_chat_name VARCHAR(200) COMMENT '企业微信群名称',
        status ENUM('active', 'inactive') DEFAULT 'active' COMMENT '状态',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_account_id (account_id),
        INDEX idx_status (status)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺配置表';
    `;

    const createMessageLogsTable = `
      CREATE TABLE IF NOT EXISTS message_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id VARCHAR(100) NOT NULL COMMENT '抖音订单ID',
        account_id VARCHAR(100) NOT NULL COMMENT '商户账户ID',
        wework_chat_id VARCHAR(100) COMMENT '企业微信群ID',
        customer_phone VARCHAR(50) COMMENT '客户手机号',
        product_name VARCHAR(500) COMMENT '商品名称',
        order_price DECIMAL(10,2) COMMENT '订单价格',
        message_content TEXT COMMENT '消息内容',
        send_status ENUM('pending', 'success', 'failed') DEFAULT 'pending' COMMENT '发送状态',
        send_time DATETIME COMMENT '发送时间',
        error_message TEXT COMMENT '错误信息',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_order_id (order_id),
        INDEX idx_account_id (account_id),
        INDEX idx_send_status (send_status),
        INDEX idx_created_at (created_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息日志表';
    `;

    try {
      await this.pool.execute(createShopsTable);
      await this.pool.execute(createMessageLogsTable);
      logger.info('[数据库] 数据表检查/创建完成');
    } catch (error) {
      logger.error('[数据库] 创建表失败:', error);
      throw error;
    }
  }

  /**
   * 根据商户ID获取企业微信群配置
   * @param {string} accountId - 商户账户ID
   * @returns {Promise<Object|null>} 店铺配置
   */
  async getShopConfig(accountId) {
    try {
      const [rows] = await this.pool.execute(
        'SELECT * FROM shops WHERE account_id = ? AND status = ?',
        [accountId, 'active']
      );
      return rows[0] || null;
    } catch (error) {
      logger.error(`[数据库] 查询店铺配置失败: ${accountId}`, error);
      return null;
    }
  }

  /**
   * 保存或更新店铺配置
   * @param {Object} shopData - 店铺数据
   */
  async saveShopConfig(shopData) {
    const { account_id, account_name, wework_chat_id, wework_chat_name } = shopData;

    try {
      await this.pool.execute(
        `INSERT INTO shops (account_id, account_name, wework_chat_id, wework_chat_name)
         VALUES (?, ?, ?, ?)
         ON DUPLICATE KEY UPDATE
         account_name = VALUES(account_name),
         wework_chat_id = VALUES(wework_chat_id),
         wework_chat_name = VALUES(wework_chat_name),
         updated_at = CURRENT_TIMESTAMP`,
        [account_id, account_name, wework_chat_id, wework_chat_name]
      );
      logger.info(`[数据库] 店铺配置保存成功: ${account_id}`);
    } catch (error) {
      logger.error(`[数据库] 保存店铺配置失败: ${account_id}`, error);
      throw error;
    }
  }

  /**
   * 记录消息日志
   * @param {Object} logData - 日志数据
   */
  async saveMessageLog(logData) {
    const {
      order_id,
      account_id,
      wework_chat_id,
      customer_phone,
      product_name,
      order_price,
      message_content,
      send_status,
      error_message,
    } = logData;

    try {
      await this.pool.execute(
        `INSERT INTO message_logs
         (order_id, account_id, wework_chat_id, customer_phone, product_name,
          order_price, message_content, send_status, send_time, error_message)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), ?)`,
        [
          order_id,
          account_id,
          wework_chat_id,
          customer_phone,
          product_name,
          order_price,
          message_content,
          send_status,
          error_message,
        ]
      );
    } catch (error) {
      logger.error(`[数据库] 保存消息日志失败: ${order_id}`, error);
    }
  }

  /**
   * 检查订单是否已处理(防重)
   * @param {string} orderId - 订单ID
   * @returns {Promise<boolean>} 是否已处理
   */
  async isOrderProcessed(orderId) {
    try {
      const [rows] = await this.pool.execute(
        'SELECT id FROM message_logs WHERE order_id = ? AND send_status = ?',
        [orderId, 'success']
      );
      return rows.length > 0;
    } catch (error) {
      logger.error(`[数据库] 检查订单状态失败: ${orderId}`, error);
      return false;
    }
  }

  /**
   * 获取所有活跃店铺列表
   * @returns {Promise<Array>} 店铺列表
   */
  async getAllActiveShops() {
    try {
      const [rows] = await this.pool.execute(
        'SELECT * FROM shops WHERE status = ? ORDER BY created_at DESC',
        ['active']
      );
      return rows;
    } catch (error) {
      logger.error('[数据库] 获取店铺列表失败', error);
      return [];
    }
  }

  /**
   * 关闭数据库连接
   */
  async close() {
    if (this.pool) {
      await this.pool.end();
      logger.info('[数据库] 连接池已关闭');
    }
  }
}

module.exports = new Database();
