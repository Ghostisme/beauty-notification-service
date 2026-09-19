# 抖音来客订单 → 企业微信群 同步工具

把抖音来客的订单信息推送到企业微信群（内部群走群机器人 Webhook，外部客户群走企业群发 API）。支持**服务商模式**：一个应用服务多个来客商户，逐商户拉单推送，并解密订单中的客户手机号。

## 推送目标

| 目标 | 通道 | 说明 |
|------|------|------|
| 内部群 | 群机器人 Webhook | 简单可靠，无需申请权限 |
| **外部客户群**（含微信用户） | 客户联系·企业群发 API | 群机器人**不支持**外部群，需自建应用 |

`config.json` 中 `wecom.target` 三选一：`internal` / `customer_group` / `both`（两边都发）。每个商户可在 `merchants[].wecom` 单独覆盖。

## 两种数据来源

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `file` | 读取来客后台导出的订单 CSV/Excel | 快速上手，无需申请API权限 |
| `api`  | 服务商模式：client_token + account_id 逐商户拉单 | 全自动，多商户 |

## 快速开始（file 模式，5分钟跑通）

1. 企业微信群里添加机器人：**群设置 → 群机器人 → 添加**，复制 Webhook 地址
2. 打开 `config.json`，把地址填到 `wecom.webhook_url`
3. 从抖音来客后台（订单管理 → 导出）下载订单表格
4. 运行：
   ```bash
   python sync.py --file 你的订单文件.csv          # 真实发送
   python sync.py --file 你的订单文件.csv --dry-run # 先预览不发送
   ```

## 服务商模式（多商户 + API 拉单 + 手机号）

### 前置条件

