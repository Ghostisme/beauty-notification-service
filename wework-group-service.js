// ============================================
// 企业微信客户群消息推送服务
// 功能:接收抖音订单 → 自动推送到客户群
// ============================================

const express = require('express');
const axios = require('axios');
const fs = require('fs').promises;
const path = require('path');

const app = express();
app.use(express.json());

// ============ 配置区 ============
const CONFIG = {
  CORP_ID: process.env.WEWORK_CORP_ID || 'your_corp_id',           // 企业 ID
  AGENT_SECRET: process.env.WEWORK_SECRET || 'your_agent_secret',  // 应用 Secret
  AGENT_ID: process.env.WEWORK_AGENT_ID || '1000001',              // 应用 ID
  TOKEN_CACHE_FILE: './token_cache.json'  // access_token 缓存文件
};

// 群配置文件(存储 500 个群的 chatid)
const GROUPS_FILE = './groups.json';

// ============ Access Token 管理 ============
/**
 * 获取企业微信 access_token(带缓存)
 * token 有效期 7200 秒,缓存后复用
 */
async function getAccessToken() {
  try {
    // 尝试从缓存读取
    const cache = await loadTokenCache();
    if (cache && cache.expires_at > Date.now()) {
      console.log('✅ 使用缓存的 access_token');
      return cache.access_token;
    }

    // 缓存过期,重新获取
    console.log('🔄 获取新的 access_token...');
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/gettoken';
    const response = await axios.get(url, {
      params: {
        corpid: CONFIG.CORP_ID,
        corpsecret: CONFIG.AGENT_SECRET
      }
    });

    if (response.data.errcode !== 0) {
      throw new Error(`获取 token 失败: ${response.data.errmsg}`);
    }

    const token = response.data.access_token;
    const expiresIn = response.data.expires_in; // 7200 秒

    // 保存到缓存(提前 5 分钟过期以防边界情况)
    await saveTokenCache({
      access_token: token,
      expires_at: Date.now() + (expiresIn - 300) * 1000
    });

    console.log('✅ access_token 已获取并缓存');
    return token;

  } catch (error) {
    console.error('❌ 获取 access_token 失败:', error.message);
    throw error;
  }
}

// 加载 token 缓存
async function loadTokenCache() {
  try {
    const data = await fs.readFile(CONFIG.TOKEN_CACHE_FILE, 'utf-8');
    return JSON.parse(data);
  } catch {
    return null;
  }
}

// 保存 token 缓存
async function saveTokenCache(cache) {
  await fs.writeFile(CONFIG.TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2));
}

// ============ 群管理 ============
/**
 * 加载群配置
 * groups.json 格式:
 * {
 *   "groups": [
 *     { "id": "group_001", "name": "朝阳店客户群", "chatid": "wrOgQh..." },
 *     { "id": "group_002", "name": "海淀店客户群", "chatid": "wrOgQh..." }
 *   ]
 * }
 */
async function loadGroups() {
  try {
    const data = await fs.readFile(GROUPS_FILE, 'utf-8');
    return JSON.parse(data);
  } catch (error) {
    console.warn('⚠️ 群配置文件不存在,返回空列表');
    return { groups: [] };
  }
}

/**
 * 保存群配置
 */
async function saveGroups(groupsData) {
  await fs.writeFile(GROUPS_FILE, JSON.stringify(groupsData, null, 2));
  console.log('✅ 群配置已保存');
}

/**
 * 从企业微信 API 获取所有客户群列表
 */
async function fetchGroupsFromAPI() {
  try {
    const token = await getAccessToken();
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/groupchat/list';

    const response = await axios.post(url, {
      status_filter: 0,  // 0:所有群
      limit: 1000        // 一次最多 1000 个
    }, {
      params: { access_token: token }
    });

    if (response.data.errcode !== 0) {
      throw new Error(`获取群列表失败: ${response.data.errmsg}`);
    }

    const groupChatList = response.data.group_chat_list || [];

    // 获取每个群的详细信息
    const groups = [];
    for (const item of groupChatList) {
      const detail = await getGroupDetail(item.chat_id);
      groups.push({
        id: `group_${groups.length + 1}`.padStart(10, '0'),
        name: detail.name || '未命名群',
        chatid: item.chat_id,
        member_count: detail.member_list?.length || 0
      });
    }

    return { groups };

  } catch (error) {
    console.error('❌ 获取群列表失败:', error.message);
    throw error;
  }
}

/**
 * 获取单个群的详细信息
 */
async function getGroupDetail(chatId) {
  try {
    const token = await getAccessToken();
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/groupchat/get';

    const response = await axios.post(url, {
      chat_id: chatId
    }, {
      params: { access_token: token }
    });

    if (response.data.errcode !== 0) {
      console.warn(`⚠️ 获取群详情失败 ${chatId}: ${response.data.errmsg}`);
      return { name: '未知群', member_list: [] };
    }

    return response.data.group_chat;

  } catch (error) {
    console.error(`❌ 获取群详情异常 ${chatId}:`, error.message);
    return { name: '未知群', member_list: [] };
  }
}

// ============ 消息发送 ============
/**
 * 发送文本消息到指定客户群
 * @param {string} chatId - 群的 chat_id
 * @param {string} content - 消息内容
 */
