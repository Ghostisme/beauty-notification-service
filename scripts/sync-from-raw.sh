#!/usr/bin/env bash
#
# 从 GitHub raw 直接同步源码到服务器
#
# 为什么不用 git pull:部署机(阿里云国内节点)到 github.com 的 TCP 连接会卡死,
# git pull 挂满 30 秒被 timeout 杀掉(退出码 143),clone/fetch 同样不可用。
# 但 raw.githubusercontent.com 走的是另一套 CDN,实测可达 —— 所以绕开 git 协议,
# 按文件清单逐个 curl 拉取。
#
# 用法(在项目根目录执行):
#   curl -fsSL https://raw.githubusercontent.com/Ghostisme/beauty-notification-service/main/scripts/sync-from-raw.sh | bash
#   curl -fsSL <同上> | bash -s -- <ref>     # 指定分支名或 commit SHA
#
# 建议传 commit SHA 而不是分支名:raw 的 CDN 对分支名有缓存,刚 push 的内容可能
# 要等几分钟才可见;SHA 指向不可变内容,不受缓存影响,拉到的一定是那一版。

# 不用 set -e:每个文件的下载失败要自己统计并继续,而不是中途整个退出
set -uo pipefail

REPO="Ghostisme/beauty-notification-service"
REF="${1:-main}"
BASE="https://raw.githubusercontent.com/${REPO}/${REF}"
BACKUP_DIR=".sync-backup-$(date +%Y%m%d-%H%M%S)"

# 需要同步的文件清单 —— 版本库里全部跟踪的文件,减去下面三类排除项。
#
# 为什么是全量而不是"只同步本次改动的文件":部署机的 git 早就拉不动了,它停在
# 哪个 commit 是未知数。只补改动文件的前提是"其余文件已经最新",这个前提无法
# 验证;一旦不成立就是新旧混合(比如新版 api.js 配旧版 spi.js),排查代价远高于
# 多拉几十个文件的那几十秒。全量同步把这个未知数直接消掉。
#
# 排除项(刻意不在清单里,不是漏了):
#   1. data/accounts.json、data/groups.json —— 线上真实配置(accountId、门店、
#      企微 webhook key)。版本库里那份是占位模板,覆盖过去线上推送当场断掉。
#   2. .env、logs/、node_modules/ —— 本就在 .gitignore 里,不在跟踪范围。
#   3. 快速部署指南.md、配置指南.md —— 非 ASCII 文件名要 URL 编码才能拉,
#      易出错且对运行无影响。需要时在本地看。
#
# 清单含本脚本自身:服务器上留一份后就能直接 bash scripts/sync-from-raw.sh,
# 不必每次走 curl 管道。自我覆盖是安全的 —— 下面用的是 mv(rename),
# 旧 inode 在 bash 的 fd 关闭前不会消失,正在执行的脚本读的还是旧内容。
#
# 版本库新增文件后,本清单要同步更新,生成命令:
#   git -c core.quotepath=false ls-files | grep -v '^data/.*\.json$' | grep -P '^[\x00-\x7F]+$'
FILES=(
  ".env.example"
  ".gitignore"
  "1.md"
  "2.md"
  "DEPLOYMENT.md"
  "DOUYIN_FLOW.md"
  "DOUYIN_INTEGRATION_GUIDE.md"
  "DOUYIN_TEST.md"
  "Dockerfile"
  "FRONTEND.md"
  "GIT_ACCELERATION.md"
  "GIT_DEPLOY.md"
  "IMPLEMENTATION.md"
  "PROCESS_ORDERS.md"
  "QUICK_START.md"
  "README.md"
  "STORAGE.md"
  "check-all-fields.js"
  "check-api-params.js"
  "data/groups.json.example"
  "deploy-commands.sh"
  "deploy-git.sh"
  "deploy-production.sh"
  "deploy-simple.sh"
  "deploy.md"
  "deploy.sh"
  "docker-compose.yml"
  "docs/DEPLOY_FIX.md"
  "docs/UPDATE_GUIDE.md"
  "ecosystem.config.js"
  "fix-database.sh"
  "fix-nginx-admin.sh"
  "groups.json.example"
  "nginx.conf"
  "nginx/.gitignore"
  "nginx/README.md"
  "nginx/conf.d/beauty-notification.conf"
  "nginx/conf.d/future-frontend.conf.example"
  "nginx/nginx.conf"
  "order-structure.json"
  "package-lock.json"
  "package.json"
  "restart-service.sh"
  "scripts/check-douyin.js"
  "scripts/check-outbound-ip.js"
  "scripts/deploy-nginx.sh"
  "scripts/fix-node-path.sh"
  "scripts/get-access-token.js"
  "scripts/manual-fix.sh"
  "scripts/monitor-update.sh"
  "scripts/sync-from-raw.sh"
  "scripts/test-member-mobile-change.js"
  "scripts/test-member-mobile-update.js"
  "scripts/test-member-update.js"
  "scripts/verify-token-refresh.js"
  "src/config.js"
  "src/config/index.js"
  "src/database/index.js"
  "src/debug-order.js"
  "src/debug-phone.js"
  "src/douyin-flow.js"
  "src/douyin.js"
  "src/modules/douyin/api.js"
  "src/modules/douyin/decrypt.js"
  "src/modules/douyin/errors.js"
  "src/modules/douyin/http-client.js"
  "src/modules/douyin/index.js"
  "src/modules/douyin/order-processor.js"
  "src/modules/douyin/order-query.js"
  "src/modules/douyin/sensitive-fields.js"
  "src/modules/douyin/spi.js"
  "src/modules/douyin/token-manager.js"
  "src/process-orders.js"
  "src/queue.js"
  "src/routes/index.js"
  "src/server.js"
  "src/services/douyin.js"
  "src/services/wework.js"
  "src/storage/adapter.js"
  "src/storage/index.js"
  "src/test-douyin-step.js"
  "src/test-douyin.js"
  "src/test.js"
  "src/utils/douyin-signature.js"
  "src/utils/logger.js"
  "src/wework.js"
  "test-send.js"
  "test-webhook.js"
  "test.sh"
  "tests/douyin.test.js"
  "update.sh"
  "web/app.js"
  "web/index.html"
  "web/style.css"
  "web/web/style.css"
  "webhook-collector.html"
  "wework-employee-sender.js"
  "wework-group-service.js"
)

