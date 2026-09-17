# 前端组件化架构说明

本管理后台采用 Bootstrap 5 框架,实现了模块化的组件结构。

## 📁 项目结构

```
web/
├── index.html          # 主页面 - Bootstrap 布局
├── style.css           # 自定义样式
├── app.js              # 主应用逻辑
└── components/         # 组件目录(待扩展)
    ├── dashboard.js    # 概览组件
    ├── shops.js        # 店铺管理组件
    ├── logs.js         # 日志组件
    └── config.js       # 配置组件
```

## 🎨 技术栈

- **UI 框架**: Bootstrap 5.3
- **图标**: Bootstrap Icons
- **JavaScript**: ES6+ 原生 JS
- **组件通信**: 事件驱动
- **状态管理**: 全局 state 对象

## 🔧 核心组件说明

### 1. 导航栏组件 (Navbar)

**位置**: `index.html` 顶部
**功能**:
- 显示系统状态(在线/离线)
- 快速刷新按钮
- 响应式折叠菜单

```html
<nav class="navbar navbar-expand-lg navbar-dark bg-gradient">
  <!-- 系统状态指示器 -->
  <span class="badge" id="statusBadge">
    <i class="bi bi-circle-fill" id="statusIcon"></i>
    <span id="statusText">运行中</span>
  </span>
</nav>
```

### 2. 侧边栏组件 (Sidebar)

**位置**: `index.html` 左侧
**功能**:
- 页面导航菜单
- 快速链接
- 活动状态指示

```javascript
function switchPage(event, page) {
  // 更新激活状态
  document.querySelectorAll('.sidebar .nav-link').forEach(link => {
    link.classList.remove('active');
  });
  event.currentTarget.classList.add('active');
  
  // 切换页面内容
  loadPageData(page);
}
```

### 3. 统计卡片组件 (Stats Cards)

**功能**: 显示关键指标
**数据绑定**:

```javascript
function updateStatsCards(data) {
  document.getElementById('totalShops').textContent = data.total_shops;
  document.getElementById('todayMessages').textContent = data.today_messages;
  document.getElementById('successRate').textContent = data.success_rate + '%';
  document.getElementById('totalCustomers').textContent = data.total_customers;
}
```

### 4. 消息列表组件 (Message List)

**功能**: 展示最近消息
**模板**:

```javascript
function renderRecentMessages(messages) {
  return messages.map(msg => `
    <div class="message-item">
      <div class="d-flex justify-content-between">
        <span class="fw-bold">${msg.shop_name}</span>
        <span class="badge bg-${msg.push_success ? 'success' : 'danger'}">
          ${msg.push_success ? '成功' : '失败'}
        </span>
      </div>
      <div class="text-muted">${msg.message_content}</div>
    </div>
  `).join('');
}
```

### 5. 店铺表格组件 (Shops Table)

**功能**: 管理店铺信息
**操作**:
- 查看店铺列表
- 配置企微群
- 授权新店铺

### 6. 日志表格组件 (Logs Table)

**功能**: 查看消息历史
**过滤器**:
- 按店铺筛选
- 时间范围
- 分页加载

### 7. 模态框组件 (Modals)

**授权模态框**:
```javascript
function showAuthModal() {
  const modal = new bootstrap.Modal(document.getElementById('authModal'));
  modal.show();
}
```

**Toast 通知**:
```javascript
function showToast(message, type = 'success') {
  const toastEl = document.getElementById('liveToast');
  const toast = new bootstrap.Toast(toastEl);
  // 设置消息和样式
  toast.show();
}
```

## 📊 数据流

```
用户操作 → 事件处理函数 → API 调用 → 更新 state → 重新渲染组件
```

### 示例: 加载店铺列表

```javascript
// 1. 用户点击"店铺管理"
switchPage(event, 'shops')

// 2. 触发数据加载
async function loadShops() {
  const response = await fetch(`${API_BASE}/admin/shops`);
  const data = await response.json();
  
  // 3. 更新全局状态
  state.shops = data.data;
  
  // 4. 渲染组件
  renderShopsList(data.data);
}

// 5. 渲染 HTML
function renderShopsList(shops) {
  container.innerHTML = shops.map(shop => `
    <tr>
      <td>${shop.shop_name}</td>
      <td>${shop.shop_id}</td>
      ...
    </tr>
  `).join('');
}
```

## 🎯 组件化最佳实践

### 1. 职责单一原则

