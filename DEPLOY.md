# 服务器部署指南

> **本文是「裸机从头装一遍」的完整说明**（装 Docker、配 nginx、首次上线）。
> 日常**更新代码**不要看这里，看 **`操作手册.md` 第 7 章**：
> 本地 `python tools/release.py` 打包 → `scp` 上传 → 服务器 `bash tools/remote-deploy.sh` 解压重建。
> 这样服务器**完全不需要访问 GitHub**（国内直连很慢）。
> 中继（把消息真正发进微信群的程序）见 **`操作手册.md` 第 8 章**。
>
> 注：本文早期版本把项目目录写成 `/opt/dylk-wecom-sync`，实际部署目录是
> **`/opt/beauty-notification-service`**（`deploy.sh` 会 clone 到这里）。
> 拿不准时用 `docker inspect dylk-admin --format '{{ range .Mounts }}{{ .Source }}{{ "\n" }}{{ end }}'` 确认。

目标服务器：**Ubuntu 24.04（公网 IP 47.103.32.12，已装全局 nginx）**

最终架构：

```
浏览器
  │  https://notification.hongquanquan.cn
  ▼
全局 nginx (宿主机)
  ├── /          → 直接托管静态前端  /opt/dylk-wecom-sync/web/index.html
  └── /api/*     → 反代 127.0.0.1:8787 (Docker 容器 dylk-admin: web_admin.py)
                        │
                        ├── SQLite 订单库/日志  data/admin.db
                        ├── 来客开放平台 API (IP 白名单: 47.103.32.12 ✔)
                        └── 企业微信 API (内部群 webhook / 外部客户群企业群发)
```

## 一、上传代码

```bash
# 本地执行
scp -r dylk-wecom-sync root@47.103.32.12:/opt/
```

## 二、启动后端容器（Docker）

**一键方式（推荐）**：服务器上进入项目目录，执行 `sudo bash deploy.sh`——自动完成装 Docker、生成并保存 ADMIN_TOKEN、构建启动容器、写 nginx 配置、reload、自检；需要 HTTPS 时用 `HTTPS=1 sudo bash deploy.sh`。

手动方式（等价步骤）：

```bash
# 0. 服务器装 Docker (如未装)
curl -fsSL https://get.docker.com | bash

# 1. 构建并启动(ADMIN_TOKEN 必填, 先生成强随机令牌)
cd /opt/dylk-wecom-sync
openssl rand -hex 24          # 记下输出, 作为页面访问令牌
export ADMIN_TOKEN=<刚才的令牌>
docker compose up -d --build

# 2. 验证
curl -s http://127.0.0.1:8787/api/health
docker compose logs -f        # 看日志, Ctrl+C 退出
```

说明：
- 容器端口只绑定 `127.0.0.1:8787`，公网访问一律走 nginx，不直接暴露
- `config.json` / `data/` / `state/` / `logs/` 都是挂载卷：改配置后 `docker compose restart` 即生效，数据不丢
- 去重状态在 `state/`（按商户 `state_<account_id>.json` 分文件）
- 可选的订单自动拉取常驻服务：`docker compose --profile sync up -d`（每 30 分钟拉单推送）

## 三、nginx 配置（全局 nginx，静态前端 + /api 反代）

创建 `/etc/nginx/sites-available/notification.hongquanquan.cn`：

```nginx
server {
    listen 80;
    server_name notification.hongquanquan.cn;

    # 静态前端(直接托管, 不需要任何后端参与)
    root /opt/dylk-wecom-sync/web;
    index index.html;

    # 后端 API 反代到 Docker 容器
    location /api/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/notification.hongquanquan.cn /etc/nginx/sites-enabled/
sudo nginx -t && sudo nginx -s reload

# HTTPS(全局 nginx 用 apt 装 certbot)
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d notification.hongquanquan.cn   # 自动改配置加 443 和证书续期
```

完成后浏览器打开 `https://notification.hongquanquan.cn`，页面会要求输入访问令牌（即上面 `export` 的 `ADMIN_TOKEN`）。

## 四、部署后自检

