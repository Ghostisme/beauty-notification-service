# notification.hongquanquan.cn：旧 Node.js 服务切换到来客通知工具

当前情况：域名已有 DNS、HTTP/HTTPS 配置；旧工具由 PM2 管理，可能使用 MySQL 保存留资及日志。本流程继续用 PM2 管理新工具的 Python 进程，复用现有站点与证书。

2026-10-12 经阿里 DNS、Google DNS 分别查询，该域名 A 记录均为 `47.103.32.12`。本机网络的外部 HTTPS 探测未成功完成 TLS 握手，不能据此确认当前线上证书和页面已通过验收；切换前后都要执行本文的 HTTPS 检查。本次交付迁移配置，尚未登录服务器执行切换。

## 1. 这次调整的范围

| 项目 | 操作 |
| --- | --- |
| 网站入口 | 继续使用 `https://notification.hongquanquan.cn` |
| DNS、证书、续期、80 跳转到 443 | 复用现有配置 |
| 新程序 | 当前仓库 `feature/laike-wecom-tool` 分支下的 `laike-wecom-tool/` |
| 新部署目录 | `/opt/beauty-notification-service-laike/laike-wecom-tool`，与旧目录分开 |
| 新 PM2 进程 | `laike-wecom-tool`，单个 Python 进程，监听 `127.0.0.1:8790` |
| 新数据库 | 新目录自己的 `data/tool.db`，SQLite，配套 `data/.master-key` |
| 旧 Node.js、旧 MySQL | 先保留。确认留资接收方和发送任务后，只停已确认需要替换的旧进程 |
| Windows 发送端 | 将服务器地址切换为该 HTTPS 域名，保留令牌、校准和本机账本 |

