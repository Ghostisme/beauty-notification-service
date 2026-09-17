# Git 克隆加速配置

## 方法一: 使用 GitHub 镜像站(推荐)

### 1. GitHub Proxy 镜像

```bash
# 使用 ghproxy.com 镜像
git clone https://ghproxy.com/https://github.com/Ghostisme/beauty-notification-service.git

# 或使用 gh-proxy.com
git clone https://gh-proxy.com/https://github.com/Ghostisme/beauty-notification-service.git
```

### 2. FastGit 镜像

```bash
git clone https://hub.fastgit.xyz/Ghostisme/beauty-notification-service.git
```

### 3. GitClone 镜像

```bash
git clone https://gitclone.com/github.com/Ghostisme/beauty-notification-service.git
```

## 方法二: 配置 Git 代理

### 使用 HTTP/HTTPS 代理

```bash
# 全局配置(假设代理地址为 127.0.0.1:7890)
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy https://127.0.0.1:7890

# 只针对 GitHub
git config --global http.https://github.com.proxy http://127.0.0.1:7890

# 取消代理
git config --global --unset http.proxy
git config --global --unset https.proxy
```

### 使用 SOCKS5 代理

```bash
# 配置 SOCKS5 代理
git config --global http.proxy socks5://127.0.0.1:1080
git config --global https.proxy socks5://127.0.0.1:1080
```

## 方法三: 修改 hosts 文件

### 1. 查询 GitHub IP

访问以下网站获取最快的 GitHub IP:
- https://www.ipaddress.com/
- https://github.com.ipaddress.com/

### 2. 修改 hosts

```bash
# Linux/Mac
sudo nano /etc/hosts

# Windows
notepad C:\Windows\System32\drivers\etc\hosts
```

添加以下内容(IP 可能需要更新):

```
# GitHub
140.82.113.4 github.com
199.232.69.194 github.global.ssl.fastly.net
185.199.108.153 assets-cdn.github.com
185.199.109.153 assets-cdn.github.com
185.199.110.153 assets-cdn.github.com
185.199.111.153 assets-cdn.github.com
```

刷新 DNS:

```bash
# Linux
sudo systemd-resolve --flush-caches

# Mac
sudo killall -HUP mDNSResponder

# Windows
ipconfig /flushdns
```

## 方法四: 使用 SSH 协议

### 1. 生成 SSH 密钥

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```

### 2. 添加到 GitHub

```bash
# 查看公钥
cat ~/.ssh/id_ed25519.pub

# 复制公钥内容到 GitHub Settings > SSH Keys
```

### 3. 使用 SSH 克隆

```bash
git clone git@github.com:Ghostisme/beauty-notification-service.git
```

### 4. 配置 SSH 代理(可选)

编辑 `~/.ssh/config`:

```
Host github.com
    HostName ssh.github.com
    Port 443
    User git
    ProxyCommand nc -X 5 -x 127.0.0.1:1080 %h %p
```

## 方法五: 浅克隆(减少下载量)

```bash
# 只克隆最近一次提交
git clone --depth 1 https://github.com/Ghostisme/beauty-notification-service.git

# 如需完整历史,再执行
cd beauty-notification-service
git fetch --unshallow
```

## 推荐组合方案

### 服务器部署时使用

1. **首选: GitHub 镜像站**
   ```bash
   git clone https://ghproxy.com/https://github.com/Ghostisme/beauty-notification-service.git
   ```

2. **备选: 浅克隆**
   ```bash
   git clone --depth 1 https://github.com/Ghostisme/beauty-notification-service.git
   ```

### 开发环境使用

1. 配置代理(如果有)
2. 使用 SSH 协议
3. 修改 hosts 文件

## 速度测试

```bash
# 测试克隆速度
time git clone https://github.com/Ghostisme/beauty-notification-service.git test1
time git clone https://ghproxy.com/https://github.com/Ghostisme/beauty-notification-service.git test2

# 清理测试目录
rm -rf test1 test2
```

## 配置持久化

### 将镜像配置写入脚本

创建 `~/.gitconfig-mirror`:

```bash
#!/bin/bash
# Git 镜像加速配置

# 设置函数
use_github_mirror() {
    export GIT_MIRROR="https://ghproxy.com/"
    echo "已启用 GitHub 镜像加速"
}

# 克隆函数
git_clone_fast() {
    local repo_url=$1
    if [[ $repo_url == https://github.com/* ]]; then
        repo_url="${GIT_MIRROR}${repo_url}"
    fi
    git clone "$repo_url" "${@:2}"
}

# 使用示例:
# source ~/.gitconfig-mirror
# use_github_mirror
# git_clone_fast https://github.com/Ghostisme/beauty-notification-service.git
```

加载配置:

```bash
echo "source ~/.gitconfig-mirror" >> ~/.bashrc
source ~/.bashrc
```

## 故障排查

### 克隆失败

```bash
# 检查网络连接
ping github.com

# 检查 DNS
nslookup github.com

# 增加缓冲区大小
git config --global http.postBuffer 524288000

# 关闭 SSL 验证(不推荐)
git config --global http.sslVerify false
```

### 镜像站不可用

如果某个镜像站失效,尝试其他镜像:

1. https://ghproxy.com/
2. https://gh-proxy.com/
3. https://hub.fastgit.xyz/
4. https://gitclone.com/github.com/

## 更新部署脚本

更新 `deploy-git.sh` 中的克隆命令:

```bash
# 原来的
git clone $REPO_URL $PROJECT_DIR

# 改为(使用镜像)
git clone https://ghproxy.com/$REPO_URL $PROJECT_DIR

# 或(使用浅克隆)
git clone --depth 1 $REPO_URL $PROJECT_DIR
```