```bash
# 1. 确认服务器出口 IP(应输出 47.103.32.12, 即来客白名单里的 IP)
curl -s ifconfig.me

# 2. 后端健康
curl -s http://127.0.0.1:8787/api/health

# 3. 拉单预览: 白名单生效后应返回 ok:true 而非 2119013
curl -s "http://127.0.0.1:8787/api/orders/preview?merchant=超英皮肤定制管理"

# 4. 页面自检
curl -s -o /dev/null -w "%{http_code}\n" https://notification.hongquanquan.cn
```

## 五、⚠️ 来客开放平台 IP 白名单

订单接口会校验调用方 IP：**`2119013 IP不在白名单，请开通权限`**。

- 本项目服务器出口公网 IP：**47.103.32.12**（已加入白名单 ✔）
- 本地开发机 IP 不在白名单，本地拉单报 2119013 属正常，部署到服务器后即消失
- token 失效无需人工干预：代码已做内存缓存（提前 5 分钟刷新）+ 请求失败自动强制重取并重试一次

## 六、企业微信配置（外部客户群推送）

**先澄清两条通道的区别**（群里能不能收到，取决于走哪条）：

| 通道 | 配置项 | 适用 | 说明 |
|------|--------|------|------|
| 群机器人 Webhook | `wecom.webhook_url` | 仅**内部群** | 外部客户群加不了机器人，客户群不要用它 |
| 客户联系 → 企业群发 API | `wecom.corpid` + `secret` + `chat_id_list` | **外部客户群** ✔ | 应用创建群发任务，群主手机端确认后发出 |

获取位置：

1. **企业 ID（corpid）**：管理后台 https://work.weixin.qq.com →「我的企业」→ 企业信息 → 底部「企业ID」
   → 本项目已填：`ww9f53651f397a9958`（AgentId `1000002` 已填入 `wecom.agentid`）
2. **应用 Secret / AgentId**：管理后台 →「应用管理」→「自建」→ 点开自建应用 →「查看 Secret」→ Secret 发送到企业微信客户端查看
   → **当前唯一待填项**：拿到后填入 `config.json` 的 `wecom.secret`（或页面上保存），然后 `docker compose restart`
3. **客户联系权限**：管理后台 →「客户联系」→「API」→ 用同一个自建应用勾选权限（否则查不到客户群、建不了群发）
4. 配好后页面该商户下点「查客户群」验证（能列出 chat_id 即通）

平台硬限制（官方规则）：客户群每天默认只收 1 条群发；API 创建的任务需群主在「群发助手」确认发送。

## 七、安全要点

- **务必设置 ADMIN_TOKEN**：后台可改配置、触发推送
- `chmod 600 config.json`（含真实密钥）；勿提交公开仓库
- Nginx 层可再加管理端 IP 白名单（`allow 你的IP; deny all;`）
- 日志：容器 `logs/web_admin.log`（挂载到宿主机）+ SQLite `data/admin.db`（页面「运行日志」页签可查）

## 八、目录结构

```
dylk-wecom-sync/
├── sync.py                  # 核心逻辑(拉单/解密/构建消息/推送/去重)
├── web_admin.py             # 后端 API 服务(容器内运行)
├── storage.py               # SQLite 存储(订单库/运行日志)
├── web/index.html           # 静态前端(nginx 直接托管)
├── config.json              # 配置(挂载卷, 改完 docker compose restart)
├── Dockerfile               # 后端镜像
├── docker-compose.yml       # 编排(admin 常驻 + 可选 sync 定时拉单)
├── requirements.txt
├── dylk-wecom-sync.service  # (备用)裸机 systemd 方式, 不用 Docker 时才需要
├── data/                    # 挂载卷: admin.db / incoming / processed
├── state/                   # 挂载卷: 去重状态 state_<account_id>.json
└── logs/                    # 挂载卷: web_admin.log
```

## 九、常用命令速查

| 命令 | 作用 |
|------|------|
| `docker compose up -d --build` | 启动/更新后端 |
| `docker compose restart` | 改完 config.json 后重启生效 |
| `docker compose logs -f` | 看后端日志 |
| `docker compose --profile sync up -d` | 额外启动定时拉单服务 |
| `docker compose down` | 停止 |
| `docker compose run --rm dylk-admin python sync.py --file sample_orders.csv --dry-run` | 容器内 dry-run 测试 |
