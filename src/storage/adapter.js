/**
 * 数据存储适配器 - 抽象层
 * 支持 MySQL、JSON 文件、TXT 文件三种存储方式
 */

const mysql = require('mysql2/promise');
const fs = require('fs').promises;
const path = require('path');
const logger = require('../utils/logger');

/**
 * 存储适配器基类
 */
class StorageAdapter {
  async init() { throw new Error('未实现 init 方法'); }
  async saveMessage(data) { throw new Error('未实现 saveMessage 方法'); }
  async getMessages(filters) { throw new Error('未实现 getMessages 方法'); }
  async saveShop(data) { throw new Error('未实现 saveShop 方法'); }
  async getShops() { throw new Error('未实现 getShops 方法'); }
  async updateShop(shopId, data) { throw new Error('未实现 updateShop 方法'); }
  async getStatistics() { throw new Error('未实现 getStatistics 方法'); }
  async close() { throw new Error('未实现 close 方法'); }
}

/**
 * MySQL 存储适配器
 */
class MySQLAdapter extends StorageAdapter {
  constructor(config) {
    super();
    this.config = config;
    this.pool = null;
  }

  async init() {
    this.pool = mysql.createPool({
      host: this.config.host,
      port: this.config.port,
      user: this.config.user,
      password: this.config.password,
      database: this.config.database,
      waitForConnections: true,
      connectionLimit: 10,
      queueLimit: 0,
    });

    // 测试连接
    const conn = await this.pool.getConnection();
    await conn.ping();
    conn.release();

    logger.info('[存储] MySQL 适配器初始化成功');

    // 创建表结构
    await this.createTables();
  }

  async createTables() {
    const createShopsTable = `
      CREATE TABLE IF NOT EXISTS shops (
        id INT AUTO_INCREMENT PRIMARY KEY,
        shop_id VARCHAR(100) UNIQUE NOT NULL,
        shop_name VARCHAR(200),
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at DATETIME,
        wework_chat_id VARCHAR(100),
        wework_chat_name VARCHAR(200),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_shop_id (shop_id),
        INDEX idx_updated_at (updated_at)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    `;

    const createMessagesTable = `
      CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        shop_id VARCHAR(100) NOT NULL,
        message_type VARCHAR(50),
        customer_id VARCHAR(100),
        customer_nickname VARCHAR(200),
        customer_phone VARCHAR(20),
        message_content TEXT,
        order_id VARCHAR(100),
        order_amount DECIMAL(10,2),
        pushed_to_wework BOOLEAN DEFAULT FALSE,
        push_success BOOLEAN DEFAULT FALSE,
        error_message TEXT,
        raw_data JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_shop_id (shop_id),
        INDEX idx_created_at (created_at),
        INDEX idx_customer_id (customer_id),
        INDEX idx_order_id (order_id)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    `;

    await this.pool.query(createShopsTable);
    await this.pool.query(createMessagesTable);

    logger.info('[存储] MySQL 表结构创建完成');
  }

  async saveMessage(data) {
    const query = `
      INSERT INTO messages (
        shop_id, message_type, customer_id, customer_nickname, customer_phone,
        message_content, order_id, order_amount, pushed_to_wework, push_success,
        error_message, raw_data
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `;

    const values = [
      data.shopId,
      data.messageType,
      data.customerId,
      data.customerNickname,
      data.customerPhone,
      data.messageContent,
      data.orderId,
      data.orderAmount,
      data.pushedToWework || false,
      data.pushSuccess || false,
      data.errorMessage,
      JSON.stringify(data.rawData)
    ];

    const [result] = await this.pool.query(query, values);
    return result.insertId;
  }

