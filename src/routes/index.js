/**
 * 主路由模块
 * 处理所有 HTTP 请求路由
 */

const express = require('express');
const router = express.Router();
const douyinAPI = require('../services/douyin');
const weworkAPI = require('../services/wework');
const database = require('../database');
const logger = require('../utils/logger');

/**
 * 健康检查接口
 */
router.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    service: 'beauty-notification-service',
  });
});

/**
 * 抖音 SPI 回调接口 - GET 验证
 * 配置路径: 开发配置 → SPI回调
 * 文档: https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/preparation/spi-signature-rules
 */
router.get('/douyin/spi/callback', (req, res) => {
  const { token } = req.query;
  const config = require('../config');

  // 验证 token
  if (token !== config.douyin.spiToken) {
    logger.warn('[SPI回调] Token 不匹配', { receivedToken: token });
    return res.status(403).json({ error: 'Invalid token' });
  }

  logger.info('[SPI回调] Token 验证通过');

  // 返回成功响应
  res.json({
    code: 0,
    message: 'success',
    data: {
      verified: true,
      timestamp: new Date().toISOString()
    }
  });
});

/**
 * 抖音 SPI 回调接口 - POST
 * 配置路径: 开发配置 → SPI回调
 * 接收平台主动调用的业务事件,必须验证签名
 * 文档: https://developer.open-douyin.com/docs/resource/zh-CN/local-life/develop/preparation/spi-signature-rules
 */
