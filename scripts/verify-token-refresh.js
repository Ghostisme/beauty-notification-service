/**
 * TokenManager 失效重获机制验证脚本
 *
 * 为什么需要它:业务接口(order.query 等)受 IP 白名单限制,在未加白的机器上
 * 根本走不到「token 失效 → 作废 → 重取 → 重试」这条链路;而 client_token
 * 接口不校验来源 IP,因此可以脱离业务接口单独验证 token 机制是否可靠。
 *
 * 覆盖四条路径:
 *   1. 首次获取      —— 能拿到 token,过期时间已扣除提前量
 *   2. 缓存命中      —— 未过期时复用,不重复请求
 *   3. 主动作废重取  —— invalidate() 后能自动重新获取(对应抖音 2190002/2190008)
 *   4. 并发去重      —— 多个调用者同时触发刷新时只打一次接口(single-flight)
 *
 * 用法: node scripts/verify-token-refresh.js
 */

require('dotenv').config();
const TokenManager = require('../src/modules/douyin/token-manager');

const tokenManager = new TokenManager();

/** 统一的用例结果打印,失败直接让进程以非 0 退出,便于接 CI */
let failed = 0;
function check(label, passed, detail = '') {
  console.log(`  ${passed ? '✅' : '❌'} ${label}${detail ? ` —— ${detail}` : ''}`);
  if (!passed) failed++;
}

async function case1FirstFetch() {
  console.log('\n[用例1] 首次获取 access_token');

  const token = await tokenManager.getToken();
  const status = tokenManager.getStatus();

  check('拿到非空 token', Boolean(token), `${String(token).substring(0, 12)}...`);
  check('状态标记为已持有', status.hasToken === true);
  check('剩余有效期为正', status.remainSeconds > 0, `remainSeconds=${status.remainSeconds}`);

  // expireAt 是抖音签发的真实过期时刻,refreshAt 是本地提前换新的触发点,
  // 两者之差即 refreshAdvanceSeconds(默认 300s)。差值为 0 说明提前量没生效,
  // token 会被用到真实过期的最后一刻 —— 那一瞬发出的请求很可能在抖音侧已过期。
  const advanceSeconds = Math.round(
    (new Date(status.expireAt).getTime() - new Date(status.refreshAt).getTime()) / 1000
  );
  check(
    '提前刷新量已生效(refreshAt 早于 expireAt)',
    advanceSeconds > 0,
    `advance=${advanceSeconds}s`
  );

  return token;
}

async function case2CacheHit(firstToken) {
  console.log('\n[用例2] 缓存命中(不应重新请求)');

  const token = await tokenManager.getToken();

  check('返回与首次相同的 token', token === firstToken);
  check('未进入刷新中状态', tokenManager.getStatus().refreshing === false);
}

async function case3InvalidateAndRefetch(firstToken) {
  console.log('\n[用例3] 主动作废后自动重取(模拟服务端吊销 2190002/2190008)');

  tokenManager.invalidate();
  const afterInvalidate = tokenManager.getStatus();
  check('作废后本地缓存已清空', afterInvalidate.hasToken === false);

  const token = await tokenManager.getToken();
  check('重新获取成功', Boolean(token), `${String(token).substring(0, 12)}...`);
  check('状态恢复为已持有', tokenManager.getStatus().hasToken === true);
  // token 是否与旧值相同取决于抖音侧策略(同一应用短时间内可能返回同一 token),
  // 因此只断言「能拿到」,不断言「必然变化」
  if (token === firstToken) {
    console.log('  ℹ️  抖音返回了与之前相同的 token,属正常现象(未到签发轮换点)');
  }
}

async function case4ConcurrentDedup() {
  console.log('\n[用例4] 并发刷新去重(single-flight)');
  console.log('  提示:下方若只出现一条「access_token 获取成功」日志,即说明去重生效\n');

  tokenManager.invalidate();

  const CONCURRENCY = 5;
  const tokens = await Promise.all(
    Array.from({ length: CONCURRENCY }, () => tokenManager.getToken())
  );

  const unique = new Set(tokens);
  console.log('');
  check(`${CONCURRENCY} 个并发调用全部拿到 token`, tokens.every(Boolean));
  check('并发结果收敛到同一个 token', unique.size === 1, `unique=${unique.size}`);
  check('刷新完成后 refreshing 已复位', tokenManager.getStatus().refreshing === false);
}

async function main() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   TokenManager 失效重获机制验证        ║');
  console.log('╚════════════════════════════════════════╝');

  try {
    const firstToken = await case1FirstFetch();
    await case2CacheHit(firstToken);
    await case3InvalidateAndRefetch(firstToken);
    await case4ConcurrentDedup();
  } catch (error) {
    console.error('\n❌ 验证过程抛出异常:', error.message);
    process.exit(1);
  }

  console.log('\n────────────────────────────────────────');
  if (failed === 0) {
    console.log('✅ 全部用例通过\n');
  } else {
    console.log(`❌ ${failed} 项断言失败\n`);
    process.exit(1);
  }
}

main();
