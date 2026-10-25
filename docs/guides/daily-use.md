# First Agent 日用指南

> 2026-10-18 CLI 个人试用收尾：日用采用 base 安装，不默认安装实验性 TUI。
> 当前支持范围与验证结果见 [能力清单](capabilities.md) 和
> [唯一执行记录](../handoffs/2026-10-11-product-reliability-closure/RESULTS.md)。
> 详细命令清单见 [COMMANDS.md](../handoffs/2026-10-10-reliable-daily-use/COMMANDS.md)。

## 确认与许可速查（2026-10-23 consent-ux 起）

- **远端模型发送提示（`Remote provider disclosure required`）**：`y` 只批这一次的精确范围；
  `s` 授权本会话常规对话数据（32 次发送 / 60 分钟，提示会显示剩余额度与到期时间）；
  `n`/回车不发送。选过 `s` 后普通对话不再逐次询问。任务开始/修订后的第一次发送若
  工具或控制结构与许可授予时不同，会再次询问并在提示里说明原因（剩余额度旁一行）；
  再选一次 `s` 即为当前结构续期。`/revoke-provider-consent` 随时撤销。
- **含新来源（读文件/列目录/搜索结果等）的发送**：首次会单独询问；选 `r`
  后，本会话内的读/列/搜输出（含之后读到的新文件）都在许可内不再逐次询问。
  **命令输出**（`tool_results` 类）不在此列，仍逐次单独批准——这是当前版本
  已知边界；写文件产生的结果属于稳定来源，在许可内不会反复问。
- **文件/命令审批（`Execute this operation?`）**：`y` 只批本笔；提示中出现 `f` 时可选
  同文件复用（16 次 / 60 分钟）、`d` 选已声明目录复用；`n` 拒绝。不适用时产品会明确说明
  而不会降级。
- **任务暂停窗口**：先 `/resume` 再回答挂起的确认。

## 环境

- **macOS 专属**：沙箱使用 macOS Seatbelt（read-only 验证与 workspace-write）。
  其它平台未验证、不支持。
- Python：`pyproject.toml` 声明最低 **3.11**；本轮实际验证运行版本 **3.12.2**
  （未做跨 Python 矩阵）。
- extras 严格来自当前元数据：`dev`、`browser`、`skill`、`mcp`、`tui`
  （**没有** `web` extra）。TUI 需 `tui`（`textual>=8.2,<9`），但当前有恢复外发确认的
  交互缺口，不作为日用推荐入口。
- 浏览器能力是 `browser` extra，使用专属测试 Chromium，不接管你的日常浏览器。

## 安装

### 本机固定试用入口（2026-10-18）

已使用独立、非 editable 的 base wheel 安装，不依赖开发仓库的未提交文件：

```bash
~/.local/share/first-agent/previews/20261018-cli-9rmRS6/start \
  --workspace /绝对路径/项目副本
```

`start` 只调用该目录内的 `venv/bin/first-agent`，固定使用
`openai_compatible / deepseek-v4-flash / thinking disabled` 和 `https://api.deepseek.com`。
密钥只读取启动进程的 `DEEPSEEK_API_KEY`，不自动加载 shell profile、不读取或改写凭据文件。
启动前在你自己的终端注入有效 key；本轮用户新提供的 key 已通过认证与实际模型调用，但未保存
到安装目录或配置。普通编码样本已完整通过，纠正/恢复与零改写样本没有在本轮预算内全部闭合。

会话保存在同一安装目录下的独立 `state/`，首次实际启动时创建；用同一命令和同一 workspace
重启即可恢复。不要删除旧 state 来绕过未知效果。没有更改 PATH、已有安装、登录项或后台服务。
首次试用建议使用可丢弃的项目副本，并给任务一个你能独立检查的验收条件。

**先准备任务自己的依赖。** Agent 的 base 安装只带自身运行依赖，不会替所有 Python 项目安装
pytest。若任务要跑项目测试，先在启动它的终端激活该项目的既有环境，并确认测试命令可运行：

```bash
source /绝对路径/项目副本/.venv/bin/activate
command -v python3 pytest
python3 -m pytest -q
```

然后从同一终端运行上面的 `start --workspace ...`。launcher 保留调用者 PATH，命令工具会净化
和绑定它；只用绝对路径启动一个 venv 的 Python **不等于**已经激活该 venv 的命令搜索路径。
本轮真实测试就遇到这个差异：外部验证有 pytest，Agent 的子进程却只找到系统 Python；修正
测试进程 PATH 后才完成整条真实任务。不要把找不到依赖解释成 API key 失效或让 Agent 假报完成。

### 自行安装

**每个 venv 必须先创建**；下面两条路径分别对应"用户安装物启动"与"源码开发启动"。

### 用户安装物启动（推荐日常使用）

```bash
python3 -m venv ~/.local/share/first-agent/venv      # 先创建 venv
~/.local/share/first-agent/venv/bin/python -m pip install \
  dist/first_agent-1.0.0-py3-none-any.whl           # base CLI
~/.local/share/first-agent/venv/bin/first-agent --workspace ~/myproject
```

安装物自带 `first-agent` 入口；**不需要**源码目录，也不要求存在 `main.py`。

