# Round 017：冻结前关键合同闭合计划

状态：已完成
说明：这里的 Round 017 是 004–016 优化轮次之后的审计闭合编号，不是产品能力 017。

## 目标

在不增加新能力、不改变 Runtime 所有权的前提下，闭合三个已经复现的合同缺陷：

1. Memory 不得写出下一次无法读取的 durable store。
2. SubAgent 的 child 结果必须以完整 UTF-8 JSON envelope 服从 parent 的 8192-byte 上限。
3. Provider strict 投影不得误删与 schema keyword 同名的业务属性；开放 object 必须明确 fail closed。

## 外部审计依据

- Oracle Web session：`first-agent-r17-contract-closure-packet-20260909-c4e8`
- 档位：`Pro，第 5 项，共 5 项`
- 结果：`PROCEED`，建议按 Memory → SubAgent → Provider 串行执行，完成后冻结。
- 产品裁决：三项都修复“普通任务中会遇到的错误失败”，不扩展能力；不得借机引入配额服务、流式 RPC、完整 JSON Schema 框架或 Provider fallback。

## 固定边界

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop。
- `ContextManager`、`ToolRuntime`、Provider adapter 的既有所有权不变。
- 不新增第二套 loop、schema framework、fallback、自授权、后台 drain、迁移或自动清理。
- 不提高 Memory 上限，不改变 SubAgent timeout/cleanup receipt，不修改 Skill entrypoint ToolSpec 来伪造 strict 兼容。
- 不读取秘密、`.env`、真实凭据、私有运行数据或未跟踪 `tui/`。
- 不 commit、push、tag、修改 remote。
- 三个 Pi executor 串行运行；每个 executor 只能编辑自己的 ownership。

## Slice 1：Memory 写前容量合同

允许编辑：

- `agent/memory/contracts.py`
- `agent/memory/store.py`
- `agent/memory/tools.py`
- `agent/memory/preferences.py`
- `tests/memory/test_store.py`
- `tests/memory/test_tools.py`
- `tests/memory/test_owner_preferences.py`

验收合同：

- 以完整序列化 bytes 为唯一容量依据；`len(document) == _MAX_STORE_BYTES` 接受，超过才拒绝。
- 新增窄异常 `MemoryCapacityError`，只能在临时文件、截断、写入或 replace 之前抛出。
- 拒绝后旧 durable bytes、实例 revision、实例 records 不变；不得触碰已有 temp 文件。
- `create()` 的初始序列化先于目标文件创建；不引入新的初始化机制。
- Memory mutation 与 OwnerPreference mutation 精确映射容量拒绝为 `KnownNotExecuted`；普通 store/I/O 错误仍走既有不确定结果路径。
- 先写行为 Red，再做最小 Green；不得用 import error、skip 或 xfail 充当 Red。

Focused proof：

```bash
.venv/bin/python -m pytest -q -rx tests/memory/test_store.py tests/memory/test_tools.py tests/memory/test_owner_preferences.py
```

## Slice 2：SubAgent UTF-8 envelope 合同

允许编辑：

- `agent/subagent/contracts.py`
- `agent/subagent/child.py`
- `agent/subagent/process_runner.py`
- `tests/subagent/test_process_runner.py`

验收合同：

- 一个 leaf 常量定义 8192-byte result envelope 上限，producer 与 consumer 共用。
- child 保留 4000 字符产品上限，并按完整 JSON 编码成本选择 message 的最大字符前缀。
- 输出必须是完整有效 UTF-8 JSON；短消息原样保留，status 不变，不新增字段。
- parent 继续执行 `max_bytes + 1` 检测；不改变 parser、deadline、stderr、process group 或 cleanup receipt。
- 真实 `ChildProcessRunner` + fake provider 的长 CJK/emoji completed 路径为 `COMPLETED / TERMINATED`。
- 先写行为 Red，再做最小 Green。

Focused proof：

```bash
.venv/bin/python -m pytest -q -rx tests/subagent/test_process_runner.py tests/subagent/test_process_termination_contract.py
```

## Slice 3：Provider strict schema 角色投影

允许编辑：

- `agent/provider/normalize.py`
- `tests/provider/test_kernel_providers.py`
- `tests/skill/test_executable_tools.py`

验收合同：

- `properties` 中的业务名称逐字保留，只对子 schema value 递归。
- 现有六个 unsupported keyword 只在 schema constraint 位置删除；`enum`、`const`、`default`、`examples` 等 literal data 保真。
- strict object 必须原本就具有明确 `properties` map 且 `additionalProperties is False`；缺省、`true` 或 schema-valued 均明确拒绝。
- 显式 `properties={}` + `additionalProperties=False` 仍允许。
- 使用既有 `ProviderProtocolError`，开放 object 原因固定为 `unsupported_strict_open_object`；错误 detail 仅包含安全定位，不泄露 schema 数据。
- Runtime ToolSpec、原始 schema 与非 strict 路径不变；Skill 开放 `arguments` 仍不支持 strict，但在 HTTP 请求前准确失败。
- 旧 strict 正例只改为显式封闭 fixture，并新增原开放形状的拒绝测试。
- 先写行为 Red，再做最小 Green。

Focused proof：

```bash
.venv/bin/python -m pytest -q -rx tests/provider/test_kernel_providers.py tests/skill/test_executable_tools.py
```

## 串行闭环

每个 Slice 按以下顺序闭合：

1. Pi 回报可解释的行为 Red、最小 Green、focused test 与 diff 摘要。
2. Codex 检查 ownership、行为语义、已有用户改动与错误分类。
3. Codex 独立运行 focused tests；发现问题则把精确反馈交回同一个 Pi 修正。
4. 当前 Slice 通过后，才发送下一份 Pi 资料包。

三个 Slice 都通过后，本轮只运行一次集中回归与全量门槛：

```bash
.venv/bin/python -m pytest -q -rx tests/memory tests/subagent tests/provider tests/skill tests/kernel
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

任一失败、超时、输出截断或本轮新增 skip/xfail 都不算完成。通过后停止扩张，进入下一轮 truth-sync 与 materialized install 验收。

## 完成证据（2026-09-09）

- Oracle Web 方案、验收合同与 Pi 执行资料包：最高档完成，session 与临时 Profile 已清理。
- Memory：Codex 独立复跑 focused tests，`45 passed`。
- SubAgent：Codex 独立复跑 focused tests，`27 passed`。
- Provider：核心 focused tests `92 passed`；continuity 补充文件 `135 passed`。
- 集中相关回归：`847 passed`。
- 最终全仓回归：`3359 passed, 3 skipped`；skip 均为既有平台条件项，本轮未新增 skip/xfail。
- `git diff --check`：PASS。
- `.venv/bin/ruff check .`：PASS。

本轮冻结后的真实 strict 边界：固定产品 ToolSpec 中，Skill entrypoint 的开放
`arguments` 与 Browser action 的开放 `fields` 会被明确拒绝；外部 MCP schema 是否兼容
取决于服务端声明。这里不静默补空对象、过滤工具、关闭 strict 或切换 Provider。
