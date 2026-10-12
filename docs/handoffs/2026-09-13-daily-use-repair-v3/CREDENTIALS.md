# 后续执行的凭据与网络边界

资料包制作阶段不读取 key、不发真实请求。用户此前明确提供的最新 DeepSeek 凭据已保存在本机仓库外的以下精确文件：

`/Users/jinkun.wang/.local/share/first-agent-qa-credentials.7SIayu/deepseek.key`

这是用户已授权用于 First Agent 合成 dogfood 的特定路径；不扩大到其他 Agent 配置或凭据目录。上轮该 key 曾成功完成认证及合成任务，不能引用更早一次失败断言它目前无效；本包准备没有再次验证有效性。原明文不写进资料包、manifest、测试、Git、参数或模型输入。

执行本包时，先通过 D0 再加载凭据。复用前包 `docs/handoffs/2026-09-13-qa-repair-v2/launch_deepseek.py` 的 owner-only/no-follow/单链接/有界读取与环境注入做法；该旧脚本**没有强制预算，也不支持本包新参数，不能直接拿来启动本轮真实测试**。在 D0 中补齐可检查的 launcher，然后验证合成 key + MockTransport 的零泄漏/拒绝分支。

参数固定为最近已使用的便宜模型配置：

- provider：openai_compatible
- model：deepseek-v4-flash（2026-09-13 官方正式 ID；`deepseek-flash` 短名不在当前模型枚举内）
- base URL：https://api.deepseek.com
- request path：/chat/completions
- thinking：disabled
- strict tools：false
- credential env：FIRST_AGENT_DOGFOOD_API_KEY
- HTTP timeout：90s

这是已使用配置，不保证执行日服务状态。联网前只核对 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/)；如模型/服务确实变更则记录，不静默切换供应商或高价模型。普通 core 测试不启用 Web、Browser、SubAgent，也不读取外部内容作为 prompt。

launcher 只向产品 composition root 注入环境值和显式参数。原旧脚本继承 ambient 环境，接手时应收窄到已验证必要变量；不要打印环境，不让其他 model key、代理凭据进入验证子进程。不能设置 PYTHONPATH 或 monkeypatch 覆盖 installed 产品。

使用文件前以 no-follow 打开校验父目录 owner/0700、文件 owner/0600、regular/单链接与读取长度；缺失或不安全时停止真实行，继续其他离线工作。同一确定性 401/403 不重复请求，记录脱敏错误码和 attempts，不能凭错误推断欠费、撤销或 token 是否计费。

这条本机凭据路径不随仓库搬迁。另一台机器由操作者使用其安全凭据注入渠道提供；没有凭据仍应完成 D0–D4 和安装回归，D5 标 BLOCKED。整个执行窗口最多 40 次，每 journey 最多 8 次，执行层强制方法见 VERIFICATION。
