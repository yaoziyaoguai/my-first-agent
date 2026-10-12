# First Agent 日用指南

> 2026-10-10 执行包 S3 产物；2026-10-12 按候选安装物复核（Q1）：
> extras 与元数据一致、安装物入口 `first-agent`、Textual 8.2.8。
> 详细命令清单见 [COMMANDS.md](../handoffs/2026-10-10-reliable-daily-use/COMMANDS.md)。

## 环境

- **macOS 专属**：沙箱使用 macOS Seatbelt（read-only 验证与 workspace-write）。
  其它平台未验证、不支持。
- Python：`pyproject.toml` 声明最低 **3.11**；本轮实际验证运行版本 **3.12.2**
  （未做跨 Python 矩阵）。
- extras 严格来自当前元数据：`dev`、`browser`、`skill`、`mcp`、`tui`
  （**没有** `web` extra）。TUI 需 `tui`（`textual>=8.2,<9`；本轮在 **8.2.8**
  上验证）。
- 浏览器能力是 `browser` extra，使用专属测试 Chromium，不接管你的日常浏览器。

## 安装

**每个 venv 必须先创建**；下面两条路径分别对应"用户安装物启动"与"源码开发启动"。

### 用户安装物启动（推荐日常使用）

```bash
python3 -m venv ~/.local/share/first-agent/venv      # 先创建 venv
~/.local/share/first-agent/venv/bin/python -m pip install \
  "dist/first_agent-1.0.0-py3-none-any.whl[tui]"     # 核心 + TUI
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

## Provider 配置（DeepSeek Flash，已真实验证的路径）

```bash
export DEEPSEEK_API_KEY=sk-...        # 只在当前 shell 注入；不要写进任何文件
first-agent setup \
  --provider openai_compatible --model deepseek-flash \
  --base-url https://api.deepseek.com --credential-env DEEPSEEK_API_KEY
```

（源码开发启动时把 `first-agent` 换成 `.venv/bin/python main.py`。）

`setup` 把**非秘密**配置保存到 owner-only 的 owner-preferences（此后免参启动）；
密钥永远只从环境变量注入，不会被保存、打印或写入 checkpoint。
首次对话发送数据前会要求**数据外发确认**（y）——这是治理设计。

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
  `/exit` 退出；运行到审批边界时直接输入新文本 = **中途纠正**（撤销未执行的
  pending 调用，按新要求继续）。
- TUI：F2 来源、F3 回看最近保留内容、F4 多行编辑、Ctrl-Q 安全退出
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

## 支持矩阵（2026-10-10）

| 对象 | 状态 |
|---|---|
| DeepSeek Flash（api.deepseek.com，openai_compatible） | **真实任务 A/B/C 全链验证 PASS**（2026-10-10 候选；详见 handoffs） |
| 仓库内其它 adapter（anthropic_compatible 等） | 仅有离线测试证据；**未经真实调用验证** |
| 其它"OpenAI 兼容"服务 | 未验证；协议名相近不等于支持 |
| 非 macOS 平台 | 不支持（Seatbelt 专属） |
