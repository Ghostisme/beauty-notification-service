// 正式实例的只读界面检查；不会创建订单、留资、测试消息或执行发送。
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
const fs = require('fs');
const path = require('path');
let browser;

(async () => {
  const base = process.env.TOOL_TEST_URL || 'http://127.0.0.1:8790';
  const output = path.resolve(process.env.TOOL_LIVE_CHECK_OUTPUT || 'data');
  const password = process.env.TOOL_TEST_PASSWORD || fs.readFileSync(
    process.env.TOOL_TEST_PASSWORD_FILE || 'data/.bootstrap-password', 'utf8').trim();
  fs.mkdirSync(output, {recursive:true});
  browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined});
  const context = await browser.newContext({viewport:{width:1440,height:1080},locale:'zh-CN',timezoneId:'Asia/Shanghai'});
  const page = await context.newPage();
  const errors=[], checks=[];
  page.on('pageerror', error=>errors.push(error.message));
  page.on('response', response=>{if(response.status()>=500)errors.push(`${response.status()} ${response.url()}`);});
  await page.goto(base);
  await page.locator('#login-form input[name=password]').fill(password);
  await page.locator('#login-form button[type=submit]').click();
  await page.locator('#main-content h1').waitFor();
  const session = await (await page.request.get(base+'/api/session')).json();
  if(session.demo)throw new Error('真实界面检查需要正式实例');
  if(await page.locator('#demo-badge').textContent()!=='正式环境')throw new Error('运行环境标记不正确');
  checks.push('正式实例登录与环境标记');
  for(const target of ['dashboard','messages','stores','templates','tasks','settings']) {
    await page.locator(`aside button[data-page=${target}]`).click();
    await page.waitForFunction(()=>!document.querySelector('#main-content .loading'));
    if(await page.getByText('暂时无法读取数据',{exact:true}).count())throw new Error(`${target} 页面未能读取`);
    checks.push(`正式实例页面 ${target}`);
  }
  await page.locator('.connection-panel h2').getByText('真实接入检查',{exact:true}).waitFor();
  checks.push('真实接入状态逐项展示');
  const mode = await page.locator('#channel-form select[name=mode]').inputValue();
  await page.locator('#channel-form select[name=mode]').selectOption('relay');
  if(await page.locator('#http-fields').isVisible())throw new Error('Windows 模式不应展示 HTTP 凭证字段');
  await page.locator('#channel-form select[name=mode]').selectOption('http');
  if(!await page.locator('#http-fields').isVisible())throw new Error('HTTP 模式应展示接口字段');
  await page.locator('#channel-form select[name=mode]').selectOption(mode);
  checks.push('发送方式对应字段切换，不保存配置');
  const address = await page.getByLabel('发送端服务器地址',{exact:true}).inputValue();
  if(address!==new URL(base).origin)throw new Error('发送端连接地址不正确');
  checks.push('显示实际后台地址');
  await page.locator('.connection-panel').screenshot({path:path.join(output,'live-readiness.png')});
  const status = await (await page.request.get(base+'/api/connections')).json();
  const result = {mode:'formal',read_only:true,checks,errors,connections:status.items.map(
    item=>({key:item.key,state:item.state,checked_at:item.checked_at}))};
  fs.writeFileSync(path.join(output,'browser-live-check.json'),JSON.stringify(result,null,2));
  if(errors.length)throw new Error(errors.join('\n'));
  await browser.close();browser=null;
  console.log(JSON.stringify({mode:result.mode,read_only:true,checks:checks.length,errors},null,2));
})().catch(async error=>{if(browser)await browser.close();console.error(error.message);process.exitCode=1;});
