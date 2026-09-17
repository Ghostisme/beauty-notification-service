/**
 * 美容店来客通知管理后台 - 前端逻辑
 * 使用 Bootstrap 5
 */

// API 基础地址
const API_BASE = window.location.origin;

// Bootstrap Modal 实例
let authModalInstance = null;

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
  // 初始化 Bootstrap 组件
  initBootstrapComponents();

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
 * 初始化 Bootstrap 组件
 */
function initBootstrapComponents() {
  // 初始化模态框
  const authModalEl = document.getElementById('authModal');
  if (authModalEl) {
    authModalInstance = new bootstrap.Modal(authModalEl);
  }
}

/**
 * 页面切换
 */
function switchPage(event, page) {
  event.preventDefault();

  // 更新侧边栏激活状态
  document.querySelectorAll('.sidebar .nav-link').forEach(link => {
    link.classList.remove('active');
  });
  event.currentTarget.classList.add('active');

  // 切换页面内容
  document.querySelectorAll('.page-content').forEach(content => {
    content.style.display = 'none';
  });
  document.getElementById(page).style.display = 'block';

  state.currentPage = page;

  // 加载对应页面数据
  loadPageData(page);
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
  const statusBadge = document.getElementById('statusBadge');
  const statusIcon = document.getElementById('statusIcon');
  const statusText = document.getElementById('statusText');

  try {
    const response = await fetch(`${API_BASE}/api/health`);
    const data = await response.json();

    if (data.status === 'ok') {
      statusBadge.className = 'badge bg-success rounded-pill';
      statusIcon.className = 'bi bi-circle-fill me-1';
      statusText.textContent = '运行中';
    } else {
      throw new Error('服务异常');
    }
  } catch (error) {
    statusBadge.className = 'badge bg-danger rounded-pill';
    statusIcon.className = 'bi bi-circle-fill me-1';
    statusText.textContent = '离线';
  }
}

/**
 * 加载概览页面数据
 */
async function loadDashboard() {
  try {
    // 加载统计数据
    const statsRes = await fetch(`${API_BASE}/api/admin/shops`);
    if (statsRes.ok) {
      const statsData = await statsRes.json();
      if (statsData.code === 0) {
        updateStatsCards(statsData.data);
      }
    }

    // 加载最近消息
    const logsRes = await fetch(`${API_BASE}/api/admin/logs?limit=10`);
    if (logsRes.ok) {
      const logsData = await logsRes.json();
      if (logsData.code === 0) {
        renderRecentMessages(logsData.data);
      }
    }

  } catch (error) {
    console.error('加载概览数据失败:', error);
    showToast('加载概览数据失败', 'danger');
  }
}

/**
 * 更新统计卡片
 */
function updateStatsCards(shops) {
  document.getElementById('totalShops').textContent = shops?.length || 0;

  // 简化统计 - 实际数据需要后端 API 支持
  document.getElementById('todayMessages').textContent = '-';
  document.getElementById('successRate').textContent = '-';
  document.getElementById('totalCustomers').textContent = '-';
}

/**
 * 渲染最近消息
 */
function renderRecentMessages(messages) {
  const container = document.getElementById('recentMessages');

  if (!messages || messages.length === 0) {
    container.innerHTML = `
      <div class="text-center py-4 text-muted">
        <i class="bi bi-inbox fs-1 d-block mb-2"></i>
        <p>暂无消息记录</p>
      </div>
    `;
    return;
  }

  container.innerHTML = messages.map(msg => `
    <div class="message-item">
      <div class="d-flex justify-content-between align-items-start mb-2">
        <div>
          <span class="fw-bold">${msg.shop_name || '未知店铺'}</span>
          <span class="badge bg-${msg.push_success ? 'success' : 'danger'} ms-2">
            ${msg.push_success ? '成功' : '失败'}
          </span>
        </div>
        <span class="message-time">${formatTime(msg.created_at)}</span>
      </div>
      <div class="text-muted">
        <strong>${msg.customer_nickname || '顾客'}</strong>: ${msg.message_content || '无消息内容'}
      </div>
    </div>
  `).join('');
}

/**
 * 刷新概览页面
 */
function refreshDashboard() {
  showToast('正在刷新...', 'info');
  loadDashboard();
}

/**
 * 加载店铺列表
 */
async function loadShops() {
  const container = document.getElementById('shopsList');
  container.innerHTML = `
    <div class="text-center py-5">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">加载中...</span>
      </div>
      <p class="mt-2 text-muted">加载中...</p>
    </div>
  `;

  try {
    const response = await fetch(`${API_BASE}/api/admin/shops`);
    const data = await response.json();

    if (data.code === 0) {
      state.shops = data.data;
      renderShopsList(data.data);
      updateShopSelects(data.data);
    } else {
      throw new Error(data.error || '加载失败');
    }
  } catch (error) {
    console.error('加载店铺列表失败:', error);
    container.innerHTML = `
      <div class="alert alert-danger" role="alert">
        <i class="bi bi-exclamation-triangle me-2"></i>
        加载失败: ${error.message}
      </div>
    `;
  }
}

/**
 * 渲染店铺列表
 */
