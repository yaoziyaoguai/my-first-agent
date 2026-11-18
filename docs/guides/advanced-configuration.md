# 进阶配置与可选能力

本文保存默认 CLI 之外的配置与运行边界。首次安装与架构概览见 [README](../../README.md)，
日常操作见 [日用指南](daily-use.md)。可选能力在当前代码身份上均为
`implemented-candidate`；历史验收不等于当前安装物已完成全部第三方适配。

## 配置、状态与恢复

`first-agent setup` 在状态根的 `provider-profile.json` 保存 provider、model、base URL、
credential 环境变量名、thinking mode、request path、strict tools 开关与 timeout。
它不读取或保存密钥，也不发送模型请求。密钥仅从选定环境变量读取，不自动加载 `.env`。
临时覆盖使用完整的 `--provider`、`--model`、`--base-url` 参数组，不能只用单独
`--model` 覆盖已保存 profile。

默认状态根是工作区外的 `~/.local/state/my-first-agent/v1`，目录权限 `0700`、文件权限
`0600`。会话按工作区路径与文件系统身份绑定。重启时，唯一安全候选可自动选择；存在多个
候选时由用户选择，超过 16 个可翻页。工作区身份改变或执行结果未知时先进入恢复决定，
不自动重放可能已经发生的操作。

需要隔离配置时，setup 与启动使用相同的 `--state-root`，且该目录必须在工作区外。
不要直接使用 macOS 的 `/tmp/...`：`/tmp` 是符号链接，状态根的 no-follow 约束会拒绝。
旧 `--state` / `--resume` 手动 checkpoint 接口已移除，旧格式不静默迁移。

```bash
first-agent --provider fake --workspace /absolute/project \
  --state-root "$HOME/first-agent-dev-state"
```

`--without-owner-preferences` 只跳过本次启动的跨工作区偏好，不删除原数据，也不关闭
另行配置的工作区 Memory。

## 项目环境与会话准入

文件工具默认隐藏部分保留名称。启动时可用 `--project-path` 明确开放具体普通文件：

```bash
first-agent --workspace /absolute/project \
  --project-path config/app.yaml --project-path pytest.ini
```

已进入 REPL 时使用 `/project-path config/app.yaml`；无参数可列出本会话准入。
它不能开放敏感文件、符号链接或工作区外路径，也不会开放未列出的相邻文件。

`/env-path .venv/bin` 将一个工作区内目录前缀到本会话 `local_process` 的 PATH，
最多 8 项，新加入者优先；无参数可查看。它不改变沙箱或受管 Web 进程的 PATH，
不安装依赖，也不放宽文件读取权限；每条命令仍按解析后的可执行文件审批。
两类会话准入在 `/new`、`/switch` 重装配或重启后重建，持久会话与 checkpoint 继续保留。
启动旗标 `--project-path` 指定的集合会重新注入。

## 累计模型请求预算

`--max-model-attempts N` 必须与 `--transport-audit-ledger PATH` 配套。
ledger 在 HTTP 发出前累计占位，失败请求也计数；恢复与重启不重置额度。
启用 HTTP SubAgent 时，父子调用共享同一个上限。

额度耗尽后任务在安全边界暂停；若用户决定增加预算，以同一个 ledger 和更高上限
重启即可继续原任务。请求次数不是精确账单，远端已接收的请求不保证可撤销或退款。

## 归档与恢复历史

每个工作区最多保留 256 个 active-history 会话，产品不自动删除历史。
`--status` 可查看完整 conversation ID。

```bash
first-agent --workspace /absolute/project --status
first-agent --workspace /absolute/project archive CONVERSATION_ID
first-agent --workspace /absolute/project archive CONVERSATION_ID --yes
first-agent --workspace /absolute/project restore CONVERSATION_ID SOURCE_CHECKPOINT_DIGEST
first-agent --workspace /absolute/project restore CONVERSATION_ID SOURCE_CHECKPOINT_DIGEST --yes
```

不带 `--yes` 只预览；确认后按 exact revision/digest 操作。只有已完成或已取消、没有
未决执行和资源的会话能归档。归档不可变，restore 不删除归档；身份不匹配、数据损坏、
会话正被使用或同 ID 已存在时拒绝覆盖。