async function sendMessageToGroup(chatId, content) {
  try {
    const token = await getAccessToken();
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/appchat/send';

    const response = await axios.post(url, {
      chatid: chatId,
      msgtype: 'text',
      text: {
        content: content
      },
      safe: 0  // 0:可转发分享  1:不可转发
    }, {
      params: { access_token: token }
    });

    if (response.data.errcode !== 0) {
      throw new Error(`发送失败: ${response.data.errmsg}`);
    }

    return response.data;

  } catch (error) {
    console.error(`❌ 发送消息到群 ${chatId} 失败:`, error.message);
    throw error;
  }
}

/**
 * 批量发送消息到多个群
 * @param {array} chatIds - 群 ID 数组
 * @param {string} content - 消息内容
 */
async function broadcastMessage(chatIds, content) {
  const results = {
    success: [],
    failed: []
  };

  for (const chatId of chatIds) {
    try {
      await sendMessageToGroup(chatId, content);
      results.success.push(chatId);
      console.log(`✅ 已发送到群: ${chatId}`);
    } catch (error) {
      results.failed.push({ chatId, error: error.message });
      console.error(`❌ 发送失败: ${chatId}`);
    }

    // 避免触发频率限制,每条消息间隔 100ms
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  return results;
}

// ============ API 接口 ============

/**
 * 抖音消息回调接口
 * POST /douyin/callback
 */
app.post('/douyin/callback', async (req, res) => {
  try {
    const { type, content, timestamp } = req.body;

    if (type === 'im_message' || type === 'order') {
      // 构造通知消息
      const message = formatOrderNotification({
        source: '抖音',
        customerId: content.customer_id || '未知',
        message: content.message || content.order_info,
        time: new Date(timestamp * 1000).toLocaleTimeString('zh-CN')
      });

      // 加载所有群配置
      const groupsData = await loadGroups();
      const chatIds = groupsData.groups.map(g => g.chatid);

      // 广播到所有群
      const results = await broadcastMessage(chatIds, message);

      console.log(`📢 消息已推送: 成功 ${results.success.length}, 失败 ${results.failed.length}`);

      res.json({
        success: true,
        broadcast_results: results
      });
    } else {
      res.json({ success: true, message: '忽略的消息类型' });
    }

  } catch (error) {
    console.error('❌ 处理抖音回调失败:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * 手动发送测试消息
 * POST /test/send
 * Body: { "message": "测试内容", "chatIds": ["wrOgQh..."] }
 */
app.post('/test/send', async (req, res) => {
  try {
    const { message, chatIds } = req.body;

    if (!message) {
      return res.status(400).json({ error: '缺少 message 参数' });
    }

    // 如果没有指定群,发送到所有群
    let targetChatIds = chatIds;
    if (!targetChatIds || targetChatIds.length === 0) {
      const groupsData = await loadGroups();
      targetChatIds = groupsData.groups.map(g => g.chatid);
    }

    const results = await broadcastMessage(targetChatIds, message);

    res.json({
      success: true,
      message: '测试消息已发送',
      results
    });

  } catch (error) {
    console.error('❌ 发送测试消息失败:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * 获取群列表
 * GET /groups
 */
app.get('/groups', async (req, res) => {
  try {
    const groupsData = await loadGroups();
    res.json(groupsData);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

/**
 * 从企业微信同步群列表
 * POST /groups/sync
 */
app.post('/groups/sync', async (req, res) => {
  try {
    console.log('🔄 开始同步群列表...');
    const groupsData = await fetchGroupsFromAPI();
    await saveGroups(groupsData);

    res.json({
      success: true,
      message: `已同步 ${groupsData.groups.length} 个群`,
      groups: groupsData.groups
    });

  } catch (error) {
    console.error('❌ 同步群列表失败:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * 手动添加群
 * POST /groups/add
 * Body: { "name": "新群", "chatid": "wrOgQh..." }
 */
app.post('/groups/add', async (req, res) => {
  try {
    const { name, chatid } = req.body;

    if (!name || !chatid) {
      return res.status(400).json({ error: '缺少 name 或 chatid' });
    }

    const groupsData = await loadGroups();
    const newId = `group_${groupsData.groups.length + 1}`.padStart(10, '0');

    groupsData.groups.push({
      id: newId,
      name,
      chatid,
      added_at: new Date().toISOString()
    });

    await saveGroups(groupsData);

    res.json({
      success: true,
      message: '群已添加',
      group: groupsData.groups[groupsData.groups.length - 1]
    });

  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// ============ 辅助函数 ============
function formatOrderNotification({ source, customerId, message, time }) {
  return `🔔 新顾客咨询提醒

📱 来源: ${source}
👤 顾客ID: ${customerId}
⏰ 时间: ${time}
💬 内容: ${message}

请及时回复!`;
}

// ============ 启动服务 ============
const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`
╔════════════════════════════════════════════╗
║  企业微信客户群消息推送服务               ║
╚════════════════════════════════════════════╝

🚀 服务已启动: http://localhost:${PORT}

📡 接口列表:
  - POST /douyin/callback      抖音消息回调
  - POST /test/send            手动测试推送
  - GET  /groups               查看群列表
  - POST /groups/sync          同步群列表
  - POST /groups/add           手动添加群

📝 配置文件:
  - ${GROUPS_FILE}             群配置

⚙️ 环境变量:
  - WEWORK_CORP_ID=${CONFIG.CORP_ID}
  - WEWORK_SECRET=${CONFIG.AGENT_SECRET.substring(0, 10)}...
  - WEWORK_AGENT_ID=${CONFIG.AGENT_ID}

💡 快速测试:
  curl -X POST http://localhost:${PORT}/test/send \\
    -H "Content-Type: application/json" \\
    -d '{"message":"测试消息"}'
  `);
});
