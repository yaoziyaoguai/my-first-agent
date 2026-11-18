# Release Notes

## v1.0.0（2026-11-18，项目收官）

First Agent v1.0.0 是本项目的完结版本，范围为「可自然语言驱动、受治理地完成本地
任务的个人 Agent」：macOS、单用户、CLI。功能开发到此结束；此后仅处理已声明
日用范围内可复现的阻断缺陷。后台服务、多平台运行时和多用户产品留给独立目标。

- **代码与版本身份**：冻结代码 `4af348a`，已发布 tag `v1.0.0` 指向 `124c898`。
  此后的最终整理仅涉及文档和配图，不移动既有 tag。收官实测 wheel 为
  `first_agent-1.0.0-py3-none-any.whl`，sha256
  `18f0f05af96e47c99509155a584634b52048c21ed3e22007a9864de43b093811`。
  该摘要只绑定当时验收安装物；README 等打包元数据变化后的重建物应独立核对摘要。
- **交付范围**：多轮对话、确定性上下文构建、串行工具与精确审批（digest 绑定）、
  `local_process` / `sandbox_exec` / `shell_exec`、文件读写与工作区检索、
  安全边界自动压缩、checkpoint 恢复、`/new`、`/pause`、`/resume`、`/switch`，
  `/project-path` 与 `/env-path` 会话内准入、有限授权复用和可选 Tavily 公开 Web。
  `local_process` 是当前用户权限的本机执行，不能当作 OS 沙箱。密钥只从环境变量注入。
- **收官自动门**：4362 passed / 3 skipped / 0 failed；干净 venv 安装验证 6/6 PASS。
  安装旅程的 provider 是 scripted fake，真实模型证据由下一项单列。
- **真实模型验证**：DeepSeek Flash、冻结 d04 协议，共 59 次请求。
  **E1 PASS、E3 PASS（零写契约）**；E2 首跑 `INCOMPLETE_EVIDENCE`，
  非法控制响应耗尽修复额度后安全停止；唯一一次有界复跑中，纠正、暂停和
  新进程恢复治理链 10/10 通过，但一条业务要求被误实现，结果为
  **`FAIL_FALSE_COMPLETION`**。不把该失败改记为 PASS，也不以此证明“产品零缺陷”。
  本轮未定位新的 Runtime 治理实现缺陷；按既定停止条件结束，不继续重跑。
- **可选入口与限制**：Scheduler 安装命令缺少可运行 host composition，返回
  `needs_019_config`；TUI 保持实验性，暂停后外发决定的重显已修复，但不宣称与
  CLI 完全对等；Browser / Skill / MCP 的当前第三方适配与真实验证范围有限。
  收官真实模型旅程只使用一个 DeepSeek 配置，不能外推其它 provider、模型或平台。
- **使用须知**：`Verified delivery` 只说明登记证据项通过。使用者仍需检查 diff、
  独立测试和关键反例；请提前准备任务项目依赖，必要时使用 `/env-path`。
  安装与操作见 [README](../README.md)、[日用指南](guides/daily-use.md) 和
  [进阶配置](guides/advanced-configuration.md)。
- **留档选择**：自助恢复增强、Memory 增强、TUI 完整对齐、019 host composition、
  真实数据源普适集成等不再是本项目待办。只有明确改变产品目标才重新定范围。

收官详情见 [STATE](handoffs/2026-10-25-continuous-improvement/STATE.md)。其中
`previews/...` 为仓库外本机证据，未随仓库发布；历史验收材料继续绑定原始身份。