每个函数只做一件事:
```javascript
// ✅ 好: 职责清晰
async function fetchShops() {
  return await fetch('/api/shops').then(r => r.json());
}

function renderShops(shops) {
  return shops.map(shop => createShopCard(shop));
}

// ❌ 差: 职责混杂
async function loadAndRenderShops() {
  const data = await fetch('/api/shops').then(r => r.json());
  document.getElementById('list').innerHTML = data.map(...).join('');
}
```

### 2. 可复用组件

```javascript
// 通用徽章组件
function createBadge(text, variant = 'primary') {
  return `<span class="badge bg-${variant}">${text}</span>`;
}

// 使用
const successBadge = createBadge('成功', 'success');
const errorBadge = createBadge('失败', 'danger');
```

### 3. 事件委托

```javascript
// ✅ 好: 事件委托
document.getElementById('shopsList').addEventListener('click', (e) => {
  if (e.target.matches('.btn-config')) {
    const shopId = e.target.dataset.shopId;
    configShop(shopId);
  }
});

// ❌ 差: 为每个按钮绑定事件
shops.forEach(shop => {
  document.querySelector(`#btn-${shop.id}`).addEventListener('click', ...);
});
```

### 4. 数据与视图分离

```javascript
// 数据层
class ShopStore {
  constructor() {
    this.shops = [];
  }
  
  async fetchShops() {
    const response = await fetch('/api/shops');
    this.shops = await response.json();
    return this.shops;
  }
}

// 视图层
class ShopView {
  render(shops) {
    return shops.map(shop => this.renderShopCard(shop));
  }
  
  renderShopCard(shop) {
    return `<div class="card">...</div>`;
  }
}
```

## 🔄 进一步组件化方案

### 方案 1: Web Components (推荐)

```javascript
// 自定义店铺卡片组件
class ShopCard extends HTMLElement {
  connectedCallback() {
    const shop = JSON.parse(this.getAttribute('data-shop'));
    this.innerHTML = `
      <div class="card">
        <div class="card-body">
          <h5>${shop.shop_name}</h5>
          <p>${shop.shop_id}</p>
          <button class="btn btn-primary">配置</button>
        </div>
      </div>
    `;
  }
}

customElements.define('shop-card', ShopCard);
```

使用:
```html
<shop-card data-shop='{"shop_name":"美容店","shop_id":"001"}'></shop-card>
```

### 方案 2: 模板引擎

使用轻量级模板引擎如 `lit-html`:

```javascript
import { html, render } from 'lit-html';

const shopCard = (shop) => html`
  <div class="card">
    <div class="card-body">
      <h5>${shop.shop_name}</h5>
      <p>${shop.shop_id}</p>
    </div>
  </div>
`;

render(shopCard(shop), document.getElementById('container'));
```

### 方案 3: Vue.js / React (重型方案)

如需更复杂的状态管理和组件交互,可考虑引入框架。

## 📱 响应式设计

Bootstrap 5 提供的响应式工具类:

```html
<!-- 移动端隐藏,桌面端显示 -->
<div class="d-none d-md-block">桌面端内容</div>

<!-- 移动端显示,桌面端隐藏 -->
<div class="d-md-none">移动端内容</div>

<!-- 响应式列布局 -->
<div class="col-12 col-md-6 col-lg-4">自适应</div>
```

## 🎨 主题定制

在 `style.css` 中覆盖 Bootstrap 变量:

```css
:root {
  --bs-primary: #667eea;
  --bs-success: #22c55e;
  --bs-danger: #ef4444;
}

/* 自定义渐变背景 */
.bg-gradient {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
```

## 🔌 API 集成

所有 API 调用统一使用 `fetch` 并加入错误处理:

```javascript
async function apiRequest(url, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${url}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    });
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error('API 请求失败:', error);
    showToast('操作失败: ' + error.message, 'danger');
    throw error;
  }
}

// 使用
const shops = await apiRequest('/admin/shops');
```

## 📝 后续优化建议

1. **引入 TypeScript** - 类型安全
2. **使用构建工具** - Vite/Webpack 打包
3. **代码分割** - 按需加载组件
4. **状态管理** - Zustand/Pinia 轻量方案
5. **单元测试** - Jest/Vitest 测试覆盖
6. **PWA 支持** - 离线访问能力

## 🎯 当前架构优势

✅ **轻量级** - 无需构建,直接运行  
✅ **易维护** - 结构清晰,便于理解  
✅ **快速开发** - Bootstrap 提供现成组件  
✅ **响应式** - 自适应各种屏幕尺寸  
✅ **易扩展** - 模块化设计,便于添加功能
