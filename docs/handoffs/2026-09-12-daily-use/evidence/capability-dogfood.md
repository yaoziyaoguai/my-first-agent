# Agent 能力 dogfooding 与 QA 记录

日期：2026-09-12  
被测 revision：`838cb2b66fbb`（工作树包含尚未提交的 `/new` 生命周期修复）

## 结论

本轮通过已安装的 `first-agent`、`first-agent-schedule` 和真实 TUI 入口启动产品，
并用隔离的合成 workspace、Memory store、Skill 与本地 MCP fixture 覆盖当前能力面。
没有发现新的功能性回归。当前能力仍应保持 `implemented-candidate`，不能因为本轮本地
dogfooding 提升为 production-ready 或真实 E3。

本轮最重要的事实是：内核和扩展边界可组合，macOS Sandbox 确实执行了真实 Seatbelt，
并且通过 operator 已配置的智谱 Coding Plan endpoint 完成了一次真实 `glm-5.3` 最小生成。
Browser、Web 和配置完成的 019 host journey 仍没有在本环境获得真实运行证据。

## 实际启动旅程

1. 用真实 CLI 同时组合 Memory、合成 Skill、本地 stdio MCP、SubAgent、Sandbox 和 Browser。
2. 在同一进程输入 `/new` 后成功重新组合；产生两个独立 conversation checkpoint，既有
   Memory store 被严格复用，进程正常退出。
3. 真实 TUI 成功进入并正常退出；Textual Pilot 另行验证 `/new` 返回共享 process signal。
4. 调用已安装的 Scheduler `list` 与 `reconcile`，两者均以
   `needs_019_config / host_profile_unavailable` 退出。同日源码复核发现安装入口固定传入
   `core=None`，macOS 入口也是 unavailable 占位，尚未接通可信 host 装配；
   因此不能把原因仅归为本机缺少配置。详见同日 019 调度产品复核。
5. 启用 Browser 时发现当前环境未安装 Playwright/browser extra。CLI 明确报告 unavailable，
   没有静默切换到个人浏览器或非治理实现。
6. First Agent 默认 provider profile 尚未配置；在 Pi 的非产品配置中找到 operator 已配置的
   `cc-switch-zhipu-glm` / `glm-5.3` endpoint。凭据只在测试子进程内临时注入 composition root，
   未写入 First Agent profile、checkpoint、事件或报告。真实模型完成 disclosure 后返回预期的
   `REAL_MODEL_OK`，exit 0。

任务内容与 workspace 均为本轮创建的合成数据。真实 Provider smoke 按用户授权临时解析
Pi 模型凭据并注入子进程；没有输出凭据值，也没有读取 `.env`、真实 Memory、用户会话或
未跟踪 `tui/`。此前笼统写“没有读取凭据”与实际认证操作矛盾，现予更正。

## 能力证据矩阵

| 能力 | 本轮结果 | 证据边界 |
|---|---|---|
| Runtime / files / local process / history | PASS | 真实入口启动；016 reference journey 通过；模型选用工具仍是 deterministic provider 证据 |
| `/new` 生命周期 | PASS | 真实 CLI 生成第二个 checkpoint；真实 TUI 启动；TUI Pilot `/new` 通过 |
| Memory | PASS | 真实 CLI create 后跨 `/new` strict load；integration tests 通过 |
| Skill | PASS | 真实 catalog 装载合成 Skill；reference task 与真实 Seatbelt executable Skill test 通过 |
| MCP | PASS | 真实 CLI 构造本地 stdio bridge 并完成关闭；integration/session tests 通过；未做外部 MCP |
| SubAgent | PASS（有界） | 真实入口注册；单 child、进程 runner 和 parent integration tests 通过；未做远程 Provider child |
| macOS Sandbox | PASS | 启动 preflight 为 ready；真实 Seatbelt workspace/read-only、forked grandchild TCP 阻断和 packaged policy probe 通过 |
| Browser | PARTIAL | 治理 reference tests 通过；缺少 browser extra，未执行真实 Chromium 页面任务 |
| Scheduler | PARTIAL | 注入 core 的 CLI/caller 与重复 occurrence replay 通过；manual task 不再依赖 macOS wake，cold wake 改为显式开启；安装入口固定未装配，仍不能直接使用 |
| TUI | PASS | 真实终端进入/退出；Pilot `/new` 通过 |
| 真实模型 | PASS（smoke） | 真实 `glm-5.3` 完成认证、disclosure 和一次无工具生成；不是完整 capability E3 |
| Web | NOT TESTED | 未配置 Tavily Web profile / credential；没有把模型联网能力冒充为 governed Web |

## QA 发现与处置

### P2（已修复）：启动页没有投影已启用扩展，用户无法确认组合是否成功

在同时启用 Memory、Skill、MCP 与 SubAgent 后，启动页仍只显示
`files, history, local programs, sandboxed execution`。这些扩展功能实际上已经组合成功，
但用户从产品界面无法确认，排障时只能依赖测试或检查内部状态。

本轮已增加安全、无内容的 ready projection，只依据成功完成的现有 composition 显示
Memory、Skills、MCP 与 bounded SubAgent；不显示 Skill 内容、MCP 参数、Memory 路径或凭据，
也没有引入第二套 capability registry。

### 已撤回：`Web profile` 不是 Browser 的错误旧称

macOS 的 `/tmp` 会解析到符号链接路径。以 `/tmp/...` 作为 state root 并启用 Browser 时，
安全检查正确拒绝了路径，报错为 `Web profile path must not traverse symlinks`。复核 composition
后确认该错误确实来自独立的 Web profile loader，而非 governed Browser profile，因此原先把它
判断为旧称是错误归因。本轮不修改正确文案，也不放宽 no-symlink 安全策略；改用 canonical
`/private/tmp/...` 后启动成功。

## 验证记录

- 能力级 dogfood 测试组：`112 passed in 21.16s`。
- 修复后的 CLI/扩展聚焦回归：`100 passed in 14.45s`。
- 真实 Provider smoke：`openai_compatible` / `glm-5.3` / operator 配置的智谱 endpoint，
  `thinking_mode=disabled`，期望文本命中且 exit 0。
- 覆盖 016、017、018、019 reference slice，以及 Memory、Skill、MCP、SubAgent、Scheduler、
  TUI 和真实 macOS Seatbelt 的高价值路径。
- 最终完整回归：`3394 passed, 3 skipped in 360.18s`。首次完整回归中，既有 015 E3
  进程组清理断言在机器负载下发生一次超时；该精确用例随后 `1 passed in 14.14s`，第二次
  完整回归也通过，未把超时或局部重跑冒充为全量通过。
- `ruff check .` 与 `git diff --check` 均通过。

## 未证明的范围

- 真实模型只完成了单轮、无工具的 bounded smoke，没有证明它能稳定选择、串联并完成全部能力。
- 未关闭 provider-specific thinking 时，智谱响应携带不进入 v1 replay 合同的 opaque reasoning 字段，
  Runtime 会 fail-closed；本轮按既有 Provider 合同显式使用 `thinking_mode=disabled`，没有放宽 normalize。
- 没有安装 Playwright/browser extra，所以没有真实 Chromium E3；018 仅有确定性治理合同证据。
- 019 已收轻为默认 manual reconcile、显式 cold wake 和只读 preflight，但安装入口尚未接通可信
  host 装配；本轮没有执行真实 cold wake、后台 occurrence 或 launchd journey。
- 除已记录的真实 Provider 认证与生成请求外，没有连接第三方 MCP 或真实网站，
  也没有宣称任意平台、任意网站兼容。
