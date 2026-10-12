# Dogfood 修复执行记录

当前状态：**离线修复与全量回归已闭合；真实 DeepSeek 自然语言旅程未运行，不能宣称真实模型端到端通过。**

## 基线与范围

- 接手日期：2026-09-13；分支：`main`；起始 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`。
- 被测对象是该 HEAD 加接手时已有 dirty tree，以及本次 W1–W6 的窄修复。当前分支相对 `origin/main` ahead 7。
- 接手前已有 019、日常可用性修复、测试、文档与脚本改动；本次没有把整个 dirty tree 冒充为新改动。
- 未跟踪的 `tui/` 属于用户内容，本次未读取、修改或纳入验证产物。
- 本次不读取 `.env`、secret、credential 或私有运行状态；没有 commit、push、tag、remote 修改或 capability promotion。
- 真实模型只允许使用进程环境中本轮专用的命名凭据。本次没有安全注入该凭据，因此没有进行真实 provider 调用，也没有把会话里出现过的 key 写入命令、文件或日志。

## 实施记录

### W1：artifact 批准文案（F4）

- 根因：运行前批准文案容易让用户误以为还要批准尚不存在的未来文件摘要，与已有的“两阶段确认”合同表达冲突。
- 修改：在 `agent/runtime/tools.py` 明确“本次只批准运行；生成后另行确认当前文件内容”，没有放宽 reducer 的 artifact evidence 约束。
- Red/Green：`tests/process/test_artifact_approval_contract.py` 覆盖生产 prepare 路径；相关 CLI/TUI renderer 回归通过。
- 结果：`fixed`。仍保留 effect 批准与 `confirm_file` 内容确认两阶段，不接受仅 process receipt 作为 artifact 完成证据。

### W2：拒绝后交还控制（F1）

- 根因：拒绝 pending approval 后，runtime 仍可能继续同一批次或再次调用 provider，造成继续劝批或执行剩余工具的体验。
- 修改：`ResolveApproval(approved=False)` 终止当前 run、记录拒绝并返回 `CANCELLED/approval_declined`；Goal 保留，方便用户随后纠正、恢复或显式取消。拒绝后不继续当前 model batch，也不自动重放。
- 涉及：`agent/runtime/state.py`、`agent/runtime/loop.py`、`agent/cli/render.py`，以及 kernel/continuity/CLI 测试与 `scripts/run_015_e3.py` 的合同同步。
- Red/Green：拒绝后 provider 增量调用为 0、effect 增量为 0、第三项不执行、reload 不把拒绝变批准、operator/model invocation 都有拒绝记录。
- 结果：`fixed`。暂停策略是“当前 run 终止，Goal 不自动取消”；下一次用户指令仍须形成新的 exact preview/binding 与批准。

### W3：入口路由、治理 receipt 与父级交付（F2）

- 根因一：bootstrap 对已配置能力的提示不足，模型可能把“当前阶段未暴露 callable”误判为“能力不存在”。
- 根因二：成功的 MCP/SubAgent effect 缺少统一、可接纳且与 exact request 绑定的 runtime receipt，导致工具成功却无法合法闭合 Goal。
- 根因三：SubAgent 已有成功 receipt 后，completion 分支可能只返回通用完成文案，丢掉 parent 的实际汇总文本。
- 修改：
  - `agent/runtime/context.py` 与 `agent/provider/normalize.py` 增加受校验的 configured-capability 提示和显式 intent；没有新增第二套 runtime loop。
  - `agent/runtime/tools.py` 为成功的受治理 effectful tool 生成 `governed_tool_v1` receipt；`agent/runtime/state.py` 只接纳 runtime-owned、exact request 绑定的 MCP/SubAgent completion criterion；`agent/runtime/loop.py` 在 tool result 后走同一 admission 路径。
  - completion 已验证后优先交付 provider 的 `ModelTextBlock`，无文本时才使用原通用完成文案。
- Red/Green：MCP echo、SubAgent 两点汇总、失败/未知状态、伪 receipt、缺 completion claim、纯文本捷径、exact process authority 均有回归；`tests/subagent/test_integration.py` 证明 receipt 成功后 parent 文本仍被交付。
- 结果：`fixed`（离线合同）。Skill/MCP/SubAgent 的真实模型选择与自然语言质量仍未实测。

### W4：Memory 两步入口说明（F3）

- 根因：模型无法稳定区分“已配置但当前阶段未暴露”“未配置”和“缺少合法用户 source”。
- 修改：`agent/memory/tools.py`、runtime context/tool guidance 明确完整原文、owner-provided source、配置状态与 activation 阶段；没有改变 `_fact_admission_for` 的信任边界。
- Red/Green：无配置、有配置但 bootstrap 不暴露 callable、完整上一条用户原文、子串需澄清、拒绝不保存、`/new` 后同 workspace 召回、跨 workspace 与伪 binding 拒绝。
- 结果：`fixed`（离线合同）。没有向真实 provider 发送 Memory fixture。

### W5：终态入口与 Ctrl-C（F5、F6）

- 修改：终态提示准确指向 `/new`；活跃/待批/未知 effect 不错误宣传可开新任务。provider 等待阶段的 `KeyboardInterrupt` 被投影为明确的非成功中断，不显示 traceback；已进入 `EXECUTING` 的未知 effect 仍保留恢复语义。
- Red/Green：CLI contextual decisions、entrypoint、restart/recovery 与注入 `KeyboardInterrupt` 回归通过。
- 结果：F5、F6 均 `fixed`。不声称本地 Ctrl-C 已取消远端服务端推理。

### W6：启动、路径与 endpoint 错误（F7、F8、F10、F11 部分）

- F7：owner preferences 的 provider trust mismatch 现在准确说明旧 trust 绑定，不再误称 workspace Memory 配置；不自动迁移、删除或重绑旧数据。
- F8：缺父目录从其他路径错误中单独分类并给出可执行提示；存在、symlink、越界、敏感名称仍走原安全拒绝，不自动 `mkdir`。
- F10：0755 state root 的错误明确要求 owner-only 权限；不自动修改真实目录权限。
- F11：离线验证 `https://api.deepseek.com` + `/chat/completions` 及含版本段的 explicit base/path 组合；保留完整 explicit group 优先、禁止字段混合和启动时探测多个 endpoint。
- 结果：F7、F8、F10 `fixed`；F11 endpoint composition `fixed/verified offline`，GLM wire compatibility `deferred`，因为没有本轮真实失败样本或真实调用。

