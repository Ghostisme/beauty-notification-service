# 来客门店通知工具

将多家企业的抖音来客订单、独立留资和启用的状态变化，转换为统一消息，并按企业与门店分发到对应企微外部群。提供中文小后台查看运行情况、编辑模板、补发、重新分配门店和人工确认结果。

这个项目是独立程序，使用自己的 `data/tool.db`，不需要连接或修改其他业务数据库。

## 实际运行方式

```text
抖音生活服务开放平台 ──按企业定时查询订单──┐
独立留资来源 ──接入接口 / 后台录入────────┤
                                      ▼
                     阿里云 Linux 服务器：1 核 / 2 GiB
                 自动任务 → 事件去重 → 门店路由 → 持久队列
                                      │
                  中文监控后台 ← 状态、错误、回执、人工操作
                                      │ HTTPS 拉取任务 / 上报回执
                                      ▼
                       常开 Windows 电脑 + 已登录企业微信
                 搜索完整群名 → 核对群标题 → 发送 → 核对群内消息
                                      ▼
                         各门店企微外部群
```

云端使用 Python、Flask、Waitress 和 SQLite，单进程运行，不额外部署 MySQL、Redis 或前端构建服务。Docker 与 systemd 两种部署方式均将服务内存上限设为 384 MiB、CPU 上限设为 0.8 核；这是一项部署限制，并非阿里云实机压测结果。Windows 发送端与 OCR 模型运行在另一台电脑上。

