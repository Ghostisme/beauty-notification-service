// ============================================
// 企业微信客户群消息推送服务 v2.0
// 功能:以员工身份向客户群发送消息(更自然)
// ============================================

const express = require('express');
const axios = require('axios');
const fs = require('fs').promises;

const app = express();
app.use(express.json());

// ============ 配置区 ============
const CONFIG = {
  CORP_ID: process.env.WEWORK_CORP_ID || 'your_corp_id',
  AGENT_SECRET: process.env.WEWORK_SECRET || 'your_agent_secret',
  AGENT_ID: process.env.WEWORK_AGENT_ID || '1000001',
  // 发送消息的员工 UserID(需要先添加到所有客户群)
  SENDER_USERID: process.env.SENDER_USERID || 'OrderAssistant',
  TOKEN_CACHE_FILE: './token_cache.json'
};

const GROUPS_FILE = './groups.json';

// ============ Access Token 管理 ============
async function getAccessToken() {
  try {
    const cache = await loadTokenCache();
    if (cache && cache.expires_at > Date.now()) {
      return cache.access_token;
    }

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
    const expiresIn = response.data.expires_in;

    await saveTokenCache({
      access_token: token,
      expires_at: Date.now() + (expiresIn - 300) * 1000
    });

    return token;
  } catch (error) {
    console.error('❌ 获取 access_token 失败:', error.message);
    throw error;
  }
}

async function loadTokenCache() {
  try {
    const data = await fs.readFile(CONFIG.TOKEN_CACHE_FILE, 'utf-8');
    return JSON.parse(data);
  } catch {
    return null;
  }
}

async function saveTokenCache(cache) {
  await fs.writeFile(CONFIG.TOKEN_CACHE_FILE, JSON.stringify(cache, null, 2));
}

// ============ 群管理 ============
async function loadGroups() {
  try {
    const data = await fs.readFile(GROUPS_FILE, 'utf-8');
    return JSON.parse(data);
  } catch (error) {
    return { groups: [] };
  }
}

async function saveGroups(groupsData) {
  await fs.writeFile(GROUPS_FILE, JSON.stringify(groupsData, null, 2));
}

/**
 * 获取客户群列表
 */
async function fetchGroupsFromAPI() {
  try {
    const token = await getAccessToken();
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/groupchat/list';

    const response = await axios.post(url, {
      status_filter: 0,
      owner_filter: {
        userid_list: [CONFIG.SENDER_USERID]  // 只获取指定员工的群
      },
      limit: 1000
    }, {
      params: { access_token: token }
    });

    if (response.data.errcode !== 0) {
      throw new Error(`获取群列表失败: ${response.data.errmsg}`);
    }

    const groupChatList = response.data.group_chat_list || [];
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
      return { name: '未知群', member_list: [] };
    }

    return response.data.group_chat;
  } catch (error) {
    return { name: '未知群', member_list: [] };
  }
}

// ============ 消息发送(以员工身份) ============
/**
 * 以指定员工身份向客户群发送消息
 * 这样客户看到的是员工发的,不是系统应用
 */
async function sendMessageAsEmployee(chatId, content) {
  try {
    const token = await getAccessToken();
    const url = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/add_msg_template';

    const response = await axios.post(url, {
      chat_type: 'group',  // 群聊类型
      external_userid: [],  // 空表示发给整个群
      sender: CONFIG.SENDER_USERID,  // 发送者的 UserID
      text: {
        content: content
      },
      attachments: []  // 可以添加图片、文件等附件
    }, {
      params: { access_token: token }
    });

    if (response.data.errcode !== 0) {
      throw new Error(`发送失败: ${response.data.errmsg}`);
    }

    // 获取消息模板 ID
    const msgid = response.data.msgid;

    // 发送到指定客户群
    const sendUrl = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/send_msg_to_groupchat';
    const sendResponse = await axios.post(sendUrl, {
      msgid: msgid,
      chat_id_list: [chatId]
    }, {
      params: { access_token: token }
    });

    if (sendResponse.data.errcode !== 0) {
      throw new Error(`群发送失败: ${sendResponse.data.errmsg}`);
    }

    return sendResponse.data;

  } catch (error) {
    console.error(`❌ 发送消息到群 ${chatId} 失败:`, error.message);
    throw error;
  }
}

