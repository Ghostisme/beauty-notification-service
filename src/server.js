/**
 * 主服务器入口文件
 * 启动 Express 服务器,初始化所有模块
 */

const express = require('express');
const bodyParser = require('body-parser');
const path = require('path');
const config = require('./config');
const logger = require('./utils/logger');
const database = require('./database');
const routes = require('./routes');

class Server {
  constructor() {
    this.app = express();
    this.port = config.server.port;
  }

  /**
   * 配置中间件
   */
  setupMiddleware() {
    // 解析 JSON 请求体
    // Preserve the exact bytes: Douyin SPI signatures are calculated over the
    // original HTTP body, not over JSON.stringify(req.body).
    this.app.use(bodyParser.json({
      verify: (req, res, buffer) => {
        req.rawBody = buffer.toString('utf8');
      },
    }));
    this.app.use(bodyParser.urlencoded({ extended: true }));

    // 请求日志
    this.app.use((req, res, next) => {
      logger.info(`${req.method} ${req.path}`, {
        ip: req.ip,
        userAgent: req.get('user-agent'),
      });
      next();
    });

    // CORS 设置(如果需要)
    this.app.use((req, res, next) => {
      res.header('Access-Control-Allow-Origin', '*');
      res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
      res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
      if (req.method === 'OPTIONS') {
        return res.sendStatus(200);
      }
      next();
    });
  }

  /**
   * 配置路由
   */
  setupRoutes() {
    // 静态文件服务 - 管理后台前端页面
    const webDir = path.join(__dirname, '../web');
    this.app.use('/admin/dashboard', express.static(webDir));

    // API 路由
    this.app.use('/api', routes);

    // 管理后台 API 路由
    this.app.use('/admin', routes);

    // 管理后台入口重定向
    this.app.get('/admin', (req, res) => {
      res.redirect('/admin/dashboard/');
    });

    // 根路径
    this.app.get('/', (req, res) => {
      res.send(`
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>美容店来客通知系统</title>
          <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
              background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
              min-height: 100vh;
              display: flex;
              justify-content: center;
              align-items: center;
              padding: 20px;
            }
            .container {
              background: white;
              border-radius: 16px;
              box-shadow: 0 20px 60px rgba(0,0,0,0.3);
              max-width: 800px;
              width: 100%;
              padding: 40px;
            }
            h1 {
              color: #333;
              margin-bottom: 10px;
              font-size: 32px;
            }
            .subtitle {
              color: #666;
              margin-bottom: 30px;
              font-size: 16px;
            }
            .status {
              background: #f0f9ff;
              border-left: 4px solid #3b82f6;
              padding: 15px;
              margin-bottom: 30px;
              border-radius: 4px;
            }
            .status.success {
              background: #f0fdf4;
              border-color: #22c55e;
            }
            .section {
              margin-bottom: 30px;
            }
            .section h2 {
              color: #333;
              font-size: 20px;
              margin-bottom: 15px;
              padding-bottom: 10px;
              border-bottom: 2px solid #f0f0f0;
            }
            .api-list {
              list-style: none;
            }
            .api-item {
              display: flex;
              align-items: center;
              padding: 12px;
              margin-bottom: 8px;
              background: #f9fafb;
              border-radius: 6px;
              font-family: 'Courier New', monospace;
              font-size: 14px;
            }
            .method {
              background: #3b82f6;
              color: white;
              padding: 4px 8px;
              border-radius: 4px;
              font-weight: bold;
              margin-right: 10px;
              min-width: 60px;
              text-align: center;
            }
            .method.post { background: #22c55e; }
            .method.get { background: #3b82f6; }
            .path {
              color: #333;
              flex: 1;
            }
            .button {
              display: inline-block;
              background: #667eea;
              color: white;
              padding: 12px 24px;
              border-radius: 8px;
              text-decoration: none;
              font-weight: 500;
              margin-right: 10px;
              margin-top: 10px;
              transition: background 0.3s;
            }
            .button:hover {
              background: #5568d3;
            }
            .button.secondary {
              background: #6b7280;
            }
            .button.secondary:hover {
              background: #4b5563;
            }
            footer {
              margin-top: 40px;
              padding-top: 20px;
              border-top: 1px solid #e5e7eb;
              text-align: center;
              color: #6b7280;
              font-size: 14px;
            }
          </style>
        </head>
        <body>
          <div class="container">
            <h1>🔔 美容店来客通知系统</h1>
            <p class="subtitle">抖音店铺消息 → 企业微信客户群推送</p>

            <div class="status success">
              <strong>✅ 服务运行中</strong><br>
              时间: ${new Date().toLocaleString('zh-CN')}<br>
              环境: ${config.server.env}
            </div>

            <div class="section">
              <h2>📡 API 接口</h2>
              <ul class="api-list">
                <li class="api-item">
                  <span class="method get">GET</span>
                  <span class="path">/api/health</span>
                </li>
                <li class="api-item">
                  <span class="method post">POST</span>
                  <span class="path">/api/douyin/webhook</span>
                </li>
                <li class="api-item">
                  <span class="method get">GET</span>
                  <span class="path">/api/douyin/callback</span>
                </li>
                <li class="api-item">
                  <span class="method get">GET</span>
                  <span class="path">/admin/shops</span>
                </li>
                <li class="api-item">
                  <span class="method post">POST</span>
                  <span class="path">/admin/shops/:shopId/wework-chat</span>
                </li>
                <li class="api-item">
                  <span class="method get">GET</span>
                  <span class="path">/admin/wework/chats</span>
                </li>
                <li class="api-item">
                  <span class="method post">POST</span>
                  <span class="path">/test/push</span>
                </li>
              </ul>
            </div>

            <div class="section">
              <h2>🚀 快速开始</h2>
              <a href="/admin/dashboard/" class="button">进入管理后台</a>
              <a href="/api/health" class="button secondary">健康检查</a>
            </div>

            <footer>
              <p>Beauty Notification Service v1.0.0</p>
              <p>Powered by Node.js + Express + MySQL</p>
            </footer>
          </div>
        </body>
        </html>
      `);
    });

    // 404 处理
    this.app.use((req, res) => {
      res.status(404).json({
        error: 'Not found',
        path: req.path,
      });
    });

    // 错误处理
    this.app.use((err, req, res, next) => {
      logger.error('未捕获的错误', {
        error: err.message,
        stack: err.stack,
        path: req.path,
      });

      res.status(500).json({
        error: 'Internal server error',
        message: config.server.env === 'development' ? err.message : undefined,
      });
    });
  }

