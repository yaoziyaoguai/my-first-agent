# 验证、安装与真实任务

## 0. 起始检查

在仓库根执行，逐条记录 exit 和结果：

```sh
git status --short --branch
git rev-parse HEAD
shasum -a 256 -c docs/handoffs/2026-09-13-daily-use-repair-v3/BASELINE.sha256
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python docs/handoffs/2026-09-13-daily-use-repair-v3/probe_baseline.py
```

probe_baseline 是当前缺口的观察器：exit 0 表示探针运行成功，**不代表产品修复通过**。它不依赖 /private/tmp 中的旧文件；自行创建并清除合成数据，JSON 不含用户路径或凭据。修复后结果可能变化，不能为保持 baseline 表象删掉新实现。

BASELINE 是起始 dirty 文件的字节身份，不是 git clean 断言。指纹漂移需人工核对 overlapping hunks；禁止回退用户改动。新增测试需在改实现前证明真实 Red；不能把 baseline probe 的“成功复现失败”作为 Green。

## 1. 定向门禁

每项加入你新建的测试文件；以下是已存在且可直接用的相关门禁。

```sh
# D0：budget reserve 必须用额外的并发/重启/dispatch spy 测试覆盖
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/provider/test_transport_audit.py tests/kernel/test_runtime_limits.py tests/cli/test_entrypoint.py

# D1 / D2
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/tools/test_file_tools.py tests/tools/test_path_safety.py tests/tools/test_workspace_search.py tests/kernel/test_runtime_approval.py tests/kernel/test_tool_outcomes.py

# D3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_state_root.py tests/continuity/test_restart_selection.py tests/cli/test_entrypoint.py tests/cli/test_016_startup_projection.py

# D4
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/memory/test_owner_preferences.py tests/provider/test_remote_disclosure.py tests/cli/test_everyday_entrypoint.py tests/cli/test_entrypoint.py

# D5 / 最小路由、进程与 8-call 回归
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/continuity/test_entry_routing.py tests/reference/test_016_first_agent_1_0.py tests/process/test_preparation.py tests/process/test_j1_production_verified_done.py tests/process/test_artifact_approval_contract.py
```

新 bug 修复只重测相关门禁，不每改文案重跑全量。既有测试中的默认安全边界仍需通过；新增 opt-in 功能应补新测试，不粗暴放宽旧断言。

## 2. 最终候选

离线实现稳定后构建一次非 editable wheel，在新 venv 安装，从仓库外核对 agent.__file__/main.__file__ 来自该 venv site-packages。记录 wheel SHA-256、Python 版本、OS、安装依赖方式与 dirty identity；不使用 PYTHONPATH、源码 monkeypatch 或 editable 安装冒充 wheel 回归。

优先证明纯净 venv 的 base 安装；本地依赖缓存缺失时可记录具体缺口。若使用 system-site-packages，必须标明依赖非纯净。不要从根未跟踪 tui/ 打包，不更新历史 seal 或启动 019 实机验收。

安装后必测（均用合成 workspace/state）：

- --help 列出新参数，未知/无效参数 exit 2；--status 无凭据、零创建仍保持。
- D1 flag 真正贯穿 installed main → composition → file boundary；指定公共 config/pytest.ini 可读取，敏感 fixture 仍拒绝。
- D2 完整目录审批、文件审批、read-back；拒绝和过期批准不执行；没有人为预建目标目录。
- D3 创建 17 和 33 个保存会话，installed CLI `n`、页内编号、`p`、退出与实际目标 identity 都正确；原 bytes 不变。可用安装包的 main.input_fn seam，但不能替换产品模块。
- D4 原模型建合成偏好，新模型加 --without-owner-preferences 启动；旧偏好 bytes 不变，source/tools 确认省略；新 disclosure 前零 HTTP。用 MockTransport 注入 transport，不改核心路径。
- D0 budget 在 installed 主入口重启后仍生效；UI、Runtime 与实际 transport 计数一致。
- 上一包的离线安装 probe 可复用，但只证明 R1/R3，不能替代以上：`docs/handoffs/2026-09-13-qa-repair-v2/probe_installed.py`。

最终代码（包含 D5 如有的修复）稳定后只跑一次最终 source full gates：

```sh
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

若安装候选或真实任务暴露新缺陷，先定向修好；源代码有变时旧 wheel 作废，重建并重测受影响安装项。最终 full 可以留到这些修复之后。超时、输出截断、无 exit code、跳过的系统依赖都不是 PASS。

## 3. 合成材料

使用 mktemp -d 新建一个根，其下 workspace 与 state 分开。只测试这里的内容；不要在真实仓库里测试模型读写。用编辑工具创建以下 UTF-8 文件，末尾有换行。

`workspace/notes/product.md`：

```text
# Product
- TODO: add CSV export
- Keep approval explicit
```

`workspace/config/app.yaml`：

```text
export_format: csv
test_mode: synthetic
```

`workspace/pytest.ini`：

```text
[pytest]
testpaths = tests
```

`workspace/greet.py`：

```python
def greet(name):
    return f"Hello, {name}."
```

`workspace/generate_report.py`：

```python
from pathlib import Path