新工具使用相对 API 地址，不需要为了域名重新编译前端。PM2 可以指定 Python 解释器；此配置固定一个实例，不使用 Node.js 集群模式。[PM2 官方应用配置](https://pm2.keymetrics.io/docs/usage/application-declaration/)。

**不要运行仓库根目录的旧部署脚本来替换网站。** 新分支已在该入口增加提示并退出，防止进入旧流程的 PM2 全量清理与网站配置覆盖。

以下服务器命令以原 PM2 服务所属账户为准；示例文件上传路径以 root 为例。若原服务在另一账户下，PM2 操作也应使用该账户，部署目录和数据应归该账户。不要把 root 的空 PM2 列表当成旧进程已经停止。

## 2. 先在阿里云终端查清旧服务

这一组只读取信息：

```bash
whoami
cat /etc/os-release
uname -m
free -m
node --version
pm2 --version
pm2 ls
python3 --version
command -v python3.12 || true
sudo ss -lntp
sudo systemctl is-active mysql mariadb mysqld || true
sudo nginx -t
```

从 `pm2 ls` 记录旧通知工具的进程 ID、进程名。`ss` 用来核对旧 Node.js 的监听端口、新程序的 8790 是否空闲以及 MySQL 监听状态。若 Nginx 命令不存在，先定位实际使用的 Nginx/OpenResty 或网站面板，不安装第二套代理抢占 80/443。

查出当前域名使用的 Nginx 配置文件：

```bash
sudo nginx -T 2>/dev/null | awk '
    /^# configuration file / {source=$0}
    /^[[:space:]]*server_name[[:space:]]/ && /notification\.hongquanquan\.cn/ {
        print source
        print $0
    }
'
```

在服务器编辑器中查看命中的文件，记录实际的 HTTPS `server` 块、旧 `proxy_pass`、旧静态文件 `root` 和 `location /api/`。配置中若有其他域名，只编辑本域名对应的块。保留证书路径、ACME 验证路径、续期配置及其他站点。

检查当前 HTTPS：

```bash
curl --fail --show-error --head --connect-timeout 5 --max-time 15 https://notification.hongquanquan.cn/
```

如 TLS 握手、域名证书校验或站点访问失败，先核对当前 443 监听和证书配置；不要用关闭证书校验来作为验收通过。

**确认旧留资入口后再切代理。** 查清旧 Node.js 是否仍接收抖音留资回调、表单请求或定时导入。如果仍有上游调用，应保留已确认的旧回调路径到旧 Node.js 端口，或完成上游对新接口的映射后再切换。新工具接入口为 `POST /api/ingest`，使用独立 Bearer 令牌和本工具的数据格式，详见 [接入说明](接入说明.md)。旧 `/api/...` 路径与新 API 冲突时需先解决映射。

## 3. 备份旧网站和数据库

在修改前，保留旧代码、PM2 进程信息及该域名实际配置文件的副本。以下两个变量需填入上一步查明的真实值，再执行；脚本会检查文件存在。

```bash
LAIKE_SITE_FILE='/实际的/该域名站点配置文件'
LAIKE_OLD_PM2_ID='实际旧通知工具的进程ID'
test -f "$LAIKE_SITE_FILE" && pm2 describe "$LAIKE_OLD_PM2_ID" >/dev/null && {
    LAIKE_SITE_FILE="$(readlink -f -- "$LAIKE_SITE_FILE")"
    mkdir -p -m 700 -- "$HOME/laike-site-backups"
    LAIKE_SITE_BACKUP="$HOME/laike-site-backups/notification-$(date +%Y%m%d-%H%M%S).conf"
    cp -p -- "$LAIKE_SITE_FILE" "$LAIKE_SITE_BACKUP"
    printf '站点备份：%s\n旧工具 PM2 ID：%s\n' "$LAIKE_SITE_BACKUP" "$LAIKE_OLD_PM2_ID"
}
```

命令会解析站点文件的软链目标，将副本放到当前账户主目录下的 `laike-site-backups`，避开 Nginx 加载站点的目录。记录备份的实际路径，后续回退会用到。

MySQL 留资和日志使用现有数据库备份方式保存，例如阿里云 RDS 备份或已配置的库备份任务。先确认数据库名称和现有备份，不运行删除库、清表、覆盖全库或停止 MySQL 的命令。

**旧 MySQL 数据不会因为换域名代理自动进入新后台。** 本次迁移的是当前已跑通工具自己的 SQLite 数据。旧留资和日志导入需要先核对旧表结构、门店关联、时间、稳定唯一 ID 及历史发送记录；历史留资默认作为历史数据保存，不能未经核对就变成新通知。

## 4. 在独立目录准备新程序

```bash
git clone --branch feature/laike-wecom-tool --single-branch https://github.com/Ghostisme/beauty-notification-service.git /opt/beauty-notification-service-laike
```

目标目录已存在时，先确认是否已部署过本工具，不覆盖或删除该目录。进入新程序目录：

```bash
cd /opt/beauty-notification-service-laike/laike-wecom-tool
```

服务器需要 Python 3.12、venv、现有 Node.js/PM2 和 curl。对于 **Ubuntu 24.04**，可安装：

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv curl
```

其他系统先依据第 2 步结果使用对应系统的软件包；不在 Alibaba Cloud Linux/CentOS 上套用 apt 命令。Python 3.12 已存在时无需重复安装。旧 Node.js 和 PM2 继续保留，无需安装网站的 npm 依赖。

## 5. 将本机真实配置迁移到服务器

在本机后台 `http://127.0.0.1:8790`：关闭自动同步、关闭自动发送，等待任务完成；确认没有“发送中”或“等待回执”的任务。停止本项目的 Windows 发送端，保留管理员现用密码。

在当前 Windows 项目目录备份：

```powershell
Set-Location 'D:\github_code\余乐圈美业项目资料\beauty-notification-service-laike-tool\laike-wecom-tool'
.\.venv\Scripts\python.exe -X utf8 manage.py backup
$laikeBackup = Get-ChildItem -LiteralPath '.\data\backups' -Filter 'laike-*.zip' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $laikeBackup) { throw '没有找到迁移备份' }
$laikeBackup.FullName
```

将显示的 ZIP 文件通过现有文件上传方式传到服务器 `/root/laike-migrate.zip`。备份包含配对的 `tool.db` 和 `.master-key`，含实际应用凭证和客户数据，不上传 GitHub。当前 Windows 的 `sender-config.json`、`sender-data` 全部保留。

在服务器的新程序目录恢复。此操作只允许一个尚未初始化的数据目录，已有库时会退出：

```bash
cd /opt/beauty-notification-service-laike/laike-wecom-tool
chmod 600 /root/laike-migrate.zip
python3.12 - <<'PY'
import os
import zipfile
from pathlib import Path

data = Path('data')
expected = {'tool.db', '.master-key'}
if any((data / name).exists() for name in expected):
    raise SystemExit('新目录已有数据库或密钥，请先确认原实例，不能覆盖恢复。')
with zipfile.ZipFile('/root/laike-migrate.zip') as archive:
    if set(archive.namelist()) != expected or len(archive.namelist()) != 2:
        raise SystemExit('迁移包必须恰好包含 tool.db 与 .master-key。')
    if archive.testzip():
        raise SystemExit('迁移包完整性检查失败。')
    data.mkdir(mode=0o700, exist_ok=True)
    for name in sorted(expected):
        with os.fdopen(os.open(data / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
            output.write(archive.read(name))
print('已恢复配对数据库与密钥。')
PY
```

迁移保留商户、门店、模板、同步位置、通知记录、管理员密码和发送端令牌。现有管理员密码不会重置；备份不包含 `.bootstrap-password` 文本文件。

## 6. 用 PM2 启动新工具，先不切网站

在新程序目录，以原 PM2 服务账户执行：

```bash
bash deploy/install-pm2.sh
pm2 ls
curl --fail --show-error http://127.0.0.1:8790/health
```

安装入口会检查迁移数据是否成对、自动任务是否暂停、是否有未完成发送任务及端口占用；然后创建独立 Python 环境、安装锁定依赖、检查数据库、只创建 `laike-wecom-tool` 进程。健康检查通过后执行 `pm2 save`。

预期 `/health` 返回包含 `"status":"ok"` 和 `"version":"1.0.0"` 的 JSON。旧 Node.js 仍在原端口运行，新程序只监听服务器回环地址的 8790。此时新工具仍保持自动同步、自动发送关闭。

新 PM2 配置使用 `max_memory_restart: '384M'`，其作用是超过阈值后重启，**不等同于 systemd/Docker 的硬内存上限，也未设置 CPU 硬配额**。使用单个实例、四个请求线程；1 核/2 GiB 机器需要同时观察旧服务、MySQL 和系统的总内存。现有 MySQL 占用较高时，先完成旧服务梳理后再持续运行新任务。

确认原来的 PM2 开机恢复服务仍有效：

```bash
systemctl list-unit-files 'pm2-*'
```

没有现有 PM2 开机恢复服务时，由 PM2 账户执行 `pm2 startup` 并按其输出完成系统服务安装，最后 `pm2 save`。不要再为同一个程序安装 Docker 或 `laike-tool.service`，避免重复运行。

## 7. 修改现有 HTTPS 站点的代理

在第 2 步查明的 `notification.hongquanquan.cn` HTTPS `server` 块中，将原应用路由替换为 [现有站点代理片段](../deploy/nginx-existing-site.location.conf)：

```nginx
location / {
    client_max_body_size 2m;
    proxy_pass http://127.0.0.1:8790;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 5s;
    proxy_send_timeout 35s;
    proxy_read_timeout 35s;
}
```

新工具同时提供页面、静态资源和 API，全部应用路由都需转到 8790。旧 `location /api/`、旧前端 `try_files` 或静态资源正则 `location` 可能优先匹配，不能只增加一个新的 `/` 代理就认为完成。按第 2 步保留确认仍需使用的旧留资回调路径；其他旧应用路由一并替换。

保留原 `listen 443 ssl`、证书路径、证书续期和 HTTP 到 HTTPS 跳转。域名已有站点时不再新增第二个同名站点，不执行重新申请证书的命令。代理行为依据：[Nginx 官方 proxy_pass / proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)。

仅在配置检查通过后重载：

```bash
sudo nginx -t && sudo systemctl reload nginx
curl --fail --show-error --connect-timeout 5 --max-time 15 https://notification.hongquanquan.cn/health
curl --fail --show-error --head --connect-timeout 5 --max-time 15 https://notification.hongquanquan.cn/
```

通过标准：域名 `/health` 返回新工具的 `status/version`，首页打开“来客门店通知工具”登录页，静态资源正常，使用迁移前的管理员密码能登录并操作。浏览器若仍显示旧页面，先强制刷新并核对是否存在旧缓存或 Service Worker；不要把旧 HTML 的 200 状态当成新工具已上线。

## 8. 连接抖音与 Windows 发送端

在抖音应用服务器 IP 白名单中确认云端实际出口 IP。DNS 指向的 `47.103.32.12` 与云端出口可能相同，但应以服务器实际请求出口为准。在云端后台“接入设置”验证应用凭证与商户订单权限；若返回 `2119013`，先核对该云端出口白名单。

先确认本项目旧 Windows 发送端已停止。在 Windows 的同一项目目录，仅修改服务器地址：

```powershell
$laikeConfigPath = Join-Path (Get-Location) 'sender-config.json'
$laikeConfig = Get-Content -LiteralPath $laikeConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$laikeConfig.server = 'https://notification.hongquanquan.cn'
[System.IO.File]::WriteAllText(
    $laikeConfigPath,
    ($laikeConfig | ConvertTo-Json -Depth 10),
    [System.Text.UTF8Encoding]::new($false)
)
Start-Sleep -Seconds 4
.\.sender-venv\Scripts\python.exe -X utf8 sender.py --check --test-only
```

通过标准为 `server_connected: true`，企微窗口可交互时 `ready: true`。数据库迁移会保留原发送端令牌，原校准与账本也继续使用。检查通过后启动：

```powershell
.\.sender-venv\Scripts\python.exe -X utf8 sender.py --test-only
```

当前只连接 `壹心-湖南-测试消息店`。先核对云端门店群绑定、模板和新订单；按 [真实实测流程](部署实测与日常操作全流程.md#10-用真实数据逐项验收) 人工核对待发正文后发送。此前已发送的历史订单不重复发送；之前按截图查询的 14 笔历史订单也不会因域名迁移自动变成补发任务。

## 9. 验收后只停止已确认不再需要的旧进程

满足这些条件后再停旧工具：网站和新后台登录正常、抖音权限正常、Windows 发送端连通、旧留资回调已保留或迁移、旧通知任务的重复发送风险已排除。

```bash
pm2 stop "$LAIKE_OLD_PM2_ID"
pm2 save
pm2 ls
```

`LAIKE_OLD_PM2_ID` 必须是第 3 步记录的旧通知工具 ID，不能填新工具或无关服务。若旧工具还承担留资接收任务，先保留该进程并关闭它的旧通知调度；具体方式取决于旧程序，不使用未确认的参数。MySQL 继续保留，新工具不连接或修改它。

本机后台的自动任务保持关闭，由云端在验收后开启自动同步；自动发送在确认正文和目标群后按需开启。同一套商户只保留一套正式通知调度。

## 10. 备份、日常操作和回退

```bash
cd /opt/beauty-notification-service-laike/laike-wecom-tool
pm2 logs laike-wecom-tool --lines 60 --nostream
.venv/bin/python manage.py check
.venv/bin/python manage.py backup --retain 7
pm2 restart laike-wecom-tool
```

每日备份可在服务账户的 `crontab -e` 中新增一行，不覆盖原有定时任务：

```cron
30 3 * * * cd /opt/beauty-notification-service-laike/laike-wecom-tool && .venv/bin/python manage.py backup --retain 7
```

更新时先暂停本工具的同步和发送，等待任务结束，停止 Windows 发送端并备份；在仓库目录 `git pull --ff-only origin feature/laike-wecom-tool`，进入工具目录安装 `requirements.lock`，执行 `pm2 restart laike-wecom-tool --update-env`。重新核对健康、门店、模板和发送端后恢复任务。保留 `data` 与 Windows 发送端账本。

需要回退时，先关闭新工具任务、停止 Windows 发送端，避免两套同时发送。保留新库备份，停止新 PM2 进程，再恢复实际站点备份：

```bash
pm2 stop laike-wecom-tool
cp -p -- "$LAIKE_SITE_BACKUP" "$LAIKE_SITE_FILE"
sudo nginx -t && sudo systemctl reload nginx
pm2 restart "$LAIKE_OLD_PM2_ID"
pm2 save
```

上述变量应使用第 3 步记录的真实路径和 ID；重新登录终端后需要重新填写。旧代码、旧 MySQL 都保留着。回退后核对留资接收、旧任务开关以及切换期间可能已发送的通知；不用删除新库来回退网站。