  /**
   * 启动服务器
   */
  async start() {
    try {
      // 初始化数据库
      logger.info('正在初始化数据库...');
      await database.initialize();

      // 配置中间件
      this.setupMiddleware();

      // 配置路由
      this.setupRoutes();

      // 启动 HTTP 服务器
      this.app.listen(this.port, () => {
        logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        logger.success(`🚀 服务器已启动`);
        logger.success(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
        logger.info(`📍 地址: http://localhost:${this.port}`);
        logger.info(`🌍 环境: ${config.server.env}`);
        logger.info(`⏰ 时间: ${new Date().toLocaleString('zh-CN')}`);
        logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
        logger.info('');
        logger.info('📡 Webhook 回调地址:');
        logger.info(`   抖音: POST https://你的域名/api/douyin/webhook`);
        logger.info('');
        logger.info('🔗 授权回调地址:');
        logger.info(`   GET https://你的域名/api/douyin/callback`);
        logger.info('');
        logger.info('💡 提示: 访问 http://localhost:${this.port} 查看完整文档');
        logger.success('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
      });

      // 优雅关闭
      process.on('SIGTERM', () => this.shutdown());
      process.on('SIGINT', () => this.shutdown());

    } catch (error) {
      logger.error('服务器启动失败', error.message);
      process.exit(1);
    }
  }

  /**
   * 优雅关闭
   */
  async shutdown() {
    logger.info('正在关闭服务器...');

    try {
      await database.close();
      logger.info('服务器已关闭');
      process.exit(0);
    } catch (error) {
      logger.error('关闭时出错', error.message);
      process.exit(1);
    }
  }
}

// 启动服务器
const server = new Server();
server.start();

module.exports = server;
