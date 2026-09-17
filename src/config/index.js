/**
 * 配置管理模块
 * 统一管理所有环境变量和配置项
 */

require('dotenv').config();

module.exports = {
  // 抖音生活服务配置
  douyin: {
    clientKey: process.env.DOUYIN_CLIENT_KEY,
    clientSecret: process.env.DOUYIN_CLIENT_SECRET,
    spiToken: process.env.DOUYIN_SPI_TOKEN,
  },

  // 企业微信配置
  wework: {
    corpId: process.env.WEWORK_CORP_ID,
    agentId: process.env.WEWORK_AGENT_ID,
    secret: process.env.WEWORK_SECRET,
    senderUserId: process.env.WEWORK_SENDER_USERID,
  },

  // 数据库配置
  database: {
    host: process.env.DB_HOST || 'localhost',
    port: process.env.DB_PORT || 3306,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
  },

  // 存储配置
  storage: {
    type: process.env.STORAGE_TYPE || 'json', // mysql | json | txt
    dataDir: process.env.STORAGE_DATA_DIR || './data',
  },

  // 服务器配置
  server: {
    port: process.env.PORT || 3000,
    env: process.env.NODE_ENV || 'development',
    sslKeyPath: process.env.SSL_KEY_PATH,
    sslCertPath: process.env.SSL_CERT_PATH,
  },
};
