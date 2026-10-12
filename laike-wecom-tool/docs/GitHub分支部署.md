# 从 GitHub 分支部署

仓库：<https://github.com/Ghostisme/beauty-notification-service>。

分支：`feature/laike-wecom-tool`。

工具源码位于仓库的 `laike-wecom-tool/` 子目录。本页所有启动、维护命令均在这个子目录执行，使用其中的 `compose.yaml`。Windows 企微发送端需要单独在常开电脑上运行。

## 1. 拉取和启动云端服务

适用于已安装 Git、Docker 和 Compose 插件的 Linux 服务器。以下将整个仓库克隆到 `/opt/beauty-notification-service`：

```bash
cd /opt
sudo git clone --branch feature/laike-wecom-tool --single-branch https://github.com/Ghostisme/beauty-notification-service.git beauty-notification-service
cd /opt/beauty-notification-service/laike-wecom-tool
sudo mkdir -p data
sudo chown 10001:10001 data
sudo chmod 700 data
sudo docker compose up -d --build
sudo docker compose ps
curl http://127.0.0.1:8790/health
sudo cat data/.bootstrap-password
```

`/health` 应返回包含 `"status":"ok"` 的 JSON。管理员账号是 `admin`，密码由首次启动随机生成，最后一条命令显示该实例的初始密码。修改管理员密码后，该初始密码文件自动删除。

持久数据位于宿主机 `/opt/beauty-notification-service/laike-wecom-tool/data`。Docker 服务应设置为开机启动，Compose 的 `restart: unless-stopped` 会让工具随 Docker 恢复运行。应用内存限制为 384 MiB，CPU 限制为 0.8 核。

## 2. 绑定子域名

以 `notify.1231.com` 为例，在实际 DNS 管理服务商中新增主机记录 `notify`、记录类型 `A`、记录值为服务器公网 IPv4 的解析。

在服务器上为该子域名配置 Nginx 站点或面板反向代理，目标为 `http://127.0.0.1:8790`。先让 HTTP 站点和 DNS 生效，再申请并安装子域名的 HTTPS 证书，最后开启 HTTPS 跳转。阿里云安全组和服务器防火墙允许 80、443 端口。

正式入口为 `https://notify.1231.com`，应使用 HTTPS 登录后台。细节见 [子域名启动说明](子域名启动说明.md)。Nginx 完整配置模板位于 `../deploy/nginx.conf.example`，其中证书路径必须对应已经存在的证书文件。

## 3. 启动 Windows 发送端

在 Windows 发送电脑上拉取同一分支或下载这个分支的源码，然后进入 `laike-wecom-tool`，运行 `start-sender.bat`。

填写云端 HTTPS 地址和后台提供的发送端令牌，登录企业微信，加入目标群并完成界面校准。详见 [Windows 发送端说明](Windows发送端.md)。自动同步与自动发送初始均关闭；配置企业、门店和群对应关系，验证一条消息后再启用。

## 4. 日常维护

```bash
cd /opt/beauty-notification-service/laike-wecom-tool
sudo docker compose logs --tail=100 tool
sudo docker compose exec -T tool python manage.py check
sudo docker compose exec -T tool python manage.py backup --retain 7
```

备份包含业务数据库和配套加密密钥，位于这个工具自己的 `data/backups`。每日备份可以在 root 的定时任务中添加：

```cron
30 3 * * * cd /opt/beauty-notification-service/laike-wecom-tool && /usr/bin/docker compose exec -T tool python manage.py backup --retain 7
```

## 5. 更新此分支

先在后台暂停自动发送，执行备份，再更新源码并重建容器：

```bash
cd /opt/beauty-notification-service/laike-wecom-tool
sudo docker compose exec -T tool python manage.py backup --retain 7
cd /opt/beauty-notification-service
sudo git pull --ff-only origin feature/laike-wecom-tool
cd laike-wecom-tool
sudo docker compose up -d --build
curl http://127.0.0.1:8790/health
```

更新时保留 `data` 目录，并按需要更新 Windows 发送电脑的同一分支源码；保留该电脑的 `sender-config.json` 和 `sender-data`。确认后台、门店路由及发送端状态后恢复发送。

## 6. 本地检查

在工具目录创建独立 Python 3.12 环境，安装 `requirements-dev.txt` 后运行 `python -m pytest tests`。当前已验证的内容与尚需实际账号联调的部分见 [验证记录](验证记录.md)。

运行时生成的数据库、密钥、发送端令牌、配置文件、虚拟环境和打包产物均由 `.gitignore` 忽略。仓库中附带的界面截图和验证记录使用合成数据。
