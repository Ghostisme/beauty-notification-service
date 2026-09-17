const fs = require('fs');
const path = require('path');

/**
 * 配置管理
 * 加载并管理门店配置
 */
class Config {
  constructor() {
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
