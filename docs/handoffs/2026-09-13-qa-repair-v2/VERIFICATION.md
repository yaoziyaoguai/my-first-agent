# 验证与复现

## 快速起点

在仓库根运行：

```sh
git status --short --branch
git rev-parse HEAD
shasum -a 256 -c docs/handoffs/2026-09-13-qa-repair-v2/BASELINE.sha256
```

保留接手前改动。指纹不匹配代表需要重新检查相关文件，不代表可以覆盖。资料包只包含相对源码路径，无需复制真实 state 或密钥。

本包的 [probe_installed.py](probe_installed.py) 会创建并清除自身临时合成目录，运行指定的已安装 CLI；不继承任何 credential/PYTHONPATH，不调用真实模型。它验证 R1 两个选择和 R3 /help，**不是全部验收**。当前未修候选应 exit 1；修复后的候选应 exit 0。macOS 本地运行：

```sh
.venv/bin/python docs/handoffs/2026-09-13-qa-repair-v2/probe_installed.py --first-agent /ABSOLUTE/NEW_VENV/bin/first-agent
```

/ABSOLUTE/NEW_VENV 为你实际构建的候选，必须替换；不要依赖旧 /private/tmp 存活。超时/异常/输出越界不得判 PASS。脚本只对自己启动的合成流程作退出确认，不验证自然语言智能。

## 定向门禁

每个切片先运行新 reproducer（修复前真实 Red），然后修复并跑相关门禁：

```sh
# R5 完成参数解析和递归测试替换后才能运行这组。
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/reference/test_015_e3_direct_script.py tests/reference/test_015_e3_harness.py

# R1/R2
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_state_root.py tests/continuity/test_restart_selection.py tests/cli/test_entrypoint.py tests/cli/test_everyday_entrypoint.py

# R3/R4
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/cli/test_commands.py tests/cli/test_contextual_decisions.py tests/tui/test_app.py tests/tui/test_approval_journey.py

# R6
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/automation/test_cli.py tests/automation_hosts/test_macos_cli.py
```

新增测试文件应加入对应门禁。源码 fixture 注入是正确的离线测试手段，但不能用它替代 installed entrypoint。只跑新 helper 的存在断言不算行为证据。

## 最终 source gates

R5 已确认无嵌套 pytest/残留 subprocess，最终代码稳定后运行一次：

```sh
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

遇到 macOS process/Seatbelt/loopback 权限错误，记录真实环境并在允许对应能力的环境重跑；不要删测试或弱化 assertion。超时、被中断、exit unknown 不算 PASS。之后只改文档时无需重复 full suite；若继续改内核则重跑受影响及必要 broader gates。

## 最终安装验证

1. 用当前树构建 wheel（本地工具允许 pip wheel --no-deps --no-build-isolation；缺 build 包不是必须安装新工具的理由）。
2. 新建 venv，非 editable 安装该 wheel。从仓库外运行，确认 agent.__file__ / main.__file__ 来自该 venv site-packages。
3. 记录 wheel SHA-256；若使用 --system-site-packages，明确“依赖环境非纯净”，不能声称 clean install。
4. 执行 probe_installed.py，所有 cases true/exit 0。
5. 额外验证 installed --status：全新不存在 state root 下无需 provider flags 即 exit 0，目录未创建；复用合成 pending state 展示准确摘要，state manifest 不变。可用该安装包 main.main 的 input_fn seam 构造确定性交互，不可替换产品模块或 sys.path 掩盖导入。
6. installed Scheduler help 明确 unavailable；list 的 JSON/exit 稳定。installed TUI 按 Ctrl-Q 退出；完整关闭语义由 Pilot 回归。
7. driver --help/unknown args 分别 exit 0/2；零 gate/provider/process 业务执行。

QA-01 的 installed manifest 校验应只读已有合成 checkpoint，禁止用用户 state 验证。不要先手工清除无 Goal checkpoint 让复现“变绿”。

## 真实模型补证（本包不依赖）

上轮仅有一次 auth-error attempt，status 具体值/usage 未记录，不能推断实际计费或 key 失效原因。用户现已另行提供新 key 并授权后续合成 dogfood；精确文件与安全注入方法见 [CREDENTIALS.md](CREDENTIALS.md)。只读取此授权文件，不复制聊天 key、Pi/Claude 配置或扫描凭据目录。

离线修复完成后执行：
- 首先核对官方 DeepSeek 文档的 model/base/path；保持用户选择的便宜 Flash，不自动换 provider。
- 为 Skill/MCP/Browser 的开放 object schema 使用显式 non-strict 独立配置；strict beta 是另一个覆盖用例，不能静默 fallback。
- 使用[前一包 VERIFICATION.md](../2026-09-13-dogfood-remediation/VERIFICATION.md)中“合成 fixture”“最小真实任务矩阵”“预算与度量”“证据与完成标准”的合成测试方法；不继承旧 W/F 修复范围、旧 model 名和旧凭据说明，完成标准以本包 R1–R6 为准。同一确定性错误无新证据不反复重试。
- 单 journey 最多 8 attempts、总计 50、单 HTTP timeout 90s；只能声称操作者预算，不能假称已有原子 hard cap。
- 记录 attempts、approval、tool/effect、parent final、单调时钟；usage 缺失写 unknown。

## 交付状态

每个 R 必须有：复现/根因、Red/Green、修改文件、是否改变架构合同、最终 installed 证据。具体模板见 RESULTS.md。
本包离线完成与真实模型 BLOCKED 可以同时成立；Scheduler 功能仍 deferred 必须在最终报告单列。
