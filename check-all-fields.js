require('dotenv').config();
const DouyinModule = require('./src/modules/douyin');

const douyin = new DouyinModule();

async function main() {
  await douyin.init();

  console.log('\n=== 检查两个商户的订单数据结构差异 ===\n');

  // 商户1: 长沙
  const order1 = await douyin.getOrderDetail('1086675889370262734', '7523898493467904038');
  console.log('商户1 (长沙) - contacts:');
  console.log(JSON.stringify(order1.contacts, null, 2));
  console.log('\nphone_encrypt 字段:', order1.contacts?.[0]?.phone_encrypt || '(不存在)');

  console.log('\n' + '='.repeat(50) + '\n');

  // 商户2: 许昌
  const order2 = await douyin.getOrderDetail('1091962674194265394', '7605435122824890377');
  console.log('商户2 (许昌) - contacts:');
  console.log(JSON.stringify(order2.contacts, null, 2));
  console.log('\nphone_encrypt 字段:', order2.contacts?.[0]?.phone_encrypt || '(不存在)');

  console.log('\n' + '='.repeat(50) + '\n');

  // 检查是否有其他包含手机号的字段
  console.log('商户2订单中所有字段:');
  console.log(Object.keys(order2));

  console.log('\n\n=== 查找可能包含加密手机号的字段 ===\n');
  
  function findEncryptedFields(obj, prefix = '') {
    const results = [];
    for (const [key, value] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (typeof value === 'string' && value.startsWith('Enc.')) {
        results.push({ path, value });
      } else if (typeof value === 'object' && value !== null) {
        results.push(...findEncryptedFields(value, path));
      }
    }
    return results;
  }

  const encrypted = findEncryptedFields(order2);
  if (encrypted.length > 0) {
    console.log('找到加密字段:');
    encrypted.forEach(f => console.log(`  ${f.path}: ${f.value.substring(0, 50)}...`));
  } else {
    console.log('❌ 没有找到任何 Enc. 开头的加密字段');
  }
}

main();
