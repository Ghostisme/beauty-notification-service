/**
 * 数据存储模块入口
 * 根据配置选择不同的存储适配器
 */

const { StorageManager } = require('./adapter');
const config = require('../config');
const logger = require('../utils/logger');

// 存储类型: mysql | json | txt
const STORAGE_TYPE = process.env.STORAGE_TYPE || 'json';

let storageInstance = null;

/**
 * 初始化存储
 */
async function initStorage() {
  if (storageInstance) {
    return storageInstance;
  }

  try {
    logger.info(`[存储] 初始化存储类型: ${STORAGE_TYPE}`);

    // 根据类型创建适配器
    if (STORAGE_TYPE === 'mysql') {
      storageInstance = StorageManager.create('mysql', config.database);
    } else if (STORAGE_TYPE === 'json') {
      storageInstance = StorageManager.create('json', {
        dataDir: config.storage?.dataDir
      });
    } else if (STORAGE_TYPE === 'txt') {
      storageInstance = StorageManager.create('txt', {
        dataDir: config.storage?.dataDir
      });
    } else {
      throw new Error(`不支持的存储类型: ${STORAGE_TYPE}`);
    }

    await storageInstance.init();
    logger.success(`[存储] ${STORAGE_TYPE} 存储初始化成功`);

    return storageInstance;
  } catch (error) {
    logger.error('[存储] 初始化失败:', error);
    throw error;
  }
}

/**
 * 获取存储实例
 */
function getStorage() {
  if (!storageInstance) {
    throw new Error('存储未初始化,请先调用 initStorage()');
  }
  return storageInstance;
}

/**
 * 保存消息数据
 */
async function saveMessage(data) {
  const storage = getStorage();
  return await storage.saveMessage(data);
}

/**
 * 获取消息列表
 */
async function getMessages(filters = {}) {
  const storage = getStorage();
  return await storage.getMessages(filters);
}

/**
 * 保存店铺数据
 */
async function saveShop(data) {
  const storage = getStorage();
  return await storage.saveShop(data);
}

/**
 * 获取店铺列表
 */
async function getShops() {
  const storage = getStorage();
  return await storage.getShops();
}

/**
 * 根据店铺ID获取店铺
 */
async function getShopById(shopId) {
  const storage = getStorage();
  const shops = await storage.getShops();
  return shops.find(s => s.shop_id === shopId);
}

/**
 * 更新店铺信息
 */
async function updateShop(shopId, data) {
  const storage = getStorage();
  return await storage.updateShop(shopId, data);
}

/**
 * 获取统计数据
 */
async function getStatistics(shopId = null) {
  const storage = getStorage();
  return await storage.getStatistics(shopId);
}

/**
 * 关闭存储连接
 */
async function closeStorage() {
  if (storageInstance) {
    await storageInstance.close();
    storageInstance = null;
    logger.info('[存储] 已关闭');
  }
}

module.exports = {
  initStorage,
  getStorage,
  saveMessage,
  getMessages,
  saveShop,
  getShops,
  getShopById,
  updateShop,
  getStatistics,
  closeStorage
};