**企微外部群发送采用 Windows 客户端界面自动化。** 官方“创建企业群发”要求成员确认，不适合逐订单无人值守发送。本程序因此提供了自己的桌面发送端，并保留已有工具的 HTTP 接口。桌面发送端需要一个已加入目标群的企微账号、已登录且未锁定的 Windows 桌面、固定窗口尺寸和一次界面校准。它不能作为 Linux 服务器里的纯接口直接运行。依据：[企业微信创建企业群发](https://developer.work.weixin.qq.com/document/path/92135)。

## 已有功能

| 模块 | 行为 |
| --- | --- |
| 企业与门店 | 多企业、多门店；按 `account_id + poi_id` 匹配，群名称及逻辑群 ID 均需唯一 |
| 订单同步 | 官方商户订单查询、访问令牌更新、游标分页、各企业独立同步位置、失败后重试 |
| 新订单通知 | 默认支付成功后通知；也可改为创建后通知；同一次支付不会重复触发两种通知 |
| 新留资通知 | 独立留资接入接口、后台录入；不会将预约订单直接当成留资 |
| 状态通知 | 支付成功、核销／履约、退款申请、退款成功、取消，按需勾选 |
| 消息模板 | 三类模板分别启停；插入变量、预览、字段缺失时隐藏该行或显示“未提供” |
| 自动任务 | 自动同步、自动发送分别控制；默认均暂停；可以手动同步一轮 |
| 专用测试群 | `壹心-湖南-测试消息店`；独立测试配置、三类模拟通知、发送端仅领取测试群任务 |
| 发送追踪 | 待发送、发送中、等待回执、成功、失败、待核实、待分配等状态及每次尝试记录 |
| 人工处理 | 编辑尚未发出的正文、仅在本企业内重新分配门店、补发、取消、人工确认已发送 |
| 防止重复 | 业务事件去重、发送租约、本机发送账本；不明结果不会自动重发 |
| 数据维护 | 在线一致性备份，连同加密密钥备份；按保留天数清理终态正文，永久保留不含客户资料的去重键 |
| 后台保护 | 密码散列、登录限速、会话校验、写操作校验、接入令牌分开、应用密钥加密保存 |

## 在 Windows 本机正式运行

安装 Python 3.12 后，双击 `start-server.bat`，或在本目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe run.py
```

打开 <http://127.0.0.1:8790>，账号为 `admin`，首次密码保存在 `data/.bootstrap-password`。右上角显示“正式环境”，使用独立 `data/tool.db`，不会导入示例订单或示例发送成功记录。本机真实联调暂时无需域名。

“接入设置 → 真实接入检查”分别显示应用凭证、各商家订单查询、门店群绑定、独立留资来源、发送端连接和实际业务发送结果。保存凭证后可直接验证真实接口；错误会显示抖音返回的错误码及处理提示。真实账号的逐步操作见 [本机真实接入](docs/真实接入操作.md)。

`start-demo.bat` 是另一个可选的离线演示入口，只使用 `demo-data` 中的合成数据，不执行真实查询和发送。真实接入使用上述正式入口。

## 企微发送端

在常开 Windows 电脑上安装 Python 3.12 和企业微信，登录发送账号，然后双击 `start-sender.bat`。该入口依次安装依赖、填写服务器地址及发送端令牌、校准界面并启动。

也可以分步运行：

```powershell
python -m venv .sender-venv
.\.sender-venv\Scripts\python.exe -m pip install -r requirements-sender.lock
.\.sender-venv\Scripts\python.exe sender.py --configure
.\.sender-venv\Scripts\python.exe sender.py --calibrate
.\.sender-venv\Scripts\python.exe sender.py --check
.\.sender-venv\Scripts\python.exe sender.py
```

后台“接入设置”可以查看发送端令牌。远程连接要求 HTTPS。本地配置保存在 `sender-config.json`；发送账本、校准文件及滚动日志在 `sender-data`。详细操作见 [Windows 发送端说明](docs/Windows发送端.md)。

测试群专用入口 `start-test-sender.bat` 只匹配 `壹心-湖南-测试消息店`，也支持绑定了该群的真实测试门店。发送端使用完整群名检索，核对群标题后粘贴文本。默认模板保留订单编号／留资编号与业务时间，便于发送后确认；删除业务编号会导致桌面发送端停止这条任务。客户端或界面变化、OCR 无法完整确认时，结果进入人工核实。**桌面确认代表在当前客户端目标群窗口识别到消息，不代表取得了腾讯服务端的送达回执。**

## 部署到阿里云

支持 Docker Compose 和 systemd，二选一。逐步说明、HTTPS 反向代理、备份恢复和日常维护见 [阿里云部署说明](docs/阿里云部署.md)。

从当前本机真实实例迁移到云端，并完成真实订单验收、资源实测和日常操作，按 [部署、实测与日常操作全流程](docs/部署实测与日常操作全流程.md) 顺序执行。该流程采用 Ubuntu 24.04 / Docker Compose，包含保留现有数据库与 Windows 账本的迁移步骤。

本工具位于 `Ghostisme/beauty-notification-service` 仓库的 `feature/laike-wecom-tool` 分支、`laike-wecom-tool/` 子目录。从 GitHub 拉取并部署时，按 [GitHub 分支部署说明](docs/GitHub分支部署.md) 使用对应目录；下面的 `/opt/laike-wecom-tool` 是独立程序包的部署路径。

使用 `notify.你的域名` 作为后台入口时，按 [子域名启动说明](docs/子域名启动说明.md) 配置 DNS、启动服务和 HTTPS 反向代理。

Docker 主要步骤：

```bash
cd /opt/laike-wecom-tool
mkdir -p data
sudo chown 10001:10001 data
sudo chmod 700 data
docker compose up -d --build
sudo cat data/.bootstrap-password
```

程序仅绑定服务器回环地址 `127.0.0.1:8790`，前面使用 Nginx 配置 HTTPS。附带的 `deploy/nginx.conf.example` 需要替换域名和证书路径。Compose 默认启用安全 Cookie，浏览器应通过 HTTPS 域名访问后台。

## 首次真实接入顺序

已经准备好企微测试群 `壹心-湖南-测试消息店` 时，可以先按 [壹心测试群联调](docs/壹心测试群联调.md) 验证模板、队列、企微发送端和回执；该测试不需要真实抖音商户或门店 ID。

1. 取得服务商应用的 Client Key / Secret 和订单查询权限，让合作商家在抖音来客中完成对该应用的授权。后台添加根商户账号 ID。
2. 添加各门店 `poi_id`，填写企微中的完整群名。使用本程序 Windows 发送端时，群 ID 是程序自动生成的逻辑标识，不需要拿腾讯 `chat_id`。
3. 配置抖音应用，保持自动发送暂停，手动同步一轮，核对订单、金额、门店和可用手机号。
4. 在专用 Windows 电脑登录企微，完成校准。先将一个测试群绑定到测试门店，确认搜索、发送、回执与失败状态正确。
5. 再绑定实际门店群，开启所需模板与状态事件，开启自动同步、自动发送。
6. 独立留资需要接入对应的真实上游来源。程序已提供接入口及后台录入；尚未把某个未确认的开放平台留资权限宣称为已接通。

订单权限与参数依据：[抖音生活服务订单查询](https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/order.query/query)。该接口不返回明文券码。手机号是否完整可用取决于真实返回字段和授权；不会凭空补齐脱敏号码。批量解密适配默认关闭，需按实际应用权限与接口合同核对后启用。

## 接口与验证

- [数据与发送工具接入说明](docs/接入说明.md)：独立留资、订单和状态事件的标准数据格式，以及 HTTP 发送回执约定。
- [验证记录](docs/验证记录.md)：本次实际执行的测试、浏览器检查、资源测量和未完成实机验证的部分。
- `pytest` 检查企业隔离、游标、去重、并发领取、租约、补发、备份恢复、HTTP 发送回执及发送端账本。
- `scripts/browser-check.cjs` 用 Playwright 检查后台操作；运行时需要自行安装 Playwright，或设置 `PLAYWRIGHT_MODULE` 和 `PLAYWRIGHT_CHROMIUM_PATH`。
- `scripts/benchmark.py` 启动临时实例压入合成数据，不访问抖音或真实群。

本机已完成真实应用验证、历史订单查询及经确认的单条企微测试群发送，每 120 秒的真实订单同步已实际运行。手机号与独立留资来源、当前新订单和状态变化的实际通知、阿里云部署仍需按真实权限与数据继续验证，范围见 [验证记录](docs/验证记录.md)。部署包不包含任何应用密钥、数据库、客户数据或发送端令牌。
