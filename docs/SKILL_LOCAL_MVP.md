# Skill System Safe Local MVP

本文件记录 Roadmap Completion Autopilot 中的 Skill System 最小安全实现。

## 定位

Skill 在本阶段只是 **local fixture capability descriptor**：

- 读取显式传入的 `tmp_path` 或 `tests/fixtures/skills`。
- 解析 `SKILL.md` 的 name、description、allowed-tools、metadata 和指令正文。
- 生成只读 descriptor，供后续 parent runtime / policy 决定是否使用。

它不是：

- 真实 skill installer。
- 远程 marketplace。
- 任意代码执行入口。
- 子 agent。
- runtime activation。
- tool policy bypass。

## Safety rules

- no real skill dirs
- no network install
- no arbitrary code execution
- no env expansion
- no secret output
- no direct tool execution by skill
- parent runtime remains in control
- allowed tools are declarative metadata only

`agent.skills.local` therefore does not import installer, tool executor, runtime,
subprocess, or network modules。旧 `agent.skills.installer` 仍是历史原型，不属于本
MVP 的默认路径。

## Fixture example

`tests/fixtures/skills/safe-writer/SKILL.md` 是当前唯一 safe local fixture。它只说明
写作指导，不会执行命令、下载依赖、读取私人目录或连接外部服务。

## Fake dogfood example

Fake dogfood 只验证 descriptor 和展示输出，不执行 skill，也不调用 tool：

1. 读取 `tests/fixtures/skills/safe-writer/SKILL.md`。
2. 调用 `load_local_skill_descriptor(...)` 得到 descriptor。
3. 调用 `format_skill_descriptor_for_display(...)` 观察 redacted 输出。
4. 人工确认 `direct_tool_execution_allowed=False`，`parent runtime remains in control`。

这个示例故意不使用真实 skill dirs、不触发 installer、不执行 `allowed-tools`。

## Validation evidence

`tests/test_skill_local_mvp_contract.py` 覆盖：

- valid fixture skill accepted as descriptor only
- invalid manifest rejected
- unsafe path rejected
- secret-like content redacted
- command/network install/tool bypass rejected
- no runtime/network/installer dependencies
