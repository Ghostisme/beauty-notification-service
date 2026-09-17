/**
 * 订单处理主脚本
 * 完整流程: access_token → 多商户订单列表 → 订单详情 → 解密 → 提取字段
 *
 * 使用方法:
 * 1. 查看所有商户的订单列表(不处理详情):
 *    node src/process-orders.js list
 *
 * 2. 完整处理(获取详情+解密+提取):
 *    node src/process-orders.js process [每个商户订单数]
 *
 * 3. 保存为JSON:
 *    node src/process-orders.js export [每个商户订单数]
 */

require('dotenv').config();
const DouyinModule = require('./modules/douyin');
const OrderProcessor = require('./modules/douyin/order-processor');

const douyin = new DouyinModule();
const processor = new OrderProcessor(douyin);

/**
 * 命令: 列出所有商户的订单(不处理详情)
 */
async function commandList() {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   多商户订单列表查询                   ║');
  console.log('╚════════════════════════════════════════╝\n');

  const results = await processor.processMultipleAccounts({
    ordersPerAccount: 10,
    processDetails: false, // 只获取列表
  });

  console.log('\n📊 查询结果:\n');

  results.accountResults.forEach((account) => {
    console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    console.log(`商户: ${account.accountName}`);
    console.log(`账户ID: ${account.accountId}`);
    console.log(`区域: ${account.region}`);
    console.log(`订单数: ${account.ordersCount}`);

    if (account.error) {
      console.log(`❌ 错误: ${account.error}`);
    }

    console.log('');
  });

  console.log(`\n总计: ${results.totalOrders} 个订单(来自 ${results.processedAccounts} 个商户)\n`);
}

/**
 * 命令: 完整处理(详情+解密+提取)
 */
async function commandProcess(ordersPerAccount = 5) {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   多商户订单完整处理                   ║');
  console.log('╚════════════════════════════════════════╝\n');

  const results = await processor.processMultipleAccounts({
    ordersPerAccount: parseInt(ordersPerAccount),
    processDetails: true, // 完整处理
  });

  console.log('\n📋 处理结果:\n');

  results.accountResults.forEach((account) => {
    console.log(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    console.log(`商户: ${account.accountName} (${account.region})`);
    console.log(`处理: ${account.processedOrders.length}/${account.ordersCount} 成功\n`);

    if (account.processedOrders.length > 0) {
      account.processedOrders.slice(0, 3).forEach((order, index) => {
        console.log(`订单 ${index + 1}:`);
        console.log(`  📱 客户: ${order.customerPhone}`);
        console.log(`  🕐 时间: ${order.orderTime}`);
        console.log(`  🛍️  商品: ${order.productName}`);
        console.log(`  📦 类型: ${order.orderType}`);
        console.log(`  💰 金额: ${order.actualPrice} 元`);
        console.log(`  🏪 店铺: ${order.shopName}`);
        console.log(`  📊 状态: ${order.orderStatus}`);
        console.log('');
      });

      if (account.processedOrders.length > 3) {
        console.log(`  ... 还有 ${account.processedOrders.length - 3} 个订单\n`);
      }
    }

    if (account.failedOrders.length > 0) {
      console.log(`❌ 失败: ${account.failedOrders.length} 个订单`);
    }
  });

  console.log(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
  console.log('📊 汇总统计:\n');
  console.log(`  商户数: ${results.processedAccounts}`);
  console.log(`  总订单: ${results.totalOrders}`);
  console.log(`  成功处理: ${results.processedOrders}`);
  console.log(`  失败: ${results.failedOrders}`);
  console.log('');
}

/**
 * 命令: 导出为JSON
 */
async function commandExport(ordersPerAccount = 5) {
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║   导出订单数据                         ║');
  console.log('╚════════════════════════════════════════╝\n');

  const results = await processor.processMultipleAccounts({
    ordersPerAccount: parseInt(ordersPerAccount),
    processDetails: true,
  });

  // 保存到文件
  const fs = require('fs');
  const timestamp = Date.now();
  const outputFile = `orders_export_${timestamp}.json`;

  fs.writeFileSync(outputFile, JSON.stringify(results, null, 2));

  console.log(`\n✅ 数据已导出到: ${outputFile}\n`);
  console.log('文件包含:');
  console.log(`  - ${results.processedAccounts} 个商户的数据`);
  console.log(`  - ${results.processedOrders} 个完整处理的订单`);
  console.log(`  - 包含解密后的客户信息和5个核心字段`);
  console.log('');
}

/**
 * 主函数
 */
async function main() {
  const args = process.argv.slice(2);
  const command = args[0];

  if (!command) {
    console.log('\n订单处理脚本 - 多商户支持');
    console.log('═══════════════════════════════════════\n');
    console.log('使用方法:\n');
    console.log('1. 查看订单列表(不处理详情):');
    console.log('   node src/process-orders.js list\n');
    console.log('2. 完整处理(详情+解密+提取):');
    console.log('   node src/process-orders.js process [每个商户订单数]\n');
    console.log('3. 导出为JSON:');
    console.log('   node src/process-orders.js export [每个商户订单数]\n');
    console.log('示例:\n');
    console.log('   node src/process-orders.js list');
    console.log('   node src/process-orders.js process 5');
    console.log('   node src/process-orders.js export 10\n');
    console.log('配置文件: data/accounts.json\n');
    process.exit(0);
  }

  try {
    switch (command) {
      case 'list':
        await commandList();
        break;

      case 'process':
        await commandProcess(args[1] || 5);
        break;

      case 'export':
        await commandExport(args[1] || 5);
        break;

      default:
        console.error(`❌ 未知命令: ${command}`);
        console.log('可用命令: list, process, export');
        process.exit(1);
    }

    console.log('✅ 执行完成\n');
  } catch (error) {
    console.error('\n❌ 执行失败:', error.message);
    console.error('\n详细错误:', error);
    process.exit(1);
  }
}

main();
