/**
 * 美容店来客通知管理后台 - 前端逻辑
 */

// API 基础地址
const API_BASE = window.location.origin;

// 全局状态
const state = {
  shops: [],
  logs: [],
  stats: {},
  currentPage: 'dashboard'
};

/**
 * 页面初始化
 */
document.addEventListener('DOMContentLoaded', () => {
  // 初始化页面导航
  initNavigation();

  // 检查服务状态
  checkServerStatus();

  // 加载概览数据
  loadDashboard();

  // 设置 Webhook URL
  setupWebhookUrls();

  // 每 30 秒刷新一次状态
  setInterval(checkServerStatus, 30000);
});

/**
 * 初始化页面导航
 */
function initNavigation() {
  const menuItems = document.querySelectorAll('.menu-item');

  menuItems.forEach(item => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;

      // 更新菜单激活状态
      menuItems.forEach(i => i.classList.remove('active'));
      item.classList.add('active');

      // 切换页面内容
      document.querySelectorAll('.page-content').forEach(p => {
        p.classList.remove('active');
      });
      document.getElementById(page).classList.add('active');

      state.currentPage = page;

      // 加载对应页面数据
      loadPageData(page);
    });
  });
}

/**
 * 加载页面数据
 */
function loadPageData(page) {
  switch(page) {
    case 'dashboard':
      loadDashboard();
      break;
    case 'shops':
      loadShops();
      break;
    case 'logs':
      loadLogs();
      break;
    case 'config':
      loadConfig();
      break;
    case 'webhook':
      loadWebhookTest();
      break;
  }
}

/**
 * 检查服务器状态
 */
async function checkServerStatus() {
  try {
    const response = await fetch(`${API_BASE}/api/health`);
    const data = await response.json();

    if (data.status === 'ok') {
      document.getElementById('statusDot').classList.add('online');
      document.getElementById('statusDot').classList.remove('offline');
      document.getElementById('statusText').textContent = '运行中';
    } else {
      throw new Error('服务异常');
    }
  } catch (error) {
    document.getElementById('statusDot').classList.add('offline');
    document.getElementById('statusDot').classList.remove('online');
    document.getElementById('statusText').textContent = '离线';
  }
}

/**
 * 加载概览页面数据
 */
async function loadDashboard() {
  try {
    // 加载统计数据
    const statsRes = await fetch(`${API_BASE}/api/admin/statistics`);
    const statsData = await statsRes.json();

    if (statsData.code === 0) {
      state.stats = statsData.data;
      updateStatsCards(statsData.data);
    }

    // 加载最近消息
    const logsRes = await fetch(`${API_BASE}/api/admin/logs?limit=10`);
    const logsData = await logsRes.json();

    if (logsData.code === 0) {
      renderRecentMessages(logsData.data);
    }

  } catch (error) {
    console.error('加载概览数据失败:', error);
    showError('加载概览数据失败');
  }
}

/**
 * 更新统计卡片
 */
function updateStatsCards(stats) {
  document.getElementById('totalShops').textContent = stats.total_shops || 0;
  document.getElementById('todayMessages').textContent = stats.today_messages || 0;
  document.getElementById('successRate').textContent =
    stats.success_rate ? `${stats.success_rate}%` : '-';
  document.getElementById('totalCustomers').textContent = stats.total_customers || 0;
}

/**
 * 渲染最近消息
 */
function renderRecentMessages(messages) {
  const container = document.getElementById('recentMessages');

  if (!messages || messages.length === 0) {
    container.innerHTML = '<div class="loading">暂无消息记录</div>';
    return;
  }

  container.innerHTML = messages.map(msg => `
    <div class="message-item ${msg.push_success ? 'success' : 'failed'}">
      <div class="message-header">
        <div>
          <span class="message-shop">${msg.shop_name || '未知店铺'}</span>
          <span class="badge ${msg.push_success ? 'badge-success' : 'badge-danger'}">
            ${msg.push_success ? '成功' : '失败'}
          </span>
        </div>
        <span class="message-time">${formatTime(msg.created_at)}</span>
      </div>
      <div class="message-body">
        <strong>${msg.customer_nickname || '顾客'}</strong>: ${msg.message_content || '无消息内容'}
      </div>
    </div>
  `).join('');
}

/**
 * 刷新概览页面
 */
function refreshDashboard() {
  loadDashboard();
}

/**
 * 加载店铺列表
 */
