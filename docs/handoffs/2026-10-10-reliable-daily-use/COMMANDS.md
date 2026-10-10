# COMMANDS.md（2026-10-10 执行包 §S3/S5，全部经实际核验）

以下命令在仓库根目录运行；`main.py --help` 输出于 2026-10-10 核验一致。

## 日用启动（核验自 main.py parser）

```bash
# 一次性保存非秘密 provider 配置（之后免参启动）
.venv/bin/python main.py setup \
  --provider openai_compatible --model deepseek-flash \
  --base-url https://api.deepseek.com --credential-env DEEPSEEK_API_KEY

# 日常启动（读已保存 profile；key 仍在环境中注入）
export DEEPSEEK_API_KEY=sk-...   # 仅当前 shell
.venv/bin/python main.py --workspace ~/myproject          # CLI
.venv/bin/python main.py --workspace ~/myproject --tui    # TUI（需 textual）

# 或不保存 profile，每次显式传参
.venv/bin/python main.py \
  --workspace ~/myproject --state-root ~/.first-agent-state \
  --provider openai_compatible --model deepseek-flash \
  --base-url https://api.deepseek.com --credential-env DEEPSEEK_API_KEY
```

注意：`--state-root` 缺省为 owner-only 默认根；显式指定时父目录须为 0700
（transport ledger 校验同要求，见 2026-10-09 dogfood 记录）。

## 会话内命令（核验自 agent/cli/app.py）

`/help` 列出全部；日用核心：`/new`（终态后新任务）、`/exit` 退出、
`/approve <id>`（或交互 y/N）审批、`/revoke`/`/leases` 管理进程租约。
TUI 键位：F2 切换来源、F3 回看保留内容、F4 多行编辑、Ctrl-Q 安全退出。

## 测试与验证入口（核验自仓库实际文件）

```bash
.venv/bin/ruff check .
git diff --check
PIP_NO_INDEX=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx

# S5 touched-area（包 §8.1）
.venv/bin/python -m pytest -q -rx \
  tests/acceptance/test_daily_use_recovery_journey.py \
  tests/cli/test_entrypoint.py tests/tui/test_app.py tests/tui/test_adapter.py

# 安装物
.venv/bin/python -m pytest -q -rx tests/cli/test_016_packaging.py

# 真实本地浏览器旅程（专属 Chromium + loopback）
.venv/bin/python scripts/f2_f3_local_browser_journeys.py --journey all --budget-seconds 120

# S2 生命周期诊断（本包新增，接口冻结）
.venv/bin/python docs/handoffs/2026-10-10-reliable-daily-use/diagnose_session_lifecycle.py \
  --pairs 100 --seed 20261010 --max-seconds 600 \
  --output-dir .local/next-round-evidence/session-diagnosis-1
```

## Wheel 安装路径（核验自 tests/cli/test_016_packaging.py）

```bash
python3 -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
python3 -m pip install "dist/first_agent-1.0.0-py3-none-any.whl"            # base
python3 -m pip install "dist/first_agent-1.0.0-py3-none-any.whl[tui]"       # TUI
```
base 闭包含 httpx 等；browser/web/skill 为独立 extras（见 pyproject）。
