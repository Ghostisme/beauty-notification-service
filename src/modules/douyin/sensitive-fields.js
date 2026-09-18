/**
 * 订单敏感字段的收集与解密回填
 *
 * 抖音对手机号、姓名、证件号等做加密下发,值以 `Enc.` 前缀标识,需调用
 * crypto/decrypt/batch 换回明文。原先只收集 contacts[0].phone 一处,
 * 导致买家手机号(buyer_info)、收货人(receiver_info)、预订人证件
 * (buyer_reserve_info)等同样加密的字段拿不到明文。
 *
 * 本模块按文档列出的加密字段位置统一扫描,一次批量解密,再按路径回填,
 * 新增字段只需往 ENCRYPTED_FIELD_PATHS 里加一条路径。
 */

/** 加密值的统一前缀,抖音用它标识"这是密文" */
const ENCRYPTED_PREFIX = 'Enc.';

/**
 * 订单对象中可能出现加密值的字段路径。
 *
 * `[]` 表示该层是数组,需逐个元素展开。只列文档中明确会加密下发的字段,
 * 不做全对象暴力扫描 —— 后者会把商品名之类恰好以 Enc. 开头的业务文本误判为密文。
 */
const ENCRYPTED_FIELD_PATHS = [
  'contacts[].phone',
  'contacts[].phone_encrypt',
  'contacts[].name',
  'buyer_info.buyer_phone',
  'buyer_info.buyer_real_phone',
  'buyer_reserve_info[].enc_credential_numb',
  'buyer_reserve_info[].enc_name',
  'receiver_info.receiver_name',
  'receiver_info.receiver_phone',
  'receiver_info.receiver_real_phone',
];

/**
 * 判断一个值是否为抖音加密值。
 * @param {*} value - 待判定的值
 * @returns {boolean}
 */
function isEncrypted(value) {
  return typeof value === 'string' && value.startsWith(ENCRYPTED_PREFIX);
}

/**
 * 按路径定位到目标值所在的宿主对象。
 *
 * 返回宿主对象而非值本身,是为了让调用方能原地写回解密结果(回填场景)。
 * 数组层用 `[]` 标记并递归展开,遇到缺失的中间层直接跳过。
 *
 * @param {Object} root - 订单对象
 * @param {string} path - 形如 `contacts[].phone` 的路径
 * @returns {Array<{holder: Object, key: string}>} 命中的宿主与末级键名
 */
function resolvePath(root, path) {
  const segments = path.split('.');
  let cursors = [root];

  for (let i = 0; i < segments.length; i++) {
    const isLast = i === segments.length - 1;
    const segment = segments[i];
    const isArray = segment.endsWith('[]');
    const key = isArray ? segment.slice(0, -2) : segment;

    if (isLast) {
      // 末级不再下钻:数组末级(如 `tags[]`)取每个元素的宿主没有意义,按对象处理
      return cursors
        .filter((cursor) => cursor && typeof cursor === 'object')
        .map((cursor) => ({ holder: cursor, key }));
    }

    const next = [];
    for (const cursor of cursors) {
      const value = cursor?.[key];
      if (!value) continue;

      if (isArray) {
        if (Array.isArray(value)) next.push(...value.filter(Boolean));
      } else {
        next.push(value);
      }
    }

    if (next.length === 0) return [];
    cursors = next;
  }

  return [];
}

/**
 * 收集订单中所有待解密的密文值(已去重)。
 *
 * 去重很关键:同一手机号常同时出现在 contacts 和 buyer_info 里,
 * 重复提交会白耗解密接口的调用额度。
 *
 * @param {Object|Array<Object>} orders - 单个订单或订单数组
 * @returns {Array<string>} 去重后的密文数组
 */
function collectEncryptedValues(orders) {
  const list = Array.isArray(orders) ? orders : [orders];
  const found = new Set();

  for (const order of list) {
    if (!order) continue;

    for (const path of ENCRYPTED_FIELD_PATHS) {
      for (const { holder, key } of resolvePath(order, path)) {
        if (isEncrypted(holder[key])) found.add(holder[key]);
      }
    }
  }

  return [...found];
}

/**
 * 把解密结果原地回填到订单对象。
 *
 * 只覆盖能在映射表中查到明文的字段;解密失败的保持密文原样,
 * 让下游的降级逻辑(如改用 open_id 展示)仍有判据可依。
 *
 * @param {Object|Array<Object>} orders - 单个订单或订单数组(会被就地修改)
 * @param {Object<string, string>} decryptedMap - {密文: 明文}
 * @returns {number} 实际回填的字段数
 */
function applyDecryptedValues(orders, decryptedMap = {}) {
  if (!decryptedMap || Object.keys(decryptedMap).length === 0) return 0;

  const list = Array.isArray(orders) ? orders : [orders];
  let filled = 0;

  for (const order of list) {
    if (!order) continue;

    for (const path of ENCRYPTED_FIELD_PATHS) {
      for (const { holder, key } of resolvePath(order, path)) {
        const cipher = holder[key];
        if (!isEncrypted(cipher)) continue;

        const plain = decryptedMap[cipher];
        if (plain) {
          holder[key] = plain;
          filled++;
        }
      }
    }
  }

  return filled;
}

module.exports = {
  ENCRYPTED_PREFIX,
  ENCRYPTED_FIELD_PATHS,
  isEncrypted,
  collectEncryptedValues,
  applyDecryptedValues,
};
