/**
 * 抖音 OpenAPI 出口 IP 自检脚本
 *
 * 解决的问题:抖音服务商应用在网关层校验请求来源 IP,不在白名单里一律返回
 * 2119013。要加白就得先知道「本机访问外网时用的是哪个公网 IP」,而这个 IP
 * 常常不等于域名解析到的入站 IP:
 *   - ECS 直接绑定固定公网 IP / EIP → 出入站同一个,加解析到的 IP 即可
 *   - 出网走 NAT 网关 / 代理         → 出站是另一个 IP,加错了照样被拒
 * 所以必须在「实际发起抖音请求的那台机器上」跑本脚本,拿到的才是该加白的 IP。
 *
 * 脚本做三件事:
 *   1. 国内/境外多源交叉 + 跨时间复测 —— 区分「按目标分流」与「出口漂移」,
 *      前者以国内源结果为准(抖音是国内服务),后者说明加白根本不可靠
 *   2. 用项目自身的凭证真打一次抖音业务接口,确认白名单是否已生效
 *   3. 按结果直接给出下一步该做什么
 *
 * 用法: node scripts/check-outbound-ip.js [商户账户ID]
 */

require('dotenv').config();
const axios = require('axios');
const DouyinModule = require('../src/modules/douyin');
const { DouyinAPIError } = require('../src/modules/douyin/errors');

/**
 * 出口 IP 探测源。
 *
 * 标 domestic 的是「实测确认走国内线路」的站点。这个区分是必要的:出网若按目标
 * 分流(代理常见规则),同一台机器访问国内和境外会走不同线路、拿到不同出口 IP ——
 * 实测本机国内线路出口 112.65.37.110、境外线路出口 142.249.36.202。抖音是国内
 * 服务,它看到的源 IP 只可能是国内线路那个,所以分流场景下必须以 domestic 源为准。
 *
 * 注意 domestic 判定的依据是「实测走哪条线路」,不是域名归属地:分流规则按域名/IP
 * 命中,实测 api.vore.top 虽是国内域名却走代理出境(回加拿大 IP),拿它当国内源会
 * 得出完全相反的结论。新增源前务必先实测。
 *
 * 下列源均已实测:淘宝 getip 返回 403、搜狐 cityjson 恒回 127.0.0.1,已剔除。
 */
const IP_PROBES = [
  { name: 'ipip.net', url: 'https://myip.ipip.net', domestic: true },
  { name: '3322', url: 'https://ip.3322.net', domestic: true },
  { name: '网易', url: 'https://ipservice.ws.126.net/locate/api/getLocByIp', domestic: true },
  // 境外源:国内服务器多半连不通(实测阿里云上海直接 Couldn't connect),
  // 留着是为了跟国内源比对出「是否存在分流」,失败属预期,不影响结论
  { name: 'ipify', url: 'https://api.ipify.org?format=json', domestic: false },
];

/**
 * 阿里云实例元数据接口:走 169.254 同类的内网链路,不经公网,因此在公网探测
 * 全部不可达时仍然有效。返回的是「绑定在本实例上的公网 IP」——ECS 直绑 EIP 时
 * 它就等于出口 IP;若出网走 NAT 网关,出口另算,所以它只作参考不作准。
 */
const ALIYUN_METADATA_URLS = [
  { name: 'eipv4', url: 'http://100.100.100.200/latest/meta-data/eipv4' },
  { name: 'public-ipv4', url: 'http://100.100.100.200/latest/meta-data/public-ipv4' },
];

/**
 * 判断是否为公网 IPv4。
 *
 * 探测响应里混进非公网地址是常态,来源有两类,都会让人白排查一轮:
 *   - 探测源自己取不到真实客户端 IP,直接回 127.0.0.1(实测搜狐 cityjson 即如此)
 *   - 本地代理以 fake-ip 模式劫持 DNS,返回 198.18.0.0/15 段的伪造地址
 * 这类值不可能是抖音看到的源 IP,必须在提取阶段就丢掉。
 * @param {string} ip
 * @returns {boolean}
 */