  async getMessages(filters = {}) {
    let query = `
      SELECT m.*, s.shop_name
      FROM messages m
      LEFT JOIN shops s ON m.shop_id = s.shop_id
      WHERE 1=1
    `;
    const values = [];

    if (filters.shopId) {
      query += ' AND m.shop_id = ?';
      values.push(filters.shopId);
    }

    if (filters.startDate) {
      query += ' AND m.created_at >= ?';
      values.push(filters.startDate);
    }

    if (filters.endDate) {
      query += ' AND m.created_at <= ?';
      values.push(filters.endDate);
    }

    query += ' ORDER BY m.created_at DESC';

    if (filters.limit) {
      query += ' LIMIT ?';
      values.push(parseInt(filters.limit));
    }

    if (filters.offset) {
      query += ' OFFSET ?';
      values.push(parseInt(filters.offset));
    }

    const [rows] = await this.pool.query(query, values);
    return rows;
  }

  async saveShop(data) {
    const query = `
      INSERT INTO shops (shop_id, shop_name, access_token, refresh_token, token_expires_at)
      VALUES (?, ?, ?, ?, ?)
      ON DUPLICATE KEY UPDATE
        shop_name = VALUES(shop_name),
        access_token = VALUES(access_token),
        refresh_token = VALUES(refresh_token),
        token_expires_at = VALUES(token_expires_at),
        updated_at = CURRENT_TIMESTAMP
    `;

    const values = [
      data.shopId,
      data.shopName,
      data.accessToken,
      data.refreshToken,
      data.tokenExpiresAt
    ];

    await this.pool.query(query, values);
  }

  async getShops() {
    const [rows] = await this.pool.query('SELECT * FROM shops ORDER BY updated_at DESC');
    return rows;
  }

  async updateShop(shopId, data) {
    const updates = [];
    const values = [];

    if (data.weworkChatId !== undefined) {
      updates.push('wework_chat_id = ?');
      values.push(data.weworkChatId);
    }

    if (data.weworkChatName !== undefined) {
      updates.push('wework_chat_name = ?');
      values.push(data.weworkChatName);
    }

    if (updates.length === 0) return;

    values.push(shopId);
    const query = `UPDATE shops SET ${updates.join(', ')} WHERE shop_id = ?`;

    await this.pool.query(query, values);
  }

  async getStatistics() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const queries = {
      totalShops: 'SELECT COUNT(*) as count FROM shops',
      todayMessages: 'SELECT COUNT(*) as count FROM messages WHERE created_at >= ?',
      totalMessages: 'SELECT COUNT(*) as count FROM messages',
      successCount: 'SELECT COUNT(*) as count FROM messages WHERE push_success = TRUE',
      totalCustomers: 'SELECT COUNT(DISTINCT customer_id) as count FROM messages'
    };

    const [totalShops] = await this.pool.query(queries.totalShops);
    const [todayMessages] = await this.pool.query(queries.todayMessages, [today]);
    const [totalMessages] = await this.pool.query(queries.totalMessages);
    const [successCount] = await this.pool.query(queries.successCount);
    const [totalCustomers] = await this.pool.query(queries.totalCustomers);

    const total = totalMessages[0].count;
    const success = successCount[0].count;

    return {
      total_shops: totalShops[0].count,
      today_messages: todayMessages[0].count,
      total_messages: total,
      success_rate: total > 0 ? Math.round((success / total) * 100) : 0,
      total_customers: totalCustomers[0].count
    };
  }

  async close() {
    if (this.pool) {
      await this.pool.end();
      logger.info('[存储] MySQL 连接已关闭');
    }
  }
}

/**
 * JSON 文件存储适配器
 */
class JSONAdapter extends StorageAdapter {
  constructor(config) {
    super();
    this.dataDir = config.dataDir || path.join(__dirname, '../../data');
    this.shopsFile = path.join(this.dataDir, 'shops.json');
    this.messagesFile = path.join(this.dataDir, 'messages.json');
  }

  async init() {
    // 确保数据目录存在
    await fs.mkdir(this.dataDir, { recursive: true });

    // 初始化文件
    await this.ensureFile(this.shopsFile, []);
    await this.ensureFile(this.messagesFile, []);

    logger.info('[存储] JSON 适配器初始化成功');
  }

  async ensureFile(filePath, defaultData) {
    try {
      await fs.access(filePath);
    } catch {
      await fs.writeFile(filePath, JSON.stringify(defaultData, null, 2));
    }
  }