### W7：证据和成本收尾（F9、F11）

- F9：没有离线证据证明同一 digest 发生重复实际 HTTP disclosure；未修改授权默认或合并批准。状态为 `not-reproduced`。
- F11：未顺手使用 Pi 或历史凭据，也未猜测 GLM 兼容补丁。取得脱敏 wire 失败样本后才应另开窄修复。
- 没有开启新的能力、019 promotion、Browser/调度 E3 或下一轮架构扩张。

## 问题覆盖

| 问题 | 状态 | 代码/测试证据 | 剩余边界 |
|---|---|---|---|
| F1 拒绝收束 | fixed | runtime approval、goal controls、operator privacy 回归；拒绝后零 provider/effect 增量 | 真实模型 G3 未运行 |
| F2 工具后交付 | fixed（offline） | MCP/SubAgent receipt admission、parent text 交付、失败路径回归 | Skill/MCP/child 真实模型行为未运行 |
| F3 Memory 入口 | fixed（offline） | Memory fact scope/tools/integration 与 `/new` 回归 | 真实模型两步体验未运行 |
| F4 artifact 文案 | fixed | 生产 preview 合同与 CLI/TUI renderer 回归 | 保留两阶段确认 |
| F5 新任务指引 | fixed | contextual decision/entrypoint 回归 | 不自动换 Goal |
| F6 Ctrl-C | fixed（本地投影） | 注入中断与恢复回归 | 不证明远端推理被取消 |
| F7 偏好 trust 错误 | fixed | owner preferences/provider profile 回归 | 不迁移旧数据 |
| F8 缺父目录 | fixed（分类） | file tools/path safety 回归 | 历史 J3 的真实模型停滞未复现 |
| F9 多次 disclosure | not-reproduced | 未观察到可归因于同一 digest 的重复 HTTP 证据 | 授权默认未改变 |
| F10 state root 权限 | fixed | state root/entrypoint 回归 | 不修改真实目录 |
| F11 endpoint/GLM | endpoint fixed；GLM deferred | provider profile/URL composition 离线回归 | 无真实 GLM wire 样本 |

## 最终验证

### 代码与测试

