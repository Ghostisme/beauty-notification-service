# Mac 发送端与操作手册验证记录

日期：2026-10-13。目标环境为 Apple 芯片 Mac、Python 3.12、macOS 13 或更新版本；发送目标仍是现有企微外部客户群。执行本次开发与检查的机器是 Windows，不是 Mac。

## 本次新增

- Windows / Mac 自动选择桌面驱动，共用完整群名核对、发送前持久化和发送后业务编号核对流程。
- Mac 使用系统屏幕录制与辅助功能权限、Quartz 窗口和输入控制、Vision 简体中文识别、系统窗口截图；Retina 像素与窗口逻辑坐标分别处理。
- Apple 芯片原生 Python 3.12 启动入口，检查 Rosetta 和 Tk，安装 Mac 专用依赖；运行期间用 `caffeinate` 阻止自动休眠。手动锁屏、合盖或退出登录仍会停止可交互发送。
- 双击测试、正式启动、重新校准、连接检查、负责群选择入口；Windows 同时新增选群入口。初次配置限测试群，正式群须明确选择。
- 每台电脑使用不同且稳定的默认身份；既有配置的身份和账本保持有效。Windows / Mac 校准文件不混用。
- 校准增加刷新截图及取消后停止启动，Mac 可选择 Enter、Command+Enter 或 Ctrl+Enter。
- 通俗中文操作手册及浏览器版、后台入口、移动布局与打印样式；修正部署手册中过时的线索和手机号状态。

## 本次实际执行的检查

| 检查 | 实际结果 | 证据边界 |
| --- | --- | --- |
| 自动回归 | 全部 144 项通过，包含新增 20 项 Mac / 群范围用例 | 原生框架与桌面动作由测试夹具替代，不证明 Mac 真机发群 |
| Retina 与外接屏 | 2x 图像识别结果按逻辑点点击，负屏幕原点用例通过 | 逻辑约定测试，不是实际外接显示器测试 |
| 发送停止与不明结果 | 权限不足、锁屏、尺寸变化、错误群、焦点丢失不提交；提交后确认失败保留 uncertain，不盲目重发 | 测试夹具验证共同流程与本机账本 |
| Mac Python 依赖 | 13 个包及其传递依赖已解析并成功下载；原生包为 CPython 3.12 ARM64 或 universal2 wheel | 跨平台下载，不是在 Mac 执行安装或导入框架 |
| 框架 API | 对照 PyObjC 官方绑定及相应测试，核对权限、会话字典、识别请求与输出参数 | 代码与元数据核对，仍需实机调用 |
| Bash 入口 | Git Bash 语法检查通过，空参数数组已改为兼容 Mac Bash 3.2 的非空数组 | Git Bash 不是 Mac `/bin/bash`，Mac 实际启动未验证 |
| 前端脚本 | JavaScript 语法检查通过 | 不代表客户端发送 |
| 手册与本机正式后台 | 13 项只读浏览器检查通过、0 个页面脚本错误；桌面及手机布局无水平溢出，打印模式隐藏目录 | 实际读取正式本机后台，没有修改业务设置或发送消息 |
| 业务状态 | 自动发送保持关闭，完整号码要求保持开启 | 没有新增真实发群操作 |

本机后台启动后仍按原配置每 120 秒执行真实同步，程序运行数据仅在忽略目录；没有连接阿里云改配置，也没有修改旧 Node 项目或其他数据库。

## 尚需在真实 Mac 和云端执行

1. 安装原生 Python，首次系统权限授权，验证目标 Mac 上的企微应用身份及主窗口能找到。
2. 按实际客户端界面校准，核对搜索弹层、顶部群名、发送快捷键和中文 OCR。
3. 使用 `壹心-湖南-测试消息店` 完成一条真实业务消息发送，核对群内内容及后台结果。
4. 测试锁屏恢复、焦点被其他应用占用、窗口变化、不明结果核对，以及需要使用的显示器环境。
5. 阿里云部署、现有 HTTPS 域名切换、云端抖音白名单及新订单 / 留资 / 状态变化验收。

按 [操作手册](操作手册.md) 第 01、03、05、06 节执行；未做的项目不计为完成。此前 Windows 发出的单条历史订单属于 Windows 历史证据，不能用于声称 Mac 已实测成功。

## 依据

- [Apple 辅助功能授权](https://support.apple.com/zh-cn/guide/mac-help/mh43185/mac)
- [Apple 屏幕录制权限](https://support.apple.com/zh-cn/guide/mac-help/mchld6aa7d23/mac)
- [Apple Vision 文本识别请求](https://developer.apple.com/documentation/vision/vnrecognizetextrequest)
- [PyObjC 安装说明](https://pyobjc.readthedocs.io/en/latest/install.html)
- [PyObjC Quartz 绑定说明](https://pyobjc.readthedocs.io/en/latest/apinotes/Quartz.html)
- [企业微信创建企业群发](https://developer.work.weixin.qq.com/document/path/92135)