Path("generated.txt").write_text("bounded process output\n", encoding="utf-8")
print("generated.txt created")
```

不要预建 reports/。真实调用前固定 `generate_report.py` 的 bytes/hash 与候选 venv 的真实解释器绝对路径（保留正确解释器环境，不用 pyenv/asdf shim）。操作者只批准该准确脚本；同 UID local_process 不是 sandbox。其他命令、个人目录、外部网站任务均不在本轮批准范围内。

## 4. 真实调用的强制预算

必须先通过 D0 离线/安装检查。整个本轮修复尝试共享一个全新 owner-only ledger，累计 **最多 40 次 model dispatch**；每个 journey（含失败重试、修复前后复测和重启）最多 8 次。不能换 ledger、换 journey 名字或多次 /resume 重新发额度。

具体计数方法：journey 首次开始时读取同一 ledger 的合法 model 计数 B，冻结该 journey 的 ceiling 为 `min(B + 8, 40)`，记录在 RESULTS。该 journey 的所有重启与复测都传入同一个 `--max-model-attempts CEILING`。下一 journey 才可以计算新的 ceiling；真实用例串行，禁止同时用不同 ceiling 竞争。model 发送前原子占位，计数含失败，CLI 每 action 8 次本身不替代本节预算。

HTTP timeout 配置 90s；不要把 HTTP 客户端分段读超时说成端到端 deadline。每个 journey 主动运行最长 5 分钟；为此复用已有 bounded process-group runner/PTY supervisor，准确跟踪自己启动的进程、超时终止并确认清理。人工审批等待时间单列。不能创建 daemon，也不能全局 pkill。

到界或同一确定性故障再次出现且无新证据时停止该用例，转离线复现。若无法可靠执行上述预算与清理，本包真实行记 BLOCKED。禁止“再多跑一点直到偶然成功”。

## 5. 必测真实任务

使用 CREDENTIALS 的最新授权方式。普通自然语言输入不能夹带“必须先调用 goal_proposal”等内部实现教学。disclosure 和 effect 按产品准确预览逐项决定；操作者可以在这个合成范围内执行已约定的 y/n，记录决定，不把自动同意脚本当作真实用户体验。

| ID | 输入/操作 | PASS 必须证明 |
|---|---|---|
| K1 | `只读取 notes/product.md，列出 TODO，不创建或修改任何文件。` | 正确列 CSV export，来源正确；没有 write/process 请求，workspace manifest 不变；8 次以内交付 |
| K2 | 启动带 --project-path config --project-path pytest.ini；`读取 config/app.yaml 和 pytest.ini，告诉我导出格式和测试目录，不修改文件。` | 两个值 csv/tests 正确来自读取；只读、安全限制仍在，不建议跳到 shell 读被拦文件 |
| K3 | `创建 reports/daily.md，内容是两行：# Daily 和 Approved fixture.；可以创建缺失的 reports 目录，除此之外不修改任何东西。` | 目录和文件分别准确预览；批准后目录/文件存在、内容 exact、read-back 与最终交付；拒绝版本用离线 tests 证明，不重复消耗 |
| K4 | `使用解释器 <REAL_PYTHON>，参数仅为 generate_report.py，在当前工作目录运行。生成后让我确认 generated.txt 的实际内容。不要换命令。` | exact process preview、真实 exit 0、文件内容 bounded process output 换行、后置 confirm_file 和交付；不能用先手动创建文件冒充进程成功 |
| K5 | 新任务只把 greet.py 中字符串句号改成感叹号；第一次写入批准前由操作者追加一条合成注释 | 旧批准作废，重新预览保持外部注释；再次批准只改标点，实际 bytes 正确；若先做拒绝变体，首次 n 后零后续 model/effect，计入同一 8 次预算 |

K1/K4 是上轮失败回归，优先执行。执行顺序可以 K1→K4→K2→K3→K5，但每条的冻结预算单独登记。已经成功的真实行不重复跑三连；最后变更若影响该行，需要复测但仍在原本预算内。

## 6. 可选补证，不扩大修复范围

只有 K1–K5 已 PASS 且总预算有剩余才做：Memory 两条消息保存/新会话召回、Skill 文本约束、MCP benign echo、单 SubAgent 结果回传。使用现有合成 fixture，完整例子可参考 `docs/handoffs/2026-09-13-dogfood-remediation/VERIFICATION.md` 的 G6–G9，但 model/credential/预算以本包为准。

SubAgent 如果另起 HTTP 进程，先证明 child 也共享该累计请求预算；否则跳过真实 child，标 BLOCKED。Browser 不属于本轮必测（不安装浏览器、不登录网站）；Scheduler 明确 deferred。可选项失败只记录准确缺口，不自动接着扩架构。

## 7. 每条证据记录

保存 candidate wheel hash、fixture hash、自然输入、disclosure/approval 决定数、model attempts（包括失败）、工具请求数/真实执行数、parent final、外部文件 hash、主动耗时/人工等待时间、退出码与残留进程检查。计数 ledger 是调用事实，响应 usage 缺失时成本写 unknown，不能按字数猜。

不导出真实 checkpoint/context，不贴 key、不保存认证 header；真实请求只含上述合成材料。事实分别写“观察/请求/执行/成功 receipt/最终交付”，不能互相替代。