function isPublicIpv4(ip) {
  const parts = ip.split('.').map(Number);
  if (parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;

  const [a, b] = parts;
  if (a === 0 || a === 127 || a >= 224) return false;        // 保留段 / 回环 / 组播及以上
  if (a === 10) return false;                                 // 私网 A
  if (a === 172 && b >= 16 && b <= 31) return false;          // 私网 B
  if (a === 192 && b === 168) return false;                   // 私网 C
  if (a === 169 && b === 254) return false;                   // 链路本地
  if (a === 100 && b >= 64 && b <= 127) return false;         // 运营商级 NAT(CGNAT)
  if (a === 198 && (b === 18 || b === 19)) return false;      // 基准测试段,代理 fake-ip 常用
  return true;
}

/**
 * 从任意形态的响应里抠出第一个公网 IPv4。
 * 各家返回格式不统一(纯文本、JSON、JSONP),逐家写解析既啰嗦又易随对方改版失效,
 * 统一正则提取更耐用;遍历全部候选而非只取第一个,是因为响应里可能先出现内网地址
 * 或其他类 IP 串,真正的出口 IP 排在后面。
 * @param {string|Object} payload - 探测接口的原始响应
 * @returns {string|null}
 */
function extractIp(payload) {
  const text = typeof payload === 'string' ? payload : JSON.stringify(payload ?? '');
  for (const [candidate] of text.matchAll(/(?:\d{1,3}\.){3}\d{1,3}/g)) {
    if (isPublicIpv4(candidate)) return candidate;
  }
  return null;
}

/**
 * 按终端显示宽度右侧补空格。
 * padEnd 按 UTF-16 码元计数,而中文在终端占两列,直接用会让含中文的标签错位。
 * @param {string} text
 * @param {number} width - 目标显示列宽
 * @returns {string}
 */
function padDisplay(text, width) {
  const displayWidth = [...text].reduce(
    (sum, char) => sum + (char.charCodeAt(0) > 0x2e80 ? 2 : 1),
    0
  );
  return text + ' '.repeat(Math.max(0, width - displayWidth));
}

/** 默认探测用的商户号,可由命令行覆盖 */
const DEFAULT_ACCOUNT_ID = '7523898493467904038';

/**
 * 时间维度复测的间隔与轮数。
 * 只做多源(空间)交叉是不够的:同一瞬间的请求会走同一条线路,三家都会回同一个 IP,
 * 看起来"稳定";而代理/多出口 NAT 的漂移是跨时间发生的(实测同一台机器先后得到
 * 142.249.39.38 与 142.249.36.202)。因此必须隔一段时间再测一轮。
 */
const RECHECK_ROUNDS = 2;
const RECHECK_INTERVAL_MS = 3000;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 跑一轮多源探测。
 * @param {boolean} verbose - 是否逐源打印,复测轮只打汇总以免刷屏
 * @returns {Promise<Array<{ip: string, domestic: boolean}>>} 本轮探测结果
 */
async function probeOnce(verbose) {
  const results = [];

  for (const probe of IP_PROBES) {
    const label = padDisplay(`${probe.name}${probe.domestic ? '(国内)' : '(境外)'}`, 18);
    try {
      const { data } = await axios.get(probe.url, {
        timeout: 10000,
        // 部分站点对默认 UA 返回 403,统一伪装成浏览器
        headers: { 'User-Agent': 'Mozilla/5.0' },
      });
      const ip = extractIp(data);
      if (verbose) console.log(`  ${label} → ${ip || '响应中无公网 IP'}`);
      if (ip) results.push({ ip, domestic: probe.domestic });
    } catch (error) {
      if (verbose) console.log(`  ${label} → 探测失败 (${error.message})`);
    }
  }

  return results;
}

/**
 * 读取阿里云实例元数据里的公网 IP。
 * 非阿里云环境会直接连不上,属预期,静默跳过。
 * @returns {Promise<string|null>}
 */
async function probeAliyunMetadata() {
  for (const { name, url } of ALIYUN_METADATA_URLS) {
    try {
      const { data } = await axios.get(url, { timeout: 3000 });
      const ip = extractIp(data);
      if (ip) {
        console.log(`  阿里云元数据(${name}) → ${ip}`);
        return ip;
      }
    } catch {
      // 非阿里云 ECS 或元数据被关闭,继续试下一个
    }
  }
  return null;
}

/** 从探测样本里取出去重后的 IP 列表 */
const uniqueIps = (samples) => [...new Set(samples.map((s) => s.ip))];

/**
 * 实例绑定 IP 与实际出口 IP 不一致时给出警示。
 *
 * 这是加白最容易踩错的地方:控制台上看到的实例公网 IP 未必是抖音看到的源 IP,
 * 走 NAT 网关时两者必然不同,照着控制台加白会得到"加了却依然 2119013"的结果。
 * @param {string|null} boundIp - 实例元数据里的绑定公网 IP
 * @param {string} outboundIp - 实测出口 IP
 */
function warnIfBoundIpDiffers(boundIp, outboundIp) {
  if (!boundIp || boundIp === outboundIp) return;
  console.log(`  ⚠️  实例绑定 IP(${boundIp}) 与出口 IP 不同,说明出网经过 NAT 网关或代理。`);
  console.log('     白名单要加的是出口 IP,加绑定 IP 无效。');
}

async function probeOutboundIps() {
  console.log('\n[1/2] 探测本机公网出口 IP');
  console.log('────────────────────────────────────────');

  const boundIp = await probeAliyunMetadata();
  const samples = await probeOnce(true);

  // 时间维度复测:间隔重来,抓跨时间漂移
  for (let round = 2; round <= RECHECK_ROUNDS; round++) {
    await sleep(RECHECK_INTERVAL_MS);
    const roundSamples = await probeOnce(false);
    console.log(`  ${padDisplay('复测第' + round + '轮', 18)} → ${uniqueIps(roundSamples).join(', ') || '全部失败'}`);
    samples.push(...roundSamples);
  }

  console.log('');

  if (samples.length === 0) {
    // 公网探测全军覆没时,元数据是唯一线索:总比没有强,但要讲清它的局限
    if (boundIp) {
      console.log(`  ⚠️  公网探测源全部不可达,仅取到实例绑定 IP: ${boundIp}`);
      console.log('     它等于出口 IP 的前提是本机直接绑定公网 IP 出网;');
      console.log('     若出网走 NAT 网关则实际出口另有其人,加白后仍被拒即属此情况。\n');
      return boundIp;
    }
    console.log('  ❌ 所有探测源都不可达,无法确定出口 IP。请检查服务器出网是否正常。\n');
    return null;
  }

  const allUnique = uniqueIps(samples);
  const domesticUnique = uniqueIps(samples.filter((s) => s.domestic));

  if (allUnique.length === 1) {
    console.log(`  ✅ 出口 IP 稳定(跨源跨时间一致): ${allUnique[0]}`);
    warnIfBoundIpDiffers(boundIp, allUnique[0]);
    console.log('     这就是需要加入抖音白名单的 IP。\n');
    return allUnique[0];
  }

  // 出口不止一个,但未必是"漂移"。更常见的是按目标分流:访问国内站点走一条线路、
  // 访问境外走代理。这种场景下国内源之间仍然自洽,而抖音是国内服务,它看到的源 IP
  // 只可能是国内线路那个 —— 结论依旧确定,不该因为境外源不同就放弃给答案。
  if (domesticUnique.length === 1) {
    console.log(`  ⚠️  探测到 ${allUnique.length} 个不同出口 IP: ${allUnique.join(', ')}`);
    console.log('     但国内源结果自身一致,属按目标分流(国内/境外走不同线路),而非出口漂移。');
    console.log(`  ✅ 抖音为国内服务,它看到的源 IP 是: ${domesticUnique[0]}`);
    warnIfBoundIpDiffers(boundIp, domesticUnique[0]);
    console.log('     这就是需要加入抖音白名单的 IP。\n');
    return domesticUnique[0];
  }

  if (domesticUnique.length === 0) {
    // 只有境外源成活。境外线路的出口跟抖音看到的源 IP 没有关系,拿它加白纯属误导。
    console.log(`  ❌ 国内探测源全部失败,仅境外源返回: ${allUnique.join(', ')}`);
    console.log('     境外线路出口与抖音看到的源 IP 无关,不能据此加白。');
    console.log('     请检查国内出网是否正常,或改用阿里云元数据接口确认。\n');
    return null;
  }

  // 国内源之间都不一致 = 真漂移(多出口 NAT / 动态拨号),加白任一个都会时灵时不灵
  console.log(`  ⚠️  国内源返回了 ${domesticUnique.length} 个不同出口 IP: ${domesticUnique.join(', ')}`);
  console.log('     说明访问国内的出口本身就在漂移(多出口 NAT / 动态拨号 / 代理轮换)。');
  console.log('     这种环境下加白不可靠,必须改用固定公网出口的机器,');
  console.log('     或把全部出口 IP 都加进白名单。\n');
  return null;
}

async function probeDouyinApi(accountId) {
  console.log('[2/2] 实打抖音业务接口,验证白名单是否已生效');
  console.log('────────────────────────────────────────');
  console.log(`  商户账户ID: ${accountId}\n`);

  const douyin = new DouyinModule();

  try {
    const { orders, page } = await douyin.api.queryOrders({
      accountId,
      pageNum: 1,
      pageSize: 1,
    });

    console.log(`  ✅ 接口调用成功!白名单已生效。本页 ${orders.length} 单,总计 ${page.total}\n`);
    return true;
  } catch (error) {
    if (error instanceof DouyinAPIError && error.errorCode === 2119013) {
      console.log('  ❌ 仍被 2119013 拦截:当前出口 IP 不在白名单内。');
      console.log(`     logid: ${error.logId}\n`);
      return false;
    }

    // 其他错误说明 IP 这关已经过了,卡在别的环节(授权、能力申请等)
    console.log('  ⚠️  未被 2119013 拦截,但接口返回了其他错误 —— IP 白名单这关应已通过:');
    console.log(`     ${error.message}\n`);
    return null;
  }
}

async function main() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   抖音 OpenAPI 出口 IP 自检            ║');
  console.log('╚════════════════════════════════════════╝');

  const accountId = process.argv[2] || DEFAULT_ACCOUNT_ID;

  const outboundIp = await probeOutboundIps();
  const apiOk = await probeDouyinApi(accountId);

  console.log('════════════════════════════════════════');
  console.log('结论');
  console.log('════════════════════════════════════════\n');

  if (apiOk === true) {
    console.log('  订单接口已通,无需再动白名单。\n');
    return;
  }

  if (apiOk === null) {
    console.log('  IP 白名单已放行,剩余问题在别的环节(见上方错误信息)。\n');
    return;
  }

  if (!outboundIp) {
    console.log('  出口 IP 不固定或探测失败,加白前必须先解决出网稳定性。');
    console.log('  请在有固定公网 IP 的生产服务器上重跑本脚本。\n');
    return;
  }

  console.log(`  需要把这个 IP 加入抖音服务商平台的白名单:\n`);
  console.log(`      ${outboundIp}\n`);
  console.log('  操作路径:');
  console.log('      抖音服务商平台 → 应用详情 → 基础配置 → IP白名单配置 → 添加');
  console.log('  添加后通常需要几分钟生效,之后重跑本脚本确认。\n');
}

main().catch((error) => {
  console.error('\n❌ 自检异常终止:', error.message, '\n');
  process.exit(1);
});
