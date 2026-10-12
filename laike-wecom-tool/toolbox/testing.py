"""专用测试群配置；使用独立测试企业，不需要真实抖音商户或门店 ID。"""
import time


TEST_GROUP_NAME = "壹心-湖南-测试消息店"
TEST_GROUP_ID = "test-wecom-yixin-hunan"
TEST_ACCOUNT_ID = "__test_yixin_hunan__"
TEST_POI_ID = "test-only-yixin-hunan"


def test_group(db):
    store = db.one("SELECT s.*,e.account_id,e.name AS enterprise_name,e.is_test FROM stores s "
                   "JOIN enterprises e ON e.id=s.enterprise_id WHERE e.account_id=? AND e.is_test=1 AND s.poi_id=?",
                   (TEST_ACCOUNT_ID, TEST_POI_ID))
    return {"group_name": TEST_GROUP_NAME, "group_id": TEST_GROUP_ID,
            "configured": bool(store), "store": store}


def prepare_test_group(db):
    with db.connect(write=True) as c:
        enterprise = c.execute("SELECT * FROM enterprises WHERE account_id=?", (TEST_ACCOUNT_ID,)).fetchone()
        if enterprise and not enterprise["is_test"]:
            raise ValueError("测试企业标识已被业务配置占用，请先检查企业设置")
        if not enterprise:
            enterprise_id = c.execute("INSERT INTO enterprises(account_id,name,is_test,created_at) VALUES (?,?,1,?)",
                                      (TEST_ACCOUNT_ID, "壹心 · 测试专用", time.time())).lastrowid
        else:
            enterprise_id = enterprise["id"]
        store = c.execute("SELECT * FROM stores WHERE enterprise_id=? AND poi_id=?",
                          (enterprise_id, TEST_POI_ID)).fetchone()
        collision = c.execute("SELECT id FROM stores WHERE (group_id=? OR group_name=?) AND id<>?",
                              (TEST_GROUP_ID, TEST_GROUP_NAME, store["id"] if store else 0)).fetchone()
        if collision:
            raise ValueError("该测试群已经被其他门店绑定，请先解除原绑定后再配置专用测试群")
        if store:
            if (store["group_id"], store["group_name"]) != (TEST_GROUP_ID, TEST_GROUP_NAME):
                raise ValueError("专用测试群绑定已被修改，请先检查门店设置")
        else:
            c.execute("INSERT INTO stores(enterprise_id,poi_id,name,group_id,group_name,created_at) VALUES (?,?,?,?,?,?)",
                      (enterprise_id, TEST_POI_ID, TEST_GROUP_NAME, TEST_GROUP_ID, TEST_GROUP_NAME, time.time()))
            db.audit("配置专用测试群", enterprise_id, TEST_GROUP_NAME, c)
    return test_group(db)