  async readJSON(filePath) {
    const data = await fs.readFile(filePath, 'utf8');
    return JSON.parse(data);
  }

  async writeJSON(filePath, data) {
    await fs.writeFile(filePath, JSON.stringify(data, null, 2));
  }

  async saveMessage(data) {
    const messages = await this.readJSON(this.messagesFile);

    const message = {
      id: Date.now() + Math.random().toString(36).substr(2, 9),
      shop_id: data.shopId,
      message_type: data.messageType,
      customer_id: data.customerId,
      customer_nickname: data.customerNickname,
      customer_phone: data.customerPhone,
      message_content: data.messageContent,
      order_id: data.orderId,
      order_amount: data.orderAmount,
      pushed_to_wework: data.pushedToWework || false,
      push_success: data.pushSuccess || false,
      error_message: data.errorMessage,
      raw_data: data.rawData,
      created_at: new Date().toISOString()
    };

    messages.push(message);

    // 保留最近 10000 条记录
    if (messages.length > 10000) {
      messages.splice(0, messages.length - 10000);
    }

    await this.writeJSON(this.messagesFile, messages);
    return message.id;
  }

  async getMessages(filters = {}) {
    const messages = await this.readJSON(this.messagesFile);
    const shops = await this.readJSON(this.shopsFile);

    // 创建店铺映射
    const shopMap = {};
    shops.forEach(shop => {
      shopMap[shop.shop_id] = shop.shop_name;
    });

    let filtered = messages.map(msg => ({
      ...msg,
      shop_name: shopMap[msg.shop_id] || '未知店铺'
    }));

    // 应用过滤器
    if (filters.shopId) {
      filtered = filtered.filter(m => m.shop_id === filters.shopId);
    }

    if (filters.startDate) {
      const start = new Date(filters.startDate);
      filtered = filtered.filter(m => new Date(m.created_at) >= start);
    }

    if (filters.endDate) {
      const end = new Date(filters.endDate);
      filtered = filtered.filter(m => new Date(m.created_at) <= end);
    }

    // 排序
    filtered.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    // 分页
    const offset = filters.offset || 0;
    const limit = filters.limit || filtered.length;

    return filtered.slice(offset, offset + limit);
  }

  async saveShop(data) {
    const shops = await this.readJSON(this.shopsFile);

    const index = shops.findIndex(s => s.shop_id === data.shopId);

    const shop = {
      shop_id: data.shopId,
      shop_name: data.shopName,
      access_token: data.accessToken,
      refresh_token: data.refreshToken,
      token_expires_at: data.tokenExpiresAt,
      wework_chat_id: data.weworkChatId || null,
      wework_chat_name: data.weworkChatName || null,
      updated_at: new Date().toISOString()
    };

    if (index >= 0) {
      shops[index] = { ...shops[index], ...shop };
    } else {
      shop.created_at = new Date().toISOString();
      shops.push(shop);
    }

    await this.writeJSON(this.shopsFile, shops);
  }

  async getShops() {
    return await this.readJSON(this.shopsFile);
  }

  async updateShop(shopId, data) {
    const shops = await this.readJSON(this.shopsFile);
    const index = shops.findIndex(s => s.shop_id === shopId);

    if (index >= 0) {
      if (data.weworkChatId !== undefined) {
        shops[index].wework_chat_id = data.weworkChatId;
      }
      if (data.weworkChatName !== undefined) {
        shops[index].wework_chat_name = data.weworkChatName;
      }
      shops[index].updated_at = new Date().toISOString();

      await this.writeJSON(this.shopsFile, shops);
    }
  }

  async getStatistics() {
    const shops = await this.readJSON(this.shopsFile);
    const messages = await this.readJSON(this.messagesFile);

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    const todayMessages = messages.filter(m => new Date(m.created_at) >= today);
    const successMessages = messages.filter(m => m.push_success);
    const uniqueCustomers = new Set(messages.map(m => m.customer_id));

    return {
      total_shops: shops.length,
      today_messages: todayMessages.length,
      total_messages: messages.length,
      success_rate: messages.length > 0 ? Math.round((successMessages.length / messages.length) * 100) : 0,
      total_customers: uniqueCustomers.size
    };
  }

