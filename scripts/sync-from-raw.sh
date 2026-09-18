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
# 传 SHA 还会额外启用镜像源(见下方 MIRRORS),成功率高得多。

# 不用 set -e:每个文件的下载失败要自己统计并继续,而不是中途整个退出
set -uo pipefail

REPO="Ghostisme/beauty-notification-service"
REF="${1:-main}"
BACKUP_DIR=".sync-backup-$(date +%Y%m%d-%H%M%S)"

# 下载源,按顺序尝试,第一个成功即止。
#
# 为什么要多源:raw 在国内是时通时断而非完全不可达 —— 实测同一次运行里 85 个
# 文件成功、13 个 curl(28) 超时,是 DNS 轮询命中被干扰节点的特征。单源失败不
# 代表内容拿不到,换个源往往立刻就成。
MIRRORS=("https://raw.githubusercontent.com/${REPO}/${REF}")

# 镜像站只在传 commit SHA 时启用:它们对分支名的缓存长达数小时,拿到的可能是
# 旧版本,而这里最怕的就是版本混合(新版 index.js 配旧版 errors.js,启动直接崩)。
# SHA 是不可变引用,任何源返回的都必然是同一份内容,才敢并用。
if [[ "${REF}" =~ ^[0-9a-f]{7,40}$ ]]; then
  MIRRORS+=(
    "https://cdn.jsdelivr.net/gh/${REPO}@${REF}"
    "https://raw.gitmirror.com/${REPO}/${REF}"
  )
fi

# 把 curl 退出码翻成人话 —— 超时、404、DNS 挂掉的处理方式完全不同,
# 只说"失败"等于把诊断成本推给下一个人
curl_reason() {
  case "$1" in
    6)  echo "DNS 解析失败" ;;
    7)  echo "连接被拒绝" ;;
    22) echo "HTTP 错误(多半是 404,文件不在该 ref 下)" ;;
    28) echo "超时" ;;
    35|60) echo "TLS 握手失败" ;;
    *)  echo "curl 退出码 $1" ;;
  esac
}

# 逐个源尝试下载,成功返回 0;全部失败时把最后一次的原因写进全局 last_reason。
#
# --fail 不能省:不加的话 404 的响应正文("404: Not Found")会被原样写进文件,
# 得到一个能通过语法检查但内容完全错误的 js,排查起来极费时间。
# 不用 -S:错误由本函数统一汇报,curl 自己刷屏会把成功/失败的节奏搅乱。
# 超时压到 15 秒是为了快速降级 —— 卡满 30 秒再换源,近百个文件能拖成十几分钟。
last_reason=""
fetch_file() {
  local path="$1" out="$2" base rc
  for base in "${MIRRORS[@]}"; do
    curl -fsL --connect-timeout 5 --max-time 15 --retry 1 -o "${out}" "${base}/${path}"
    rc=$?
    if [ "${rc}" -eq 0 ] && [ -s "${out}" ]; then
      return 0
    fi
    last_reason="$(curl_reason "${rc}")"
    rm -f "${out}"
  done
  return 1
}

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
echo "  下载源: ${#MIRRORS[@]} 个"
if [ "${#MIRRORS[@]}" -eq 1 ]; then
  echo "  提示: 传 commit SHA 可多启用 2 个镜像源,raw 不稳时成功率高得多"
fi
echo ""

# 跑错目录会把文件散落到 home 或 / 下,事后极难清理,所以先认门
if [ ! -f "package.json" ] || [ ! -d "src" ]; then
  echo "❌ 当前目录不像项目根目录(缺 package.json 或 src/)。"
  echo "   请先 cd 到项目根目录再执行。"
  exit 1
fi

# 前置连通性检查:所有源都拿不到时立刻退出,免得刷近百条一样的失败
if ! fetch_file "package.json" "/dev/null"; then
  echo "❌ 所有下载源都取不到内容(${last_reason})。"
  echo "   可能原因:网络整体不可达,或 ref「${REF}」不存在。"
  exit 1
fi

updated=0
same=0
fail=0
failed_files=()

for path in "${FILES[@]}"; do
  tmp="${path}.sync-tmp"
  mkdir -p "$(dirname "${path}")"

  # 先落临时文件、校验非空后再 mv,避免下载中断留下半截文件顶掉好文件
  if ! fetch_file "${path}" "${tmp}"; then
    fail=$((fail + 1))
    failed_files+=("${path}")
    printf '  ❌ %-42s %s\n' "${path}" "${last_reason}"
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

  # 部分失败比全失败更危险:新旧代码混在一起(新版 index.js 配旧版 errors.js)
  # 会在运行时才炸,报错还指不到真正的原因。所以这里必须拦住,不能只列个清单
  # 就让人以为"大部分成功了,可以往下走"。
  if printf '%s\n' "${failed_files[@]}" | grep -q '^src/'; then
    echo ""
    echo "  ⚠️  失败清单里有 src/ 下的运行时代码,当前是新旧混合状态。"
    echo "     此时不要 pm2 restart,也不要跑测试脚本 —— 报错会指向错误的方向。"
  fi

  echo ""
  echo "  重跑本脚本即可只补这几个(内容没变的会自动跳过,无副作用)。"
  echo "  反复失败时改用 commit SHA 重跑,会多启用 2 个镜像源:"
  echo "    bash scripts/sync-from-raw.sh <commit-sha>"
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
