# 2026-09-13 修复后 QA Dogfood

## 结论

本轮使用最终 materialized wheel 从仓库外启动，完成真实 CLI/TUI 启停、真实 DeepSeek 请求前链路、空会话恢复、可选能力装配和 Scheduler 安装入口检查。

结论不是“全部能力端到端通过”：发现三个 P1 问题，其中空会话恢复与 credential 阻断会直接影响日常使用；真实 DeepSeek 因当前环境中的 `DEEPSEEK_API_KEY` 被服务端拒绝而阻塞。Skill、MCP、Memory、SubAgent 只能确认安装候选能够安全装配并显示 ready，不能把它们记成真实模型任务成功。

## 被测身份与安全边界

- wheel：`first_agent-1.0.0-py3-none-any.whl`
- SHA-256：`63c5218c204df5fe1d5f13565348ab8bb8e76b1e005fa5975be4a708184f53bd`
- installed import 来自临时 venv 的 `site-packages`，不是源码目录。
- 合成根：`/private/tmp/first-agent-qa-20260913.8tQYjz`
- workspace、state、Memory、Skill、MCP catalog/safety state 均为本轮合成内容。
- 只检查 credential 环境变量是否存在，不读取、显示或记录值；未读取 `.env`、个人 state、未跟踪 `tui/` 或真实 workspace 内容。
- 当前所有能力的权威 claim 仍是 `implemented-candidate`；本轮 QA 不执行 promotion。

## 旅程结果

| 旅程 | 结果 | 用户可见证据 |
|---|---|---|
| 安装包 `--help` / `--version` | PASS | 帮助正常；版本为 `1.0.0` |
| DeepSeek V4 Flash 直接回答 | BLOCKED | disclosure 后服务端返回认证失败；CLI exit 1；实际 model attempt 1，未进入推理 |
| FakeProvider 基础 CLI | PASS（仅交互壳） | ready、Working、回答投影、`/sources`、空闲 Ctrl-C 均正常；Fake 仅 echo，不算 NLU |
| `/new` 后重启 | FAIL | 两个无 Goal 空会话被列为 unfinished tasks；任一选择都因无 resumable task 而 exit 2 |
| 缺 credential 时查看同一 state | FAIL | 在打开/投影已保存会话前直接 startup exit 2 |
| Browser extra 缺失 | PASS（安全降级） | 明确显示 package missing 与安装指引；没有 fallback 到个人浏览器 |
| Skill root 装配 | PASS（composition only） | 显示 `Skills: ready`；未证明 activation 或约束遵循 |
| MCP benign stdio 装配 | PASS（composition only） | 显示 `MCP: ready`；使用本轮合成 catalog/latch；未证明真实模型调用与 parent 交付 |
| Memory create 装配 | PASS（composition only） | owner-only 合成 store 创建成功并显示 `Memory: ready`；未证明真实保存/召回 |
| SubAgent 装配 | PASS（composition only） | 显示 bounded delegation ready；未证明真实 child/parent 交付 |
| TUI 启停 | PARTIAL | TUI 可启动；Ctrl-Q 正常 exit 0；Ctrl-C 未退出且没有用户可见解释 |
| Scheduler installed CLI | FAIL | help 暴露完整 CRUD；`list` 固定返回 `needs_019_config/host_profile_unavailable` exit 2，入口没有配置参数 |
| 015 E3 driver `--help` | FAIL（developer UX） | `--help` 实际开始运行 offline gates；Ctrl-C 后 traceback，exit 130 |

DeepSeek 官方当前文档确认 `deepseek-v4-flash` 是有效 model；普通 OpenAI ChatCompletions base 为 `https://api.deepseek.com`，strict Tool Calls 使用 `https://api.deepseek.com/beta`。本次使用的是后者，因此认证失败不能归因于拼错 model 名或漏用 strict beta 入口；没有用同一凭据反复重试。

## QA-01：空会话会把 workspace 卡进不可恢复的任务选择（P1）

### What happened

在没有 active Goal 的新会话输入 `/new`，退出后重新启动同一 workspace。First Agent 显示两个 `Untitled conversation (no active task)`，要求选择“unfinished task”。选择任意一项后又提示该项没有可恢复任务，并直接退出。

### What I expected

无 Goal 的空会话不应作为 unfinished task 候选。重新启动应直接进入一个可用会话；即使保留空 conversation，也不能形成用户无法通过产品入口解除的选择循环。

### Steps to reproduce

1. 使用全新 state root 启动 First Agent。
2. 不创建 Goal，输入 `/new`。
3. 在新会话退出。
4. 使用相同 workspace 与 state root 再次启动。
5. 在列出的两个 `no active task` 项中选择任意一项。

### Additional context

这是状态可用性问题，不是数据丢失问题。现有 checkpoint 被保留，但普通用户只能删除/更换 state root 才能绕过，产品内没有明确恢复动作。

## QA-02：安装后的 Scheduler CLI 没有可用的 composition root（P1）

### What happened

`first-agent-schedule --help` 列出了 create、preview、approve、list、show、open、update、pause、resume、cancel、purge、wake、reconcile。实际执行最安全的只读 `list`，固定返回 `needs_019_config` / `host_profile_unavailable`；帮助中没有提供 state root、host profile 或配置入口。

### What I expected

如果 Scheduler 是普通安装后可用的候选能力，CLI 应提供明确、受治理的本地配置入口并允许至少 list/show；如果当前安装入口必定不可用，顶层帮助和 README 应明确标为开发/host adapter 尚未装配，而不是呈现完整可用命令面。

### Steps to reproduce

1. 非 editable 安装 First Agent wheel。
2. 运行 `first-agent-schedule --help`。
3. 运行 `first-agent-schedule list`。