  async close() {
    logger.info('[存储] JSON 适配器已关闭');
  }
}

/**
 * TXT 文件存储适配器 (日志式存储)
 */
class TXTAdapter extends StorageAdapter {
  constructor(config) {
    super();
    this.dataDir = config.dataDir || path.join(__dirname, '../../data/logs');
    this.shopsFile = path.join(this.dataDir, 'shops.txt');
    this.messagesFile = path.join(this.dataDir, 'messages.txt');
  }

  async init() {
    await fs.mkdir(this.dataDir, { recursive: true });

    // 确保文件存在
    await this.ensureFile(this.shopsFile);
    await this.ensureFile(this.messagesFile);

    logger.info('[存储] TXT 适配器初始化成功');
  }

  async ensureFile(filePath) {
    try {
      await fs.access(filePath);
    } catch {
      await fs.writeFile(filePath, '');
    }
  }

  async saveMessage(data) {
    const line = [
      new Date().toISOString(),
      data.shopId,
      data.messageType,
      data.customerId || '',
      data.customerNickname || '',
      data.customerPhone || '',
      data.messageContent || '',
      data.orderId || '',
      data.orderAmount || '',
      data.pushSuccess ? 'SUCCESS' : 'FAILED',
      data.errorMessage || ''
    ].join('\t') + '\n';

    await fs.appendFile(this.messagesFile, line);
  }

  async getMessages(filters = {}) {
    const content = await fs.readFile(this.messagesFile, 'utf8');
    const lines = content.trim().split('\n').filter(l => l);

    const messages = lines.map(line => {
      const parts = line.split('\t');
      return {
        created_at: parts[0],
        shop_id: parts[1],
        message_type: parts[2],
        customer_id: parts[3],
        customer_nickname: parts[4],
        customer_phone: parts[5],
        message_content: parts[6],
        order_id: parts[7],
        order_amount: parts[8],
        push_success: parts[9] === 'SUCCESS',
        error_message: parts[10]
      };
    });

    // 应用过滤器
    let filtered = messages;

    if (filters.shopId) {
      filtered = filtered.filter(m => m.shop_id === filters.shopId);
    }

    // 倒序排列(最新的在前)
    filtered.reverse();

    // 分页
    const offset = filters.offset || 0;
    const limit = filters.limit || 100;

    return filtered.slice(offset, offset + limit);
  }

  async saveShop(data) {
    const line = [
      new Date().toISOString(),
      'SAVE_SHOP',
      data.shopId,
      data.shopName,
      data.tokenExpiresAt || ''
    ].join('\t') + '\n';

    await fs.appendFile(this.shopsFile, line);
  }

  async getShops() {
    // TXT 模式下简化实现
    return [];
  }

  async updateShop(shopId, data) {
    const line = [
      new Date().toISOString(),
      'UPDATE_SHOP',
      shopId,
      data.weworkChatId || '',
      data.weworkChatName || ''
    ].join('\t') + '\n';

    await fs.appendFile(this.shopsFile, line);
  }

  async getStatistics() {
    // TXT 模式下简化实现
    return {
      total_shops: 0,
      today_messages: 0,
      total_messages: 0,
      success_rate: 0,
      total_customers: 0
    };
  }

  async close() {
    logger.info('[存储] TXT 适配器已关闭');
  }
}

/**
 * 存储管理器工厂
 */
class StorageManager {
  static create(type, config) {
    switch (type.toLowerCase()) {
      case 'mysql':
        return new MySQLAdapter(config);
      case 'json':
        return new JSONAdapter(config);
      case 'txt':
        return new TXTAdapter(config);
      default:
        throw new Error(`不支持的存储类型: ${type}`);
    }
  }
}

module.exports = {
  StorageAdapter,
  MySQLAdapter,
  JSONAdapter,
  TXTAdapter,
  StorageManager
};