### 源码开发启动

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python main.py --workspace ~/myproject
```

核心与 `browser`/`skill`/`mcp` extras 分开安装；缺 extras 时启动会给出明确诊断
（例如 TUI 缺依赖会提示安装 `tui` extra 而非缺配置）。

## Provider 配置（DeepSeek Flash）

```bash
export DEEPSEEK_API_KEY=sk-...        # 只在当前 shell 注入；不要写进任何文件
first-agent setup \
  --provider openai_compatible --model deepseek-v4-flash \
  --base-url https://api.deepseek.com --credential-env DEEPSEEK_API_KEY \
  --thinking-mode disabled
```

（源码开发启动时把 `first-agent` 换成 `.venv/bin/python main.py`。）

`setup` 把**非秘密**配置保存到 owner-only 的 owner-preferences（此后免参启动）；
密钥永远只从环境变量注入，不会被保存、打印或写入 checkpoint。
首次对话发送数据前会要求**数据外发确认**（y）——这是治理设计。

## 最短支持路径（setup → 任务 → 第二任务 → 暂停 → 恢复）

这是当前唯一明示支持的日用路径；其余入口（浏览器、MCP 等 extras）见 README 对应章节。

1. **setup（不保存 key）**：按上节配置一次；key 只在 shell 里。
2. **第一个任务**：进入 workspace 启动，直接输入任务文本。写入前你会看到审批预览；
   `Verified delivery` 仅表示已登记证据项通过，模型只说"done"不算数。
   显式文件要求有有限语法的完成下界保护，但不保证任意自然语言要求均被理解。
   仍需检查 diff、独立测试和关键反例；`User acceptance` 提示不是独立业务验收。
3. **`/new` 开第二任务**：第一个任务到终态后输入 `/new`，旧 Goal 与证据原样保留。
4. **安全暂停**：任务中途 `/pause`（或在审批边界 `/exit` 退出）。
5. **恢复**：同一 workspace + 同一 state-root 重新启动，按 `Resuming unfinished task`
   提示批准继续；不需要重述任务，也不会重放已执行效果。

## 第一个任务（一分钟上手）

```bash
first-agent --workspace ~/myproject
```

在一个含 `app.py` 的目录里输入：

```
Task: change greet() in app.py to return 'howdy' and verify by running python3 check.py
```

流程：模型提案 → 你看到**写入审批**（预览完整内容，y 批准 / n 拒绝）→
真实执行 → 模型自验 → `Verified delivery`（含证据范围与目标清单）。
审批前不会有任何写入。

## 日常操作

- `/help` 全部命令；`/new` 在任务终态后开新会话（旧证据保留）；
  `/status` 随时查看当前任务状态、进度与许可余额（只读，不推进任务）；
  `/exit` 退出；运行到审批边界时直接输入新文本 = **中途纠正**（撤销未执行的
  pending 调用，按新要求继续）。
- 实验性 TUI：F2 来源、F3 回看最近保留内容、F4 多行编辑、Ctrl-Q 安全退出
  （等待当前调用收口，不取消）。
- 长调用会显示等待心跳；Ctrl-C 退出码 130 并提示检查可能已发生的副作用。

## 恢复

- **恢复 = 同一 workspace + 同一 state-root 重新启动**。在审批边界 `/exit`
  退出后重启，会提示 `Resuming unfinished task`，批准即可继续（2026-10-10
  真实验证）。
- `/new` 是新任务，不是恢复。审批边界退出不是崩溃恢复；未知效果
  （unknown effect）有专门的恢复表单，按提示分类即可。
- `archive`/`restore` 子命令安全归档与恢复已完成的会话。

## 故障处置

| 症状 | 处置 |
|---|---|
| 缺 extras（TUI/浏览器/skill/mcp） | 按启动诊断提示安装对应 extra；不自动下载 |
| 配置无效/凭据未设 | `setup` 重存非秘密配置；key 只放环境变量 |
| 任务显示完成但未验证 | 看 `Verified delivery` 的证据范围行；`RunStatus.COMPLETED` 不等于验收完成 |
| **Checkpoint 安全错误**（本次会话未能安全打开/关闭） | 先确认旧进程已结束、无未确认的执行资源，再用**原 workspace 与原 state 位置**重启。不要删除 checkpoint/lock、不要新建空状态绕过。若新进程仍失败：停止操作并保留状态，用于定位 |

## 支持矩阵（2026-10-18）

| 对象 | 状态 |
|---|---|
| DeepSeek Flash `deepseek-v4-flash`（api.deepseek.com，openai_compatible，thinking disabled） | 本轮新 key 实际调用有效，新 wheel 普通编码样本完整 PASS；纠正/恢复样本额度暂停，零改写样本未运行。历史“完成但业务错误”不能据普通样本通过就算闭合；证据见唯一 RESULTS。官方模型列表本轮只列 `deepseek-flash` / `deepseek-v4-pro`，原授权名称仍可实际调用，未擅自换模型 |
| 仓库内其它 adapter（anthropic_compatible 等） | 仅有离线测试证据；**未经真实调用验证** |
| 其它"OpenAI 兼容"服务 | 未验证；协议名相近不等于支持 |
| 非 macOS 平台 | 不支持（Seatbelt 专属） |