/**
 * 批量发送消息到多个群(以员工身份)
 */
async function broadcastMessageAsEmployee(chatIds, content) {
  const results = {
    success: [],
    failed: []
  };

  try {
    const token = await getAccessToken();

    // 1. 创建消息模板
    const templateUrl = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/add_msg_template';
    const templateResponse = await axios.post(templateUrl, {
      chat_type: 'group',
      sender: CONFIG.SENDER_USERID,
      text: {
        content: content
      }
    }, {
      params: { access_token: token }
    });

    if (templateResponse.data.errcode !== 0) {
      throw new Error(`创建消息模板失败: ${templateResponse.data.errmsg}`);
    }

    const msgid = templateResponse.data.msgid;

    // 2. 批量发送(企微支持一次最多 100 个群)
    const batchSize = 100;
    for (let i = 0; i < chatIds.length; i += batchSize) {
      const batch = chatIds.slice(i, i + batchSize);

      const sendUrl = 'https://qyapi.weixin.qq.com/cgi-bin/externalcontact/send_msg_to_groupchat';
      const sendResponse = await axios.post(sendUrl, {
        msgid: msgid,
        chat_id_list: batch
      }, {
        params: { access_token: token }
      });

      if (sendResponse.data.errcode === 0) {
        results.success.push(...batch);
        console.log(`✅ 已发送到 ${batch.length} 个群`);
      } else {
        results.failed.push(...batch.map(id => ({
          chatId: id,
          error: sendResponse.data.errmsg
        })));
        console.error(`❌ 批次发送失败: ${sendResponse.data.errmsg}`);
      }

      // 避免频率限制
      await new Promise(resolve => setTimeout(resolve, 200));
    }

    return results;

  } catch (error) {
    console.error('❌ 批量发送失败:', error.message);
    // 所有群都标记为失败
    chatIds.forEach(chatId => {
      results.failed.push({ chatId, error: error.message });
    });
    return results;
  }
}

// ============ API 接口 ============

/**
 * 抖音消息回调
 */
app.post('/douyin/callback', async (req, res) => {
  try {
    const { type, content, timestamp } = req.body;

    if (type === 'im_message' || type === 'order') {
      const message = formatOrderNotification({
        source: '抖音',
        customerId: content.customer_id || '未知',
        message: content.message || content.order_info,
        time: new Date(timestamp * 1000).toLocaleTimeString('zh-CN')
      });

      const groupsData = await loadGroups();
      const chatIds = groupsData.groups.map(g => g.chatid);

      // 以员工身份广播
      const results = await broadcastMessageAsEmployee(chatIds, message);

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
 * 测试发送
 */
app.post('/test/send', async (req, res) => {
  try {
    const { message, chatIds } = req.body;

    if (!message) {
      return res.status(400).json({ error: '缺少 message 参数' });
    }

    let targetChatIds = chatIds;
    if (!targetChatIds || targetChatIds.length === 0) {
      const groupsData = await loadGroups();
      targetChatIds = groupsData.groups.map(g => g.chatid);
    }

    const results = await broadcastMessageAsEmployee(targetChatIds, message);

    res.json({
      success: true,
      message: `测试消息已以 ${CONFIG.SENDER_USERID} 身份发送`,
      results
    });

  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/groups', async (req, res) => {
  try {
    const groupsData = await loadGroups();
    res.json(groupsData);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

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
    res.status(500).json({ success: false, error: error.message });
  }
});

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
║  企业微信客户群消息推送服务 v2.0         ║
║  (以员工身份发送,更自然)                 ║
╚════════════════════════════════════════════╝

🚀 服务已启动: http://localhost:${PORT}

👤 发送者: ${CONFIG.SENDER_USERID}
   (客户会看到这个员工发的消息)

📡 接口列表:
  - POST /douyin/callback      抖音消息回调
  - POST /test/send            手动测试推送
  - GET  /groups               查看群列表
  - POST /groups/sync          同步群列表
  - POST /groups/add           手动添加群

⚙️ 环境变量:
  - WEWORK_CORP_ID=${CONFIG.CORP_ID}
  - SENDER_USERID=${CONFIG.SENDER_USERID}

💡 使用前请确保:
  1. 已创建员工账号: ${CONFIG.SENDER_USERID}
  2. 该员工已加入所有客户群
  3. 应用有"客户联系"权限
  `);
});
