const path = require('node:path');
const readline = require('node:readline/promises');
const axios = require('axios');
require('dotenv').config({ path: path.resolve(__dirname, '../.env') });

const TOKEN_URL = 'https://open.douyin.com/oauth/client_token/';
const UPDATE_URL = 'https://open.douyin.com/goodlife/v1/member/user/update/';
const HELP = `
正确用法：
  node scripts/test-member-mobile-change.js
  node scripts/test-member-mobile-change.js --execute

默认只预览，不会发送请求；只有增加 --execute 才会真正调用接口。
必填测试数据必须来自抖音平台分配的测试店铺和已经入会的测试会员：
  DOUYIN_TEST_ACCOUNT_ID       来客商户根账户ID，不是POI/门店ID
  DOUYIN_TEST_MEMBER_OPEN_ID   真实已入会测试会员open_id，不要自行生成
  DOUYIN_TEST_NEW_MOBILE       新手机号
  DOUYIN_TEST_POINTS_AMOUNT_CENT 当前积分*100
  DOUYIN_TEST_USER_LEVEL       当前等级（1-10）

脚本不会使用 DOUYIN_ACCESS_TOKEN，每次 --execute 都用当前 client key/secret 获取新 token。
`;

function getMode(argv) {
  if (argv.includes('--help') || argv.includes('-h')) return { help: true };
  if (argv.some((value) => value !== '--execute')) throw new Error('仅支持 --execute；请运行 --help 查看说明。');
  return { execute: argv.includes('--execute') };
}

function validate(value) {
  if (!/^\d+$/.test(value.accountId)) throw new Error('account_id 必须是数字形式的来客商户根账户ID。');
  if (!value.openId || /\s/.test(value.openId) || /^test_mobile_change_openid_/.test(value.openId)) {
    throw new Error('open_id 必须是平台实际分配且已经入会的测试会员 open_id，不能自行生成。');
  }
  if (!/^1\d{10}$/.test(value.mobile) && !/^\+[1-9]\d{1,14}$/.test(value.mobile)) {
    throw new Error('手机号格式不正确：中国手机号使用11位数字且不要带 +86。');
  }
  if (value.mobile.startsWith('+86')) throw new Error('中国手机号不要带 +86。');
  if (!/^\d+$/.test(value.points) || !Number.isSafeInteger(Number(value.points))) throw new Error('当前积分*100 必须是安全整数。');
  if (!/^(?:[1-9]|10)$/.test(value.level)) throw new Error('当前等级必须是 1 到 10。');
}

function makePayload(value) {
  validate(value);
  return { account_id: value.accountId, members: [{ open_id: value.openId, points_amount_cent: Number(value.points), user_level: Number(value.level), update_time: Math.floor(Date.now() / 1000), new_mobile: value.mobile }] };
}

function safe(value) {
  return JSON.stringify(value, (key, item) => /token|secret|mobile|phone/i.test(key) ? '[REDACTED]' : item, 2);
}

function isSuccess(body) {
  const zero = (value) => value === 0 || value === '0';
  return zero(body?.data?.error_code) && (body?.extra?.error_code === undefined || zero(body.extra.error_code)) && (body?.extra?.sub_error_code === undefined || zero(body.extra.sub_error_code));
}

function logids(body) {
  return [...new Set([body?.log_id, body?.logid, body?.extra?.logid].filter(Boolean))];
}

async function main() {
  const mode = getMode(process.argv.slice(2));
  if (mode.help) { console.log(HELP); return; }
  if (!process.env.DOUYIN_CLIENT_KEY || !process.env.DOUYIN_CLIENT_SECRET) throw new Error('当前 .env 缺少 DOUYIN_CLIENT_KEY 或 DOUYIN_CLIENT_SECRET。');
  const rl = process.stdin.isTTY ? readline.createInterface({ input: process.stdin, output: process.stdout }) : null;
  const ask = async (label, envName) => process.env[envName]?.trim() || (rl ? (await rl.question(`${label}: `)).trim() : '');
  try {
    const value = {
      accountId: await ask('抖音测试店铺来客根账户ID', 'DOUYIN_TEST_ACCOUNT_ID'),
      openId: await ask('已入会测试会员 open_id', 'DOUYIN_TEST_MEMBER_OPEN_ID'),
      mobile: await ask('新的测试手机号', 'DOUYIN_TEST_NEW_MOBILE'),
      points: await ask('当前积分*100', 'DOUYIN_TEST_POINTS_AMOUNT_CENT'),
      level: await ask('当前会员等级(1-10)', 'DOUYIN_TEST_USER_LEVEL'),
    };
    const body = makePayload(value);
    console.log('使用应用 ClientKey:', process.env.DOUYIN_CLIENT_KEY);
    console.log('请求预览（手机号已隐藏）：\n', safe(body));
    if (!mode.execute) { console.log('\nDRY RUN：未发送请求。确认测试身份后再增加 --execute。'); return; }
    const config = { timeout: 20000, maxRedirects: 0, validateStatus: () => true };
    const tokenResponse = await axios.post(TOKEN_URL, { client_key: process.env.DOUYIN_CLIENT_KEY, client_secret: process.env.DOUYIN_CLIENT_SECRET, grant_type: 'client_credential' }, { ...config, headers: { 'content-type': 'application/json' } });
    const token = tokenResponse.data?.data?.access_token;
    if (tokenResponse.status !== 200 || !token || !isSuccess(tokenResponse.data)) { console.log(`获取 client_token 失败（HTTP ${tokenResponse.status}）：\n`, safe(tokenResponse.data)); return; }
    console.log('client_token 已获取（不打印），正在只提交一次会员手机号更新...');
    const response = await axios.post(UPDATE_URL, body, { ...config, headers: { 'access-token': token, 'content-type': 'application/json' } });
    console.log(`接口响应（HTTP ${response.status}）：\n`, safe(response.data));
    const ids = logids(response.data);
    if (response.status !== 200 || !isSuccess(response.data)) {
      console.log('\n失败：这个 logid 不能作为成功验收 logid。');
      if (ids.length) console.log('故障排查 logid:', ids.join(', '));
      if (response.data?.data?.error_code === 2190002) console.log('2190002 表示 access_token 无效。请勿重复提交改号，先确认脚本目录、应用 ClientKey 和当前控制台应用一致。');
      return;
    }
    if (ids.length !== 1) { console.log('\n接口业务成功，但 logid 缺失或不唯一，不能直接提交验收。'); return; }
    console.log(`\n候选 API logid（仅在响应业务成功时有效）：${ids[0]}`);
    console.log('先在当前应用的“排查工具→日志查询”确认该日志，再填入验收页面。');
  } finally { rl?.close(); }
}

main().catch((error) => { console.error('脚本未执行：', error.message); process.exitCode = 1; });