### Additional context

这不否定 portable control core 的离线合同；问题是普通安装入口没有把 core/host profile 组合起来，用户无法取得该能力。

## QA-03：credential 检查阻断离线状态查看与恢复（P1）

### What happened

使用 real-provider 配置启动已有 state，但指定的 credential 环境变量不存在时，First Agent 在展示保存的 Goal、pending decision、recovery 状态之前直接退出。当前变量存在但被 provider 拒绝时，认证错误同样使当前 CLI 立即结束。

### What I expected

没有可调用 credential 时不能发起新模型请求，但用户仍应能够离线查看保存状态、取消 Goal、处理本地 unknown outcome，或至少获得指向具体恢复动作的只读诊断。认证失败信息应说明所用 credential 变量名和可执行的重启/设置步骤，但不能显示值。

### Steps to reproduce

1. 用 real-provider 配置创建或复用一个合成 state root。
2. 使用一个未设置的 credential 环境变量名启动。
3. 观察程序在会话投影前 exit 2。

### Additional context

本轮真实 provider 请求使用当前环境已有的变量并获得认证失败，没有记录 key。此问题不授权 FakeProvider 接管真实任务；离线查看必须保持零 provider/effect 推进。

## QA-04：CLI 命令与恢复动作不可发现（P2）

### What happened

交互中输入未知 slash command 只显示 `Unknown command.`。顶层 `--help` 没有列出 `/new`、`/sources`、`/leases`、`/browser-profiles`、批准、恢复和取消等交互命令，也没有 `/help` 入口。

### What I expected

未知命令应指向一个可用的交互帮助入口；用户无需先阅读仓库 README 才能发现日常恢复、来源、租约和 Browser profile 操作。

### Steps to reproduce

1. 启动 CLI。
2. 输入任意未知 slash command（本轮使用 `/bogus`）。
3. 运行顶层 `first-agent --help`，查找交互命令说明。

### Additional context

README 当前只列出部分 slash command；实际入口还包含更多只读和 profile 管理命令。帮助应由同一命令注册表生成或至少保持可验证同步，避免文档漂移。

## QA-05：TUI 的退出键不符合终端直觉且提示不足（P2）

### What happened

TUI ready 后按 Ctrl-C 没有退出，也没有显示“请使用 Ctrl-Q”或关闭状态；按 Ctrl-Q 才正常退出。

### What I expected

空闲状态下 Ctrl-C 应安全退出，或界面必须明确、持续地显示实际退出键。运行中如果不能退出，应解释正在等待安全收口，而不是无反馈。

### Steps to reproduce

1. 使用 FakeProvider 启动 TUI。
2. 在 ready/idle 状态按 Ctrl-C。
3. 再按 Ctrl-Q。

### Additional context

本轮只证明 idle TUI 启停；没有声称真实 in-flight cancel 可用。

## QA-06：015 E3 driver 不支持标准 `--help`，中断会打印 traceback（P2，开发体验）

### What happened

对 015 E3 驱动传入 `--help`，脚本没有显示帮助而是直接开始耗时 offline gates。中断后打印 Python traceback。

### What I expected

所有可直接运行的验收 driver 至少应提供可预测的 `--help` 或明确拒绝未知参数；Ctrl-C 应给出有界状态摘要并退出，不把正常操作者中断显示成脚本崩溃。

### Steps to reproduce

1. 对 015 E3 driver 传入 `--help`。
2. 等待它开始运行 offline gates。
3. 按 Ctrl-C。

### Additional context

这是开发/验收工具问题，不影响 First Agent runtime 的安全合同，优先级低于 QA-01 至 QA-03。

## QA-07：能力存在与当前交付已验证容易被混读（P2，产品文案）

### What happened

README 使用“当前能力”列出多项功能，而权威状态文件又说明当前 identity 的所有能力均为 `implemented-candidate`。普通用户容易把“代码中存在”理解成“当前 wheel 已完成真实验收”。

### What I expected

产品首页应把“当前可用范围”“需要额外配置/依赖”“仅历史 identity 验收”“本轮尚未真实验证”分开呈现。Web 与 Browser、Memory 与 owner preference/history、Run completed 与 Goal `VERIFIED_DONE` 尤其不能混称。

### Steps to reproduce

1. 阅读 README 的“当前能力”。
2. 再阅读 Current Capability Status 的 current snapshot。
3. 比较普通用户会得出的可用性结论。

### Additional context

这不是要求删除能力，而是降低错误期待。安全围栏有效与产品任务好用是两个不同结论。

## 建议处理顺序

1. 先修 QA-01：它能把某个 workspace 的正常入口卡死。
2. 再做产品取舍：若 Scheduler 要作为日常能力，修 QA-02；若不打算交付，就收缩帮助和 README 声明。
3. 修 QA-03，使无 credential 的只读诊断/恢复不依赖 provider，同时保持零外发、零 effect。
4. QA-04/QA-05 做一个统一的交互帮助和快捷键发现性切片。
5. QA-06、QA-07 作为开发体验与产品文案收尾，不应阻塞核心 runtime 修复。

## 尚未验证

- DeepSeek 自然语言 G1–G10：认证阻塞。
- Skill activation/entrypoint 的真实模型选择与约束遵循。
- MCP exact approval、transport result、receipt 与 parent 最终交付的真实模型 journey。
- Memory 的真实两步保存与 `/new` 后召回。
- SubAgent 真实 child/parent 交付。
- Browser extra 安装后的 Chromium journey。
- Scheduler 在真正 host composition 下的 CRUD/cold-wake journey。

不得用本轮的 composition ready、安全降级或历史 PASS 替代上述真实验证。