router.post('/douyin/spi/callback', async (req, res) => {
  try {
    const { token } = req.query;
    const config = require('../config');
    const signatureUtil = require('../utils/douyin-signature');

    // 1. 验证自定义 token (基础安全)
    if (token !== config.douyin.spiToken) {
      logger.warn('[SPI回调] Token 不匹配');
      return res.status(403).json({ error: 'Invalid token' });
    }

    // 2. 验证 SPI 签名 (必须)
    const xLifeSign = req.headers['x-life-sign'];

    if (!xLifeSign) {
      logger.warn('[SPI回调] 缺少签名 header');
      return res.status(403).json({ error: 'Missing signature' });
    }

    const body = req.body;
    const rawBody = JSON.stringify(body);
    const isValidSignature = signatureUtil.verifyHeaderSignature(
      req.headers,
      req.query,
      rawBody
    );

    if (!isValidSignature) {
      logger.warn('[SPI回调] 签名验证失败');
      return res.status(403).json({ error: 'Invalid signature' });
    }

    logger.info('[SPI回调] 签名验证通过');

    // 3. 处理业务事件
    const event = body.event;

    logger.info('[SPI回调] 收到业务事件', {
      event: event,
      client_key: body.client_key,
    });

    // 记录原始数据用于调试
    logger.debug('[SPI回调] 完整数据', body);

    // TODO: 实现具体的 SPI 业务逻辑
    // 根据 body.event 处理不同类型的回调

    // 返回成功响应
    res.json({
      code: 0,
      message: 'success',
      data: {
        received: true,
        event: event,
        timestamp: new Date().toISOString()
      }
    });

  } catch (error) {
    logger.error('[SPI回调] 处理失败', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * 抖音 Webhooks 回调接口 - POST
 * 配置路径: 基础配置 → Webhooks配置
 * 接收事件推送通知,配置时需要响应 verify_webhook 验证
 * 文档: https://partner.open-douyin.com/docs/resource/zh-CN/local-life/connect/partner/basic-config/webhooks
 */
router.post('/douyin/webhooks/callback', async (req, res) => {
  try {
    const { token } = req.query;
    const config = require('../config');

    // 验证自定义 token
    if (token !== config.douyin.spiToken) {
      logger.warn('[Webhooks] Token 不匹配');
      return res.status(403).json({ error: 'Invalid token' });
    }

    const body = req.body;
    const event = body.event;

    // 处理 URL 验证请求
    if (event === 'verify_webhook') {
      const challenge = body.content?.challenge;

      logger.info('[Webhooks] URL验证请求', { challenge });

      // 按照文档要求,返回 challenge 值
      return res.json({ challenge });
    }

    // 处理正常的事件推送
    logger.info('[Webhooks] 收到事件推送', {
      event: event,
      client_key: body.client_key,
    });

    // 记录原始数据用于调试
    logger.debug('[Webhooks] 完整数据', body);

    // TODO: 实现具体的事件处理逻辑
    // 根据 body.event 判断事件类型
    // 例如: 订单事件、核销事件、评价事件等

    // 返回成功响应
    res.json({
      code: 0,
      message: 'success',
      data: {
        received: true,
        event: event,
        timestamp: new Date().toISOString()
      }
    });

  } catch (error) {
    logger.error('[Webhooks] 处理失败', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * 抖音 Webhook 回调接口(旧版,保留兼容)
 * 接收抖音推送的消息
 */
router.post('/douyin/webhook', async (req, res) => {
  try {
    const signature = req.headers['x-douyin-signature'];
    const body = req.body;

    // 验证签名
    if (!douyinAPI.verifySignature(body, signature)) {
      logger.warn('抖音 Webhook 签名验证失败');
      return res.status(403).json({ error: 'Invalid signature' });
    }

    logger.info('收到抖音 Webhook 推送', {
      type: body.type,
      shop_id: body.data?.shop_id,
    });

    // 处理消息
    const messageData = await douyinAPI.handleWebhook(body);

    if (messageData) {
      // 查询店铺配置
      const shop = await database.getShopById(messageData.shopId);

      if (!shop) {
        logger.warn('店铺未配置', { shopId: messageData.shopId });
        return res.json({ code: 0, message: 'shop not configured' });
      }

      if (!shop.wework_chat_id) {
        logger.warn('店铺未绑定企微群', { shopId: messageData.shopId });
        return res.json({ code: 0, message: 'wework chat not configured' });
      }

      // 推送到企微群
      try {
        const notificationText = weworkAPI.formatNotification({
          shopName: shop.shop_name,
          customerId: messageData.customerId,
          customerNickname: messageData.customerNickname,
          message: messageData.message,
          timestamp: messageData.timestamp,
        });

        await weworkAPI.sendMessageToExternalChat(
          shop.wework_chat_id,
          notificationText
        );

        // 记录日志
        await database.logMessage({
          shopId: messageData.shopId,
          messageType: messageData.type,
          customerId: messageData.customerId,
          customerNickname: messageData.customerNickname,
          messageContent: messageData.message,
          orderId: messageData.orderId,
          pushedToWework: true,
          pushSuccess: true,
          errorMessage: null,
          rawData: body,
        });

        logger.success('消息已推送到企微群', {
          shopId: messageData.shopId,
          chatId: shop.wework_chat_id,
        });

      } catch (pushError) {
        logger.error('推送到企微失败', pushError.message);

        // 记录失败日志
        await database.logMessage({
          shopId: messageData.shopId,
          messageType: messageData.type,
          customerId: messageData.customerId,
          customerNickname: messageData.customerNickname,
          messageContent: messageData.message,
          orderId: messageData.orderId,
          pushedToWework: true,
          pushSuccess: false,
          errorMessage: pushError.message,
          rawData: body,
        });
      }
    }

    res.json({ code: 0, message: 'success' });

  } catch (error) {
    logger.error('处理抖音 Webhook 失败', error.message);
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * 店铺授权回调接口
 * 处理店铺授权后的跳转
 */
router.get('/douyin/callback', async (req, res) => {
  try {
    const { code, state } = req.query;

    if (!code) {
      return res.status(400).send('缺少授权码');
    }

    logger.info('收到店铺授权回调', { code: code.substring(0, 10) + '...' });

    // 用 code 换取 access_token
    const authData = await douyinAPI.getAccessToken(code);

    // 计算 token 过期时间
    const tokenExpiresAt = new Date(Date.now() + authData.expiresIn * 1000);

    // 保存到数据库
    await database.upsertShop({
      shopId: authData.shopId,
      shopName: authData.shopName,
      accessToken: authData.accessToken,
      refreshToken: authData.refreshToken,
      tokenExpiresAt,
      weworkChatId: null,  // 待配置
      weworkChatName: null,
    });

    res.send(`
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="utf-8">
        <title>授权成功</title>
        <style>
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          }
          .card {
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
            max-width: 400px;
          }
          .success-icon {
            font-size: 60px;
            margin-bottom: 20px;
          }
          h1 {
            color: #333;
            margin-bottom: 10px;
          }
          p {
            color: #666;
            line-height: 1.6;
          }
          .shop-info {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
          }
          .next-step {
            background: #667eea;
            color: white;
            padding: 12px 30px;
            border-radius: 6px;
            text-decoration: none;
            display: inline-block;
            margin-top: 20px;
          }
        </style>
      </head>
      <body>
        <div class="card">
          <div class="success-icon">✅</div>
          <h1>授权成功!</h1>
          <div class="shop-info">
            <strong>店铺:</strong> ${authData.shopName}<br>
            <strong>店铺ID:</strong> ${authData.shopId}
          </div>
          <p>您的店铺已成功授权</p>
          <p style="font-size: 14px; color: #999;">
            下一步: 配置企微群推送
          </p>
          <a href="/admin/shops" class="next-step">前往配置</a>
        </div>
      </body>
      </html>
    `);

  } catch (error) {
    logger.error('处理授权回调失败', error.message);
    res.status(500).send(`授权失败: ${error.message}`);
  }
});

/**
 * 获取店铺列表
 */
router.get('/admin/shops', async (req, res) => {
  try {
    const shops = await database.getAllActiveShops();

    res.json({
      code: 0,
      data: shops,
      total: shops.length,
    });

  } catch (error) {
    logger.error('获取店铺列表失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

/**
 * 配置店铺的企微群
 */
router.post('/admin/shops/:shopId/wework-chat', async (req, res) => {
  try {
    const { shopId } = req.params;
    const { chatId, chatName } = req.body;

    if (!chatId) {
      return res.status(400).json({ error: '缺少 chatId' });
    }

    await database.updateShopWeworkChat(shopId, chatId, chatName);

    res.json({
      code: 0,
      message: '配置成功',
    });

  } catch (error) {
    logger.error('配置企微群失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

/**
 * 获取企微客户群列表
 */
router.get('/admin/wework/chats', async (req, res) => {
  try {
    const chats = await weworkAPI.getExternalChatList();

    res.json({
      code: 0,
      data: chats,
      total: chats.length,
    });

  } catch (error) {
    logger.error('获取企微群列表失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

/**
 * 测试推送消息到企微群
 */
router.post('/test/push', async (req, res) => {
  try {
    const { shopId, testMessage } = req.body;

    const shop = await database.getShopById(shopId);

    if (!shop) {
      return res.status(404).json({ error: '店铺不存在' });
    }

    if (!shop.wework_chat_id) {
      return res.status(400).json({ error: '店铺未配置企微群' });
    }

    const message = testMessage || weworkAPI.formatNotification({
      shopName: shop.shop_name,
      customerId: 'test_customer_001',
      customerNickname: '测试顾客',
      message: '这是一条测试消息',
      timestamp: new Date(),
    });

    await weworkAPI.sendMessageToExternalChat(shop.wework_chat_id, message);

    res.json({
      code: 0,
      message: '测试消息已发送',
    });

  } catch (error) {
    logger.error('测试推送失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

/**
 * 获取消息日志
 */
router.get('/admin/logs', async (req, res) => {
  try {
    const { shopId, limit = 50, offset = 0 } = req.query;

    const logs = await database.getMessageLogs(
      shopId,
      parseInt(limit),
      parseInt(offset)
    );

    res.json({
      code: 0,
      data: logs,
      total: logs.length,
    });

  } catch (error) {
    logger.error('获取日志失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

/**
 * 获取统计数据
 */
router.get('/admin/statistics', async (req, res) => {
  try {
    const { shopId } = req.query;

    const stats = await database.getStatistics(shopId);

    res.json({
      code: 0,
      data: stats,
    });

  } catch (error) {
    logger.error('获取统计数据失败', error.message);
    res.status(500).json({ error: error.message });
  }
});

module.exports = router;
