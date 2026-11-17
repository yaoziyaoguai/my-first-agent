# Release Notes

## v1.0.0（2026-11-18，项目收官）

First Agent v1.0.0 是本项目的完结版本。范围裁决（oracle 收官审计
`mfa-project-closure-audit-2026-11-18`）：**通用 Agent ≠ 全功能 Agent**——以
「可自然语言驱动、受治理地完成本地任务的个人 Agent」完结，此后只接受能在已声明
日用范围内复现的阻断缺陷；后台自动化服务、多平台运行时、远程工具生态与多用户
产品不属于本项目范围。

- **冻结代码身份**：`4af348a`（release tag `v1.0.0` 标记收官终 commit，其后仅
  文档提交）。wheel：`first_agent-1.0.0-py3-none-any.whl`，sha256
  `18f0f05af96e47c99509155a584634b52048c21ed3e22007a9864de43b093811`。
- **交付范围**：macOS 单用户本地 CLI。多轮对话、确定性上下文构建、串行工具与
  精确审批（digest 绑定）、`local_process`/`sandbox_exec`（Seatbelt）/
  `shell_exec`、文件读写编辑与工作区检索、压力触发安全边界压缩、checkpoint
  恢复、`/new`//`pause`//`resume`//`switch` 会话管理、`/project-path` 与
  `/env-path` 会话内准入、会话级外发许可（s/r/f/d）、固定 Tavily 公开 Web
  查询。密钥永远只从环境变量注入。
- **收官验证**（均绑定冻结身份）：完整门 4362 passed / 0 failed；干净 venv
  安装验证 6/6 PASS；真实模型层（deepseek-flash，冻结 d04 协议）E1 PASS、
  E3 PASS（零写契约）、E2 旅程治理链 10/10 闭合（业务判据按模型侧语义误解
  诚实分类收档，无产品缺陷、无新 P0/P1）。
- **诚实不可用标注**：Scheduler（Durable automations）安装入口 `needs_019_config`
  fail-closed，无可用 host composition；TUI 为实验性（存在恢复外发确认的交互
  缺口，不作日用推荐入口）；`browser`/`skill`/`mcp` extras 的非核心 adapter
  仅离线证据；非 macOS 平台不支持；anthropic_compatible 等其它 adapter 未经
  真实调用验证。
- **使用须知**：`Verified delivery` 是登记证据项的下界，不等于业务验收——
  请独立检查 diff、运行独立测试与关键反例；任务依赖请先准备（见日用指南
  「先准备任务自己的依赖」与 `/env-path`）。安装与使用说明见
  [README](../README.md) 与 [日用指南](guides/daily-use.md)。
- **留档缓议项**（不阻塞收官）：#2 自助恢复（升级触发=正常默认使用中稳定复现
  的不可恢复状态）、#5 Memory、TUI 补齐、019 host composition、#4 真实数据源
  普适集成（需单独范围裁决）。