1. 在 [抖音开放平台服务商平台](https://partner.open-douyin.com) 创建**生活服务商应用**，拿到 `client_key` / `client_secret`
2. 控制台「解决方案」申请行业方案与能力权限（至少包含**订单查询** `life.capacity.order.query`）
3. **商家授权**：每个商户在抖音来客「店铺管理 → 第三方应用授权」授权你的应用；你在服务商平台「授权管理」确认授权关系
4. 拿到每个商户的**来客商户根账户ID（account_id）**

### 配置（config.json）

```jsonc
{
  "mode": "api",
  "douyin": {
    "client_key": "...", "client_secret": "...",
    "phone_decrypt": "local"
  },
  "merchants": [
    { "account_id": "商户1根账户ID", "name": "门店A",
      "wecom": { "webhook_url": "门店A的群Webhook" } },
    { "account_id": "商户2根账户ID", "name": "门店B" }
  ]
}
```

- 订单接口：`GET /goodlife/v1/akte/order/query/`（按 `update_order_start_time/end_time` 增量拉取，`sync.lookback_minutes` 控制时间窗）
- 每个商户独立去重（`state_<account_id>.json`），互不干扰
- 推送时逐商户执行：`python sync.py --api`（全部商户）或 `--merchant 门店A`（指定商户）

### 客户手机号

- 订单接口返回的购买人手机号是 **AES 加密密文**（平台隐私管控），脚本在订单原始结构中递归识别加密字段并解密
- **本地解密**（默认，`phone_decrypt: "local"`）：AES-256-CBC，key = clientSecret 补齐/裁剪至 32 字节（补位字符 `#`，左右交替补齐），IV = key 前 16 字节；需 `pip install pycryptodome`
- **官方接口解密**（`"api"`）：回退调用 `/goodlife/v1/open/common_biz/crypto/decrypt/batch/`；本地解密失败（缺依赖或解密异常）也会自动走此通道
- 手机号解出后填入订单 `phone` 字段，在消息中显示为「手机号」/「📱」（`push.fields` 中含 `phone` 即展示）
- 解密失败不影响订单推送，手机号留空并打印日志
- 合规提醒：手机号属个人敏感信息，仅可用于核销/履约/售后等约定场景，注意个人信息保护义务

### 平台限制

- 接口/字段命名以官方文档为准，脚本已做常见字段兼容映射；若返回结构与预设不符，调整 `sync.py` 的 `map_api_order` / `PHONE_ENCRYPT_KEYS`
- 订单查询接口需申请权限并完成商家授权，未授权商户调用会返回权限错误

## 本地管理后台（Web 页面）

不想改 config.json 的话，用管理后台：页面即可完成「填商户 account_id + 企微配置 → 拉单预览 → 推送」全流程。

```bash
python web_admin.py          # 浏览器打开 http://127.0.0.1:8787
ADMIN_PORT=9000 python web_admin.py   # 自定义端口
```

功能：
- **商户管理**：新增/编辑/删除商户（account_id + 名称 + 各自企微配置，未填项继承全局）；全局来客凭证与推送默认值可配置、可测试
- **订单数据**：拉单/推送时订单自动落库（SQLite，按 商户+订单号 幂等更新），支持按商户/关键词搜索、分页浏览
- **运行日志**：每次操作（拉单预览/推送/配置修改/各类错误）自动记录，手机号脱敏，可按商户/级别/操作筛选，错误含官方 logid 便于向平台反馈追踪
- **拉单预览**：调订单接口 → 解密手机号 → 生成消息模板，只看不发、不写去重状态
- **推送测试 / 推送**：测试模式只打印消息；真实推送走去重后发送
- **查客户群**：列出企微客户群 chat_id 和群名，选中的直接填入该商户配置

安全：
- 仅设置 `ADMIN_TOKEN`（环境变量或 config.json 的 `admin_token`）后，所有 API 需携带令牌，页面会提示输入；公网部署时**必须**设置
- 服务器部署（nginx + systemd，配合已解析域名）见 `DEPLOY.md`
- 注意：来客订单接口要求 **IP 白名单**，需在开放平台控制台添加服务器出口 IP，否则报 `2119013`

链路：`抖音来客拉单 → 手机号解密 → 消息模板 → 企微内部群/外部客户群推送`。

安全说明：服务仅监听 `127.0.0.1`（本机访问）；config.json 中含密钥，不要提交到公开仓库；也可用环境变量 `DOUYIN_CLIENT_KEY` / `DOUYIN_CLIENT_SECRET` 覆盖来客凭证（优先级高于配置文件）。

## 推送外部客户群（企业群发）

> 背景：企业微信**外部群（客户群）不支持添加群机器人**，Webhook 走不通。
> 官方合规路径是「客户联系 → 企业群发」API，需要自建应用。

### 配置步骤

1. 企业微信管理后台 → **应用管理 → 自建应用 → 创建应用**，记下 `Secret`；「我的企业 → 企业信息」复制 **企业ID（corpid）**
2. 应用详情页确认应用有**客户联系**权限，且**应用可见范围**包含目标客户群的群主
3. 把 `corpid`、`secret` 填入 `config.json`（全局 `wecom` 或商户级 `merchants[].wecom`），`target` 改为 `customer_group`（或 `both` 同时推内部群）
4. 查询客户群 ID 并填入 `chat_id_list`：
   ```bash
   python sync.py --list-groups                  # 默认商户
   python sync.py --list-groups --merchant 门店A  # 指定商户
   ```
5. 试运行：`python sync.py --api --dry-run`

### 平台硬限制（代码无法绕过，务必知晓）

| 限制 | 说明 |
|------|------|
| **需成员确认** | API 只是创建群发任务，群主会在手机端「群发助手」收到待办，**手动点击发送**后才真正发到客户群 |
| **频次限制** | 每个客户群每天默认只能接收 1 条群发（管理员可在群发助手调整规则：每天1条/每周7条/每月天数） |
| **不支持 Markdown/@** | 群发消息为纯文本，脚本会自动把 Markdown 转为纯文本，@提醒在客户群不生效 |
| **消息条数** | 受频次限制，客户群建议用汇总模式（`push.per_order: false`），每天最多发一条 |

## 常用参数

| 参数 | 作用 |
|------|------|
| `--file <路径>` | 指定订单 CSV/Excel 文件 |
| `--api` | 强制 API 模式（逐商户拉单） |
| `--dry-run` | 只打印消息内容，不发送（测试用） |
| `--all` | 忽略去重记录，全部重新推送 |
| `--serve` | 常驻服务模式（定时执行） |
| `--merchant <name/序号>` | 多商户时指定商户 |
| `--list-groups` | 列出企业微信客户群（chat_id/群名） |

## 配置说明（config.json）

- `merchants[]`：多商户列表，每项 `account_id` + `name`，可覆盖 `wecom`/`push`；未配 `merchants` 时兼容旧的单商户配置（`douyin.account_id`）
- `douyin.phone_decrypt`：手机号解密策略 `local` / `api` / `off`
- `push.fields`：消息里展示哪些字段（订单号/商品/金额/状态/客户/**手机号**/时间/门店）
- `push.per_order`：`true` 每笔订单单独一条消息（实时感强）；`false` 汇总成一条（推荐订单多时）
- `sync.lookback_minutes`：API 模式每次拉取最近 N 分钟的订单
- 去重记录按商户分文件存储，同一订单不会重复推送

## 注意事项

- 企业微信机器人限频 **每分钟 20 条**，脚本已内置间隔，订单量大建议用汇总模式
- 导出表格的列名如果和预设不一致（如"实付金额"写成了"支付额"），把新列名加进 `sync.py` 顶部的 `COLUMN_ALIASES` 即可
- API 模式的接口字段以来客开放平台文档为准，脚本已做常见字段名的兼容映射