- 定向回归：171 passed，116.93s，exit 0。覆盖 runtime/kernel、continuity、CLI/TUI、artifact、Memory、MCP、SubAgent、provider、reference 等 touched area。
- 功能回归补充：9 passed，exit 0。
- macOS Browser profile：36 passed，exit 0（在允许真实 profile probe 的环境中运行）。
- macOS Seatbelt/loopback：26 passed，exit 0（在允许真实 Seatbelt 与 loopback 的环境中运行）。
- `git diff --check`：exit 0。
- `.venv/bin/ruff check .`：exit 0。
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx`：**3429 passed, 3 skipped in 388.83s，exit 0**。
- 普通受限执行环境中的第一次 full suite 曾出现 29 failures + 12 errors，原因包括 macOS profile/process identity/loopback 被环境拦截；同时也暴露出拒绝语义变更后的旧测试预期。旧预期已按新合同修正；相关系统测试在具备所需本机能力的环境重跑通过，最终 full suite 如上全绿。没有禁用或弱化这些测试。

### Materialized wheel

- 构建方式：从最终工作树使用本地 `pip wheel --no-deps --no-build-isolation` 构建；当前环境没有独立 `build` 包。
- wheel：`/private/tmp/my-first-agent-wheel.Irhs5k/dist/first_agent-1.0.0-py3-none-any.whl`。
- SHA-256：`63c5218c204df5fe1d5f13565348ab8bb8e76b1e005fa5975be4a708184f53bd`。
- 非 editable、`--no-deps` 安装成功；仓库外导入路径：
  - `/private/tmp/my-first-agent-wheel.Irhs5k/venv/lib/python3.12/site-packages/agent/__init__.py`
  - `/private/tmp/my-first-agent-wheel.Irhs5k/venv/lib/python3.12/site-packages/main.py`
- `first-agent --help` exit 0；`first-agent --version` 输出 `first-agent 1.0.0`，exit 0。
- 合成 workspace/state root 下 `--provider fake` 启动成功，显示 ready/capability 状态，输入 `/exit` 后 exit 0，无残留交互进程。
- 该 venv 使用 `--system-site-packages`，所以**依赖环境非纯净**；只能证明 wheel materialized、入口不从源码目录导入和基本启动，不是 clean dependency install 证明。
- W1/W2/W4/W5 的行为由最终 wheel 同源代码的全量/定向测试证明；没有在安装后的 CLI 中逐条重演真实自然语言 journey，因此不把基本启动冒烟写成这些 journey 的端到端 PASS。

### G1–G10

| Journey | 结果 | 本次证据与限制 |
|---|---|---|
| G1 直接回答 | NOT RUN（真实模型） | 离线路由回归 PASS；未验证真实语言质量 |
| G2 只读 TODO | NOT RUN（真实模型） | 只读工具/entry routing 回归 PASS；未跑自然输入 |
| G3 首次拒绝写入 | NOT RUN（真实模型） | 拒绝收束 deterministic 回归 PASS；未人工完成真实批准旅程 |
| G4 stale 写入批准 | NOT RUN（真实模型） | stale binding/read-back 回归 PASS；未跑真实 provider |
| G5 进程与 artifact | NOT RUN（真实模型） | artifact 两阶段合同回归 PASS；未跑合成脚本 journey |
| G6 Memory 两步 | NOT RUN（真实模型） | admission、拒绝与 `/new` 回归 PASS；未外发 fixture |
| G7 Skill | NOT RUN（真实模型） | activation/路由合同有离线覆盖；未验证模型主动选择与输出格式 |
| G8 SubAgent | NOT RUN（真实模型）；offline PASS | 成功/失败 receipt、exact criterion、parent 两点交付 integration PASS |
| G9 MCP echo | NOT RUN（真实模型）；offline PASS | exact approval、成功/错误 receipt admission integration PASS |
| G10 Ctrl-C | NOT RUN（真实 HTTP）；offline PASS | provider 等待阶段注入 `KeyboardInterrupt`、无 traceback/恢复合同 PASS |

### 成本、产物和未完成项

- 实际模型 HTTP attempts：0；retries：0；真实 token/cost/usage：unknown/not applicable。本轮启动的 CLI 会话已返回 exit 0；受限环境拒绝 OS-wide `ps` 枚举，因此“不存在其他同名外部进程”没有额外的整机级证明。
- 本轮创建的 materialized 验证内容仅位于精确临时根 `/private/tmp/my-first-agent-wheel.Irhs5k`；为便于复核暂未删除。它不是 Git 内容，之后可以整体删除。
- 已关闭安装包 CLI 的交互进程；没有启动 launchd、后台 scheduler、Browser、真实 MCP server 或 SubAgent provider。
- 本包范围内可安全离线修复的事项已经完成。仍未证明的是：G1–G10 的真实 DeepSeek 端到端体验、Skill script 的真实选择、真实 MCP/child provider 行为、GLM wire compatibility，以及完全隔离依赖的 clean install。
- 若以后继续，唯一合理的下一步是由操作者在进程环境中安全注入本轮专用凭据，使用本包 synthetic fixture 按 G1–G10 有界执行；没有该前提时不应继续消耗或复用其他 Agent 的凭据。