## Provider

默认推荐配置见 [日用指南](daily-use.md#provider-配置deepseek-flash)。
临时覆盖仍可使用显式参数：

```bash
first-agent --provider openai_compatible \
  --model your-model --base-url https://provider.example \
  --credential-env FIRST_AGENT_API_KEY
```

OpenAI-compatible 是协议适配接口，不代表任意兼容服务都已验证。
收官真实层使用的是 `deepseek-flash`、`https://api.deepseek.com`、thinking disabled；
其他 adapter 的历史记录见 [能力状态](../architecture/CURRENT_CAPABILITY_STATUS.md)。

### DeepSeek strict tools

这是显式配置，不会根据 URL 或模型名自动启用：

```bash
first-agent setup --provider openai_compatible --model deepseek-flash \
  --base-url https://api.deepseek.com/beta --request-path /chat/completions \
  --credential-env DEEPSEEK_API_KEY --strict-tools --thinking-mode disabled
```

工具 schema 若含开放 object，strict 投影会在 HTTP 前以
`unsupported_strict_open_object` 拒绝，不静默关闭 strict。
已知可能触发的组合包括 Skill entrypoint 的 `arguments`、`browser_act.fields` 和
取决于 server descriptor 的 MCP 工具；即使模型最终不调用该工具也会触发。

### 思考与流式回答

```bash
first-agent setup --provider openai_compatible --model deepseek-flash \
  --base-url https://api.deepseek.com --credential-env DEEPSEEK_API_KEY \
  --thinking-mode enabled
```

该精确配置支持流式公开回答；不能同时启用 strict。`anthropic_compatible` 也有
SSE adapter，但不代表任意兼容 endpoint 都有当前真实验证。

文本增量仅供显示，最终完整响应才由 Runtime 接纳；断流不拼凑响应，也不自动重发
已开始计费的请求。DeepSeek 的 `reasoning_content` 作为绑定 provider 身份的 opaque
continuation 保留，不进入 UI、Memory 或压缩摘要。取消在读取边界协作处理。

## 公开 Web 与来源

公开 Web 使用 base 安装内的固定 Tavily adapter，需先运行 `first-agent setup-web`，
阅读第三方处理说明并确认，再在选定环境变量中提供 key；不需要 `web` extra。

Search 和 Extract 的 exact query / URL batch 需批准。`web_fetch_url` 只准入当前对话
用户消息中的 exact canonical 公网 HTTPS URL；工具输出、摘要或模型自造 URL 不授予
抓取权限。网络请求发往 Tavily，产品不会直接继承用户浏览器的 cookie 或登录状态。
不承诺第三方 zero retention、training exclusion 或 deletion。

历史、文件、Web 和扩展返回内容作为不可信材料进入上下文。`/sources` 显示来源，
`/sources --advanced` 显示诊断用 opaque ref。来源 receipt 和 citation sidecar 证明观察、
内容摘要与产物的绑定，不保证材料或模型结论在语义上正确。

## Skill

安装 `skill` extra 后以 `--skill-root /absolute/trusted-skills` 配置可信本地目录。
每个 Skill 是一级目录，目录名应与 `SKILL.md` frontmatter 的 `name` 相同。
未配置时不引入 PyYAML 运行依赖。

模型可按需激活 body，或读取 `references/`、`assets/`。manifest 声明的 owner-local
Python entrypoint 可经精确批准在固定文件身份、digest 与 network-off 沙箱下执行。
不支持任意 `scripts/` 自动执行、远程自动安装、prompt hook 或 `allowed-tools` 扩权；
扫描后内容漂移需重启重建 catalog。

## MCP

安装 `mcp` extra，并同时设置 catalog 与 safety-state：

```bash
first-agent --provider fake --mcp-catalog /absolute/mcp-catalog.json \
  --mcp-safety-state /absolute/mcp-safety/latch.json
```

固定 stdio descriptor 映射为 `mcp__<server>__<tool>`，每次调用需审批。
项目持有进程组，通过 SDK 执行有界的 initialize、descriptor verify、call 和 close。
调用后结果无法确认时进入人工恢复，不自动重试。

durable safety latch 在调用前 arm、确认后 clear。崩溃留下未清 marker 时下次启动
拒绝执行，需操作者离线处置。catalog 不存 credential value；不保证任意 server 或
远程 transport 兼容，未配置时 base 不依赖 MCP SDK。

## Memory 与 owner preference

工作区 Memory 是显式本地明文 JSON store，词法召回、revision CAS、owner-only：

```bash
first-agent --provider fake --memory-create /absolute/memory/store.json
# 后续启动改用：
first-agent --provider fake --memory-store /absolute/memory/store.json
```

首次创建与读取已有 store 互斥。store 绑定工作区和非秘密 `--memory-profile`；
模型的 remember/update/forget 需批准，search/get 为只读。
ContextManager 按预算选择召回材料，不把它提升为系统权限，也不在 checkpoint 中保存
整个 Memory 快照。它不等于向量库、无限记忆或云同步。

owner preference 是单独的跨工作区来源，只允许当前用户原话经批准确认或纠正，
项目/Web/模型内容不能自行晋升。forget 停止未来本机召回，保留 tombstone 与 provenance，
不声称删除历史或撤回已发送的远端副本。

## SubAgent

`--subagent` 开启每次需审批的 `subagent__delegate`：把一个有界只读调查交给隔离
子进程。子进程复用同一个 `AgentRuntime.run_turn` 实现，不新增另一套生产 loop。
最多 6 次模型调用、8 次只读工具调用，不继承父历史、Memory、Skill 或 MCP，
无写入、shell 或递归派生。

返回来源由 runner 核对路径、snapshot 与 digest；结果只是建议，不能授予父侧写权限
或代替验收。HTTP child 与父进程共享显式配置的请求 ledger。取消、纠正或暂停会请求
回收子进程组；若远端请求可能已发生，仍需诚实处理 unknown outcome。

## Browser

安装 `browser` extra，再为该安装环境执行 `python -m playwright install chromium`；
以 `--browser` 开启专属隔离 Chromium。它与用户日常 Chrome 分离，具有 exact approval、
显式 user takeover、egress guard 与下载隔离。

本地页面验收只接受本任务 `managed_web_start` 返回的 opaque resource，
不接受任意 `localhost`、LAN 或既有服务。收尾需有 `browser_close` 与
`managed_web_stop` 确认。当前没有 D06 真实模型完整验收，不能外推任意网站、登录、
支付或桌面控制。详见 [018 设计](../architecture/018_GOVERNED_BROWSER_TASKS_DESIGN.md)。

## TUI 与 Scheduler

`tui` extra + `--tui` 提供实验性 Textual 界面，与 CLI 共享 action、reducer、checkpoint
和 Runtime。events 只用于显示，持久结果才权威。暂停后恢复的 pending 外发决定已修复
重显，但不宣称与 CLI 交互完全对等；日用入口仍推荐 CLI。

`first-agent-schedule` 当前只装配 portable typed dispatcher，未装配可运行的 host
composition，管理/调度命令返回 `needs_019_config / host_profile_unavailable`（exit 2）。
这不等于可用的后台定时任务。普通 CLI 不创建 macOS 登录项；cold wake、host qualification
与其它平台支持不属于默认交付范围。

## 开发环境与完整门

在仓库根目录创建开发环境，安装可选测试依赖。隔离 Skill runner 用例还要求同一环境
存在非 editable 安装；源码变化后应清理旧构建目录、重建并重装 wheel，避免测到旧模块。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install ".[dev,tui,mcp,skill,browser]"
# 以下两个目录仅为本仓库自动生成的构建产物。
rm -rf build first_agent.egg-info
.venv/bin/python -m pip wheel --no-deps --wheel-dir dist .
.venv/bin/python -m pip install --force-reinstall --no-deps \
  dist/first_agent-1.0.0-py3-none-any.whl

git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

ruff 版本由 `pyproject.toml` 钉定。缺可选依赖或使用不同解释器不能冒充完整门通过。
真实 provider 验收另有显式授权与预算，普通测试不会自动补做真实付费调用。