function renderShopsList(shops) {
  const container = document.getElementById('shopsList');

  if (!shops || shops.length === 0) {
    container.innerHTML = `
      <div class="text-center py-5">
        <i class="bi bi-shop fs-1 text-muted d-block mb-3"></i>
        <p class="text-muted mb-3">暂无店铺</p>
        <button class="btn btn-primary" onclick="showAuthModal()">
          <i class="bi bi-plus-circle me-1"></i> 授权第一个店铺
        </button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-hover align-middle">
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
              <td><code class="text-muted">${shop.shop_id}</code></td>
              <td>
                ${shop.wework_chat_name
                  ? `<span class="badge bg-success">${shop.wework_chat_name}</span>`
                  : '<span class="badge bg-warning text-dark">未配置</span>'}
              </td>
              <td>
                ${isTokenValid(shop.token_expires_at)
                  ? '<span class="badge bg-success">有效</span>'
                  : '<span class="badge bg-danger">已过期</span>'}
              </td>
              <td>${formatTime(shop.updated_at)}</td>
              <td>
                <button class="btn btn-sm btn-outline-primary" onclick="configWeworkChat('${shop.shop_id}')">
                  <i class="bi bi-gear me-1"></i> 配置企微群
                </button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
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

    const firstOption = select.options[0];
    select.innerHTML = '';
    if (firstOption) {
      select.appendChild(firstOption);
    }

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
  const authUrl = `https://open.douyin.com/platform/oauth/connect/?client_key=YOUR_CLIENT_KEY&response_type=code&scope=life.order&redirect_uri=${encodeURIComponent(window.location.origin + '/api/douyin/callback')}`;

  document.getElementById('authUrl').value = authUrl;

  if (authModalInstance) {
    authModalInstance.show();
  }
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
      showToast('配置成功!', 'success');
      loadShops();
    } else {
      throw new Error(data.error || '配置失败');
    }
  } catch (error) {
    showToast(`配置失败: ${error.message}`, 'danger');
  }
}

/**
 * 加载消息日志
 */
async function loadLogs() {
  const container = document.getElementById('logsList');
  const shopFilter = document.getElementById('logShopFilter').value;

  container.innerHTML = `
    <div class="text-center py-5">
      <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">加载中...</span>
      </div>
    </div>
  `;

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
    container.innerHTML = `
      <div class="alert alert-danger" role="alert">
        加载失败: ${error.message}
      </div>
    `;
  }
}

/**
 * 渲染日志列表
 */
function renderLogsList(logs) {
  const container = document.getElementById('logsList');

  if (!logs || logs.length === 0) {
    container.innerHTML = `
      <div class="text-center py-4 text-muted">
        <i class="bi bi-inbox fs-1 d-block mb-2"></i>
        <p>暂无日志记录</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-hover align-middle">
        <thead>
          <tr>
            <th style="width: 150px;">时间</th>
            <th>店铺</th>
            <th>顾客</th>
            <th>消息内容</th>
            <th style="width: 100px;">状态</th>
          </tr>
        </thead>
        <tbody>
          ${logs.map(log => `
            <tr class="log-item log-${log.push_success ? 'success' : 'error'}">
              <td class="text-nowrap">${formatTime(log.created_at)}</td>
              <td>${log.shop_name || '未知'}</td>
              <td>${log.customer_nickname || '-'}</td>
              <td class="text-truncate" style="max-width: 300px;">
                ${log.message_content || '-'}
              </td>
              <td>
                <span class="badge bg-${log.push_success ? 'success' : 'danger'}">
                  ${log.push_success ? '成功' : '失败'}
                </span>
                ${log.error_message ? `<br><small class="text-danger">${log.error_message}</small>` : ''}
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

/**
 * 加载系统配置
 */
function loadConfig() {
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
    resultDiv.innerHTML = `
      <div class="alert alert-warning alert-dismissible fade show" role="alert">
        <i class="bi bi-exclamation-triangle me-2"></i>
        请选择店铺
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      </div>
    `;
    return;
  }

  resultDiv.innerHTML = `
    <div class="alert alert-info" role="alert">
      <div class="spinner-border spinner-border-sm me-2" role="status"></div>
      发送中...
    </div>
  `;

  try {
    const response = await fetch(`${API_BASE}/api/test/push`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shopId, testMessage })
    });

    const data = await response.json();

    if (data.code === 0) {
      resultDiv.innerHTML = `
        <div class="alert alert-success alert-dismissible fade show" role="alert">
          <i class="bi bi-check-circle me-2"></i>
          测试消息发送成功!
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      `;
    } else {
      throw new Error(data.error || '发送失败');
    }
  } catch (error) {
    resultDiv.innerHTML = `
      <div class="alert alert-danger alert-dismissible fade show" role="alert">
        <i class="bi bi-x-circle me-2"></i>
        发送失败: ${error.message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      </div>
    `;
  }
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
    showToast('已复制到剪贴板', 'success');
  } catch (err) {
    showToast('复制失败,请手动复制', 'danger');
  }
}

/**
 * 显示 Toast 提示
 */
function showToast(message, type = 'info') {
  // 简单的提示实现,可以使用 Bootstrap Toast 组件替代
  console.log(`[${type.toUpperCase()}] ${message}`);
}

/**
 * 工具函数: 格式化时间
 */
function formatTime(timestamp) {
  if (!timestamp) return '-';

  const date = new Date(timestamp);
  const now = new Date();
  const diff = now - date;

  if (diff < 60000) {
    return '刚刚';
  }

  if (diff < 3600000) {
    return `${Math.floor(diff / 60000)} 分钟前`;
  }

  if (date.toDateString() === now.toDateString()) {
    return `今天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `昨天 ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
  }

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
