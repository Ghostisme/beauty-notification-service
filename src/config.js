const fs = require('fs');
const path = require('path');
require('dotenv').config();

/**
 * 配置管理
 * 加载环境变量和门店配置
 */
class Config {
  constructor() {
    // 服务器配置
    this.server = {
      port: process.env.PORT || 3000,
      env: process.env.NODE_ENV || 'development'
    };

    // 抖音配置
    this.douyin = {
      clientKey: process.env.DOUYIN_CLIENT_KEY,
      clientSecret: process.env.DOUYIN_CLIENT_SECRET,
      spiToken: process.env.DOUYIN_SPI_TOKEN
    };

    // 企业微信配置
    this.wework = {
      corpId: process.env.WEWORK_CORP_ID,
      agentId: process.env.WEWORK_AGENT_ID,
      secret: process.env.WEWORK_SECRET,
      senderUserId: process.env.WEWORK_SENDER_USERID
    };

    // 数据库配置
    this.database = {
      host: process.env.DB_HOST || 'localhost',
      port: process.env.DB_PORT || 3306,
      user: process.env.DB_USER,
      password: process.env.DB_PASSWORD,
      database: process.env.DB_NAME
    };

    // 门店配置
    this.groupsFile = path.join(__dirname, '../data/groups.json');
    this.groups = {};
    this.loadGroups();
  }

  /**
   * 加载门店配置
   */
  loadGroups() {
    try {
      if (!fs.existsSync(this.groupsFile)) {
        console.warn(`⚠️  配置文件不存在: ${this.groupsFile}`);
        console.warn('请创建 data/groups.json 并填入门店配置');
        return;
      }

      const data = fs.readFileSync(this.groupsFile, 'utf8');
      this.groups = JSON.parse(data);

      const count = Object.keys(this.groups).length;
      console.log(`✅ 已加载 ${count} 个门店配置`);

      // 验证配置
      this._validateConfig();

    } catch (error) {
      console.error('❌ 加载配置文件失败:', error.message);
      this.groups = {};
    }
  }

  /**
   * 重新加载配置（热更新）
   */
  reload() {
    console.log('🔄 重新加载配置...');
    this.loadGroups();
  }

  /**
   * 获取单个门店配置
   */
  getStore(storeId) {
    return this.groups[storeId];
  }

  /**
   * 获取所有门店ID
   */
  getAllStoreIds() {
    return Object.keys(this.groups);
  }

  /**
   * 获取所有门店配置
   */
  getAllStores() {
    return Object.keys(this.groups).map(id => ({
      id,
      ...this.groups[id]
    }));
  }

  /**
   * 获取门店数量
   */
  getStoreCount() {
    return Object.keys(this.groups).length;
  }

  /**
   * 按地区获取门店
   */
  getStoresByRegion(region) {
    return Object.keys(this.groups)
      .filter(id => this.groups[id].region === region)
      .map(id => ({
        id,
        ...this.groups[id]
      }));
  }

  /**
   * 验证配置格式
   */
  _validateConfig() {
    let invalidCount = 0;

    for (const [storeId, config] of Object.entries(this.groups)) {
      if (!config.name) {
        console.warn(`⚠️  门店 ${storeId} 缺少 name 字段`);
        invalidCount++;
      }

      if (!config.webhook) {
        console.warn(`⚠️  门店 ${storeId} 缺少 webhook 字段`);
        invalidCount++;
      } else if (!this._isValidWebhook(config.webhook)) {
        console.warn(`⚠️  门店 ${storeId} 的 webhook 格式不正确`);
        invalidCount++;
      }
    }

    if (invalidCount > 0) {
      console.warn(`⚠️  发现 ${invalidCount} 个配置问题`);
    }
  }

  /**
   * 验证 Webhook 格式
   */
  _isValidWebhook(webhook) {
    return webhook && webhook.startsWith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=');
  }
}

// 导出单例
module.exports = new Config();
