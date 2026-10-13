# 给执行者的任务提示

以下整段可直接发给普通 coding agent。路径可随仓库位置调整。

---

请修复 `my-first-agent` 当前真实 dogfood 暴露的日常使用问题。你是执行者，不需要联系 Oracle/Pi，也不需要原聊天记录。

先完整读取根 `AGENTS.md`，再读：

1. `docs/handoffs/2026-09-13-dogfood-remediation/BASELINE.md`
2. 同目录 `FINDINGS.md`、`WORK-PACKAGES.md`、`VERIFICATION.md`
3. `docs/architecture/KERNEL_ARCHITECTURE.md`、`EXTENSION_CONTRACTS.md`、`CURRENT_CAPABILITY_STATUS.md`

先核对基线。工作树中已有大量未提交的修复，属于原有工作；不要 reset、覆盖、顺手重构或重复实现。默认 main，不 commit/push/tag/改 remote。若相关文件指纹已变，重新核对受影响的切片即可，不因无关改动停止全部工作。

目标是让已有能力可靠完成日常任务，不是添加更多能力。按 W1 → W2 → W3 → W4 → W5 → W6 顺序实施；W7 是证据/诊断收尾。先跑当前切片的最小复现，确认实际原因，再做最小实现。每轮把根因、Red/Green 命令、结果和偏离写入 `RESULTS.md`。同一问题没有新的诊断证据时，不重复调用真实模型碰运气。

必须保持：`AgentRuntime.run_turn` 唯一 model/tool loop；ContextManager 选上下文、ToolRuntime 调 callable；CLI/TUI/headless 只翻译 typed action 和展示结果。effects 必须经过 policy/approval、durable EXECUTING 和结果 checkpoint。不得放宽 source admission、no-follow、exact binding、外发批准或 unknown-effect recovery。不要把所有请求强制建 Goal，也不能让有副作用的任务以一段文本假装完成。

安全范围：只读代码和本包内脱敏材料；不要读 `.env`、真实凭据/日志/会话/Memory/MCP/Skill 私有目录，或未跟踪的根 `tui/`。已跟踪的 `agent/runtime/`、`agent/memory/`、`agent/tui/` 是源码，可以读改。测试使用新建临时 fixture，不触碰用户文件、个人 Chrome、登录项、launchd、真实第三方账号或生产服务。

离线测试不需要密钥。真实回归仅在用户已为本次运行提供临时凭据并授权后进行；本包不含 key，也不授权你从 Pi、Claude 或聊天历史找 key。历史记录曾使用已失效的 `deepseek-flash` 短名；当前官方模型 ID 是 `deepseek-v4-flash`，这里仍采用非 strict、thinking disabled。不要自动换成旧 `deepseek-chat`、GLM 或别的 provider。只上传合成测试材料，按验证文档限制调用数并记录实际消费；无凭据时完成全部离线工作，真实验证标为 BLOCKED，不编造 PASS。

下列情况先写窄设计并请求用户决定，不自行扩大范围：必须引入新完成证据类型、改 checkpoint schema、自动取消/新建 Goal、迁移旧偏好、扩大预授权、自动创建父目录、改变进程隔离或增加后台常驻。其余清楚、可逆的修复自主完成，不每改一处就询问“是否继续”。

收尾时对最终候选运行 touched-area tests、`git diff --check`、Ruff 和一次全量 pytest；必要的全量重跑只针对后来确实变化的候选。构建非 editable wheel 验证实际安装路径，再做有预算的真实任务回归。任何失败、跳过、超时或中断都写清楚。全部通过才叫修复完成；否则明确完成了哪些、还卡在哪里。

最后交付：修改文件、逐问题状态、复现/回归证据、实际模型调用计数及未验证边界。不要宣称 production-ready 或全能力验收通过。

---