echo ""
echo "════════════════════════════════════════"
echo "  从 GitHub raw 同步源码"
echo "════════════════════════════════════════"
echo "  仓库: ${REPO}"
echo "  版本: ${REF}"
echo "  目录: $(pwd)"
echo "  文件: ${#FILES[@]} 个"
echo ""

# 跑错目录会把文件散落到 home 或 / 下,事后极难清理,所以先认门
if [ ! -f "package.json" ] || [ ! -d "src" ]; then
  echo "❌ 当前目录不像项目根目录(缺 package.json 或 src/)。"
  echo "   请先 cd 到项目根目录再执行。"
  exit 1
fi

# 前置连通性检查:raw 整体不可达时立刻退出,免得刷近百条一样的失败
if ! curl -fsSL --max-time 15 -o /dev/null "${BASE}/package.json"; then
  echo "❌ 无法访问 ${BASE}"
  echo "   可能原因:raw.githubusercontent.com 不可达,或 ref「${REF}」不存在。"
  exit 1
fi

updated=0
same=0
fail=0
failed_files=()

for path in "${FILES[@]}"; do
  tmp="${path}.sync-tmp"
  mkdir -p "$(dirname "${path}")"

  # --fail 不能省:不加的话 404 的响应正文("404: Not Found")会被原样写进文件,
  # 得到一个能通过语法检查但内容完全错误的 js,排查起来极费时间。
  # 同理先落临时文件、校验非空后再 mv,避免下载中断留下半截文件顶掉好文件。
  if ! curl -fsSL --max-time 30 -o "${tmp}" "${BASE}/${path}" || [ ! -s "${tmp}" ]; then
    rm -f "${tmp}"
    fail=$((fail + 1))
    failed_files+=("${path}")
    printf '  ❌ %s\n' "${path}"
    continue
  fi

  # 内容相同的不动也不备份:近百个文件里真正变的只有少数,只打印变化的那些,
  # 输出本身就成了"这次到底更新了什么"的清单
  if [ -f "${path}" ] && cmp -s "${tmp}" "${path}"; then
    rm -f "${tmp}"
    same=$((same + 1))
    continue
  fi

  if [ -f "${path}" ]; then
    mkdir -p "${BACKUP_DIR}/$(dirname "${path}")"
    cp -p "${path}" "${BACKUP_DIR}/${path}"
  fi
  mv "${tmp}" "${path}"
  updated=$((updated + 1))
  printf '  ✅ %s\n' "${path}"
done

# 全都没变化时备份目录是空的,留着只会积累垃圾
rmdir "${BACKUP_DIR}" 2>/dev/null

echo ""
echo "────────────────────────────────────────"
echo "  更新 ${updated} / 无变化 ${same} / 失败 ${fail}"
[ -d "${BACKUP_DIR}" ] && echo "  被覆盖的原文件已备份到 ${BACKUP_DIR}/"

if [ "${fail}" -gt 0 ]; then
  echo ""
  echo "  以下文件未同步,当前仍是旧版本:"
  for f in "${failed_files[@]}"; do echo "    - ${f}"; done
  echo ""
  echo "  重跑本脚本可只补这几个(内容没变的会自动跳过,无副作用)。"
  exit 1
fi

echo ""
echo "  注意:data/accounts.json 与 data/groups.json 是线上配置,本脚本不碰。"
echo ""
echo "  下一步:"
echo "    npm install --omit=dev                # package.json 有变化时才需要"
echo "    node scripts/check-outbound-ip.js     # 验 IP 白名单是否放行"
echo "    node src/test-douyin-step.js          # 全链路:token→订单列表→详情→解密"
echo "    pm2 restart beauty-notification       # 让线上服务用上新代码"
echo ""