async function loadShops() {
  const container = document.getElementById('shopsList');
  container.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const response = await fetch(`${API_BASE}/api/admin/shops`);
    const data = await response.json();

    if (data.code === 0) {
      state.shops = data.data;
      renderShopsList(data.data);

      // 同时更新测试表单和日志过滤器的店铺列表
      updateShopSelects(data.data);
    } else {
      throw new Error(data.error || '加载失败');
    }
  } catch (error) {
    console.error('加载店铺列表失败:', error);
    container.innerHTML = `<div class="loading">加载失败: ${error.message}</div>`;
  }
}

/**
 * 渲染店铺列表
 */
function renderShopsList(shops) {
  const container = document.getElementById('shopsList');

  if (!shops || shops.length === 0) {
    container.innerHTML = `
      <div class="loading">
        暂无店铺<br>
        <button class="btn btn-primary" onclick="showAuthModal()" style="margin-top: 1rem;">
          授权第一个店铺
        </button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>店铺名称</th>
          <th>店铺ID</th>
          <th>企微群</th>
          <th>Token 状态</th>
          <th>最后更新</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${shops.map(shop => `
          <tr>
            <td><strong>${shop.shop_name}</strong></td>
            <td><code>${shop.shop_id}</code></td>
            <td>
              ${shop.wework_chat_name
                ? `<span class="badge badge-success">${shop.wework_chat_name}</span>`
                : '<span class="badge badge-warning">未配置</span>'}
            </td>
            <td>
              ${isTokenValid(shop.token_expires_at)
                ? '<span class="badge badge-success">有效</span>'
                : '<span class="badge badge-danger">已过期</span>'}
            </td>
            <td>${formatTime(shop.updated_at)}</td>
            <td>
              <button class="btn btn-sm" onclick="configWeworkChat('${shop.shop_id}')">
                配置企微群
              </button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

/**
 * 更新店铺选择器
 */
function updateShopSelects(shops) {
  const selects = [
    document.getElementById('testShopId'),
    document.getElementById('logShopFilter')
  ];

  selects.forEach(select => {
    if (!select) return;

    // 保留第一个选项(提示文本)
    const firstOption = select.options[0];
    select.innerHTML = '';
    if (firstOption) {
      select.appendChild(firstOption);
    }

    // 添加店铺选项
    shops.forEach(shop => {
      const option = document.createElement('option');
      option.value = shop.shop_id;
      option.textContent = shop.shop_name;
      select.appendChild(option);
    });
  });
}

/**
 * 显示授权弹窗
 */
function showAuthModal() {
  const modal = document.getElementById('authModal');
  const authUrl = `https://open.douyin.com/platform/oauth/connect/?client_key=YOUR_CLIENT_KEY&response_type=code&scope=life.order&redirect_uri=${encodeURIComponent(window.location.origin + '/api/douyin/callback')}`;

  document.getElementById('authUrl').value = authUrl;
  modal.classList.add('active');
}

/**
 * 关闭授权弹窗
 */
function closeAuthModal() {
  document.getElementById('authModal').classList.remove('active');
}

/**
 * 配置企微群
 */
async function configWeworkChat(shopId) {
  const chatId = prompt('请输入企微客户群 Chat ID:');
  if (!chatId) return;

  const chatName = prompt('请输入企微群名称(可选):') || '';

  try {
    const response = await fetch(`${API_BASE}/api/admin/shops/${shopId}/wework-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chatId, chatName })
    });

    const data = await response.json();

    if (data.code === 0) {
      alert('配置成功!');
      loadShops();
    } else {
      throw new Error(data.error || '配置失败');
    }
  } catch (error) {
    alert(`配置失败: ${error.message}`);
  }
}

/**
 * 加载消息日志
 */
async function loadLogs() {
  const container = document.getElementById('logsList');
  const shopFilter = document.getElementById('logShopFilter').value;

  container.innerHTML = '<div class="loading">加载中...</div>';

  try {
    let url = `${API_BASE}/api/admin/logs?limit=100`;
    if (shopFilter) {
      url += `&shopId=${shopFilter}`;
    }

    const response = await fetch(url);
    const data = await response.json();

    if (data.code === 0) {
      state.logs = data.data;
      renderLogsList(data.data);
    } else {
      throw new Error(data.error || '加载失败');
    }
  } catch (error) {
    console.error('加载日志失败:', error);
    container.innerHTML = `<div class="loading">加载失败: ${error.message}</div>`;
  }
}

/**
 * 渲染日志列表
 */
function renderLogsList(logs) {
  const container = document.getElementById('logsList');

  if (!logs || logs.length === 0) {
    container.innerHTML = '<div class="loading">暂无日志记录</div>';
    return;
  }

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>时间</th>
          <th>店铺</th>
          <th>顾客</th>
          <th>消息内容</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        ${logs.map(log => `
          <tr>
            <td style="white-space: nowrap;">${formatTime(log.created_at)}</td>
            <td>${log.shop_name || '未知'}</td>
            <td>${log.customer_nickname || '-'}</td>
            <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">
              ${log.message_content || '-'}
            </td>
            <td>
              <span class="badge ${log.push_success ? 'badge-success' : 'badge-danger'}">
                ${log.push_success ? '成功' : '失败'}
              </span>
              ${log.error_message ? `<br><small style="color: var(--danger-color);">${log.error_message}</small>` : ''}
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

/**
 * 加载系统配置
 */
function loadConfig() {
  // 显示环境变量(敏感信息脱敏)
  const envVars = [
    { key: 'DOUYIN_CLIENT_KEY', value: '已配置', masked: true },
    { key: 'DOUYIN_CLIENT_SECRET', value: '已配置', masked: true },
    { key: 'WEWORK_CORP_ID', value: '已配置', masked: true },
    { key: 'WEWORK_SECRET', value: '已配置', masked: true },
    { key: 'NODE_ENV', value: 'production', masked: false },
    { key: 'PORT', value: '3000', masked: false }
  ];

  const container = document.getElementById('envVars');
  container.innerHTML = envVars.map(env => `
    <div class="env-item">
      <span class="env-key">${env.key}</span>
      <span class="env-value">${env.masked ? '●●●●●●●●' : env.value}</span>
    </div>
  `).join('');
}

/**
 * 设置 Webhook URLs
 */
function setupWebhookUrls() {
  const baseUrl = window.location.origin;
  document.getElementById('webhookUrl').value = `${baseUrl}/api/douyin/webhook`;
  document.getElementById('callbackUrl').value = `${baseUrl}/api/douyin/callback`;
}

/**
 * 加载 Webhook 测试页面
 */
function loadWebhookTest() {
  // 店铺列表已在 loadShops 中更新
  if (state.shops.length === 0) {
    loadShops();
  }
}

/**
 * 发送测试消息
 */
async function sendTestMessage(event) {
  event.preventDefault();

  const shopId = document.getElementById('testShopId').value;
  const testMessage = document.getElementById('testMessage').value;
  const resultDiv = document.getElementById('testResult');

  if (!shopId) {
    showTestResult('error', '请选择店铺');
    return;
  }

  resultDiv.className = 'test-result';
  resultDiv.textContent = '发送中...';
  resultDiv.classList.add('show');

  try {
    const response = await fetch(`${API_BASE}/api/test/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shopId, testMessage })
    });

    const data = await response.json();

    if (data.code === 0) {
      showTestResult('success', '✅ 测试消息发送成功!');
    } else {
      throw new Error(data.error || '发送失败');
    }
  } catch (error) {
    showTestResult('error', `❌ 发送失败: ${error.message}`);
  }
}

/**
 * 显示测试结果
 */
function showTestResult(type, message) {
  const resultDiv = document.getElementById('testResult');
  resultDiv.className = `test-result ${type} show`;
  resultDiv.textContent = message;
}

/**
 * 复制到剪贴板
 */
function copyToClipboard(elementId) {
  const element = document.getElementById(elementId);
  element.select();
  element.setSelectionRange(0, 99999);

  try {
    document.execCommand('copy');
    alert('已复制到剪贴板');
  } catch (err) {
    alert('复制失败,请手动复制');
  }
}

/**
 * 工具函数: 格式化时间
 */
function formatTime(timestamp) {
  if (!timestamp) return '-';

  const date = new Date(timestamp);
  const now = new Date();
  const diff = now - date;

  // 1分钟内
  if (diff < 60000) {
    return '刚刚';
  }

  // 1小时内
  if (diff < 3600000) {
    return `${Math.floor(diff / 60000)} 分钟前`;
  }

  // 今天
  if (date.toDateString() === now.toDateString()) {
    return `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }

  // 昨天
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `昨天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }

  // 其他
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

/**
 * 工具函数: 检查 Token 是否有效
 */
function isTokenValid(expiresAt) {
  if (!expiresAt) return false;
  return new Date(expiresAt) > new Date();
}

/**
 * 显示错误提示
 */
function showError(message) {
  console.error(message);
  // 可以实现一个 Toast 提示组件
}
