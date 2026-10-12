# 验证、合成材料与成本边界

## 先离线，最后真实模型

1. 核对 BASELINE，保留起始 diff。每个切片先用现有 ScriptedProvider、fake tool、tmp_path 写行为 Red，再实现 Green；使用 `tests/kernel/fakes.py`，不复制另一套 runtime。
2. 切片仅跑对应 tests。新的测试须实际失败于修复前，不用断言新增 helper 存在来伪造 Red。
3. 最终稳定候选才跑一次下面全量；若此后又改代码，该新候选需重新跑受影响检查，风险跨内核时重跑 full。不要按每个小改动无差别全测。

```bash
git diff --check
.venv/bin/ruff check .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

每个命令分别记 exit code、完整摘要。超时、截断、进程仍运行不能算通过。因沙箱禁止 loopback 等环境原因失败时保留结果，明确申请相应能力或记 BLOCKED；不能通过禁用测试/弱化断言掩盖失败。

## Materialized 验证

从最终工作树构建 wheel，记录 wheel SHA-256，非 editable 安装到新 venv；从仓库外运行并核对 `agent.__file__` 和 `main.__file__` 来自该 venv 的 `site-packages`。用本地已有依赖优先；缺包先报告，不擅自更新全局环境。

不要用 `PYTHONPATH`、cwd 导入、源码 monkeypatch 或 editable 安装来声称 wheel 通过。若使用 system-site-packages，必须明记“依赖环境非纯净”，不能再称 clean install。

本轮需要 CLI 的 `--help/--version`、合成状态 root 的 fake 启停、W1/W2/W4/W5 的已安装入口冒烟。无需启动 019 launchd 或更新历史 seal/promotion manifest；安装回归与 capability accepted 不是同一结论。

## 真实模型前提

- 用户为本次测试显式提供进程环境凭据；只由 composition root 读取，不能把值放在命令行、资料包、截图、日志、模型上下文或 Git。
- 历史记录曾使用已失效的短名；当前官方配置是 `openai_compatible`、
  `deepseek-v4-flash`、`https://api.deepseek.com`、`/chat/completions`、thinking disabled、
  非 strict。不要使用旧 `deepseek-chat` 或 `deepseek-flash`。
- 这是历史已核对基线，不保证执行日仍相同。若服务报不存在/不支持，先核对 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/)；不要偷偷换模型。
- 普通 Tool Calls 说明见 [官方工具调用文档](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)。本轮不切 beta/strict，不把开放 schema 导致的 strict incompatibility 混入核心任务失败。
- 数据仅下述合成 fixture；不把真实仓库、用户历史、Memory、远端 MCP 内容发送出去。人工在产品预览中逐次作批准/拒绝，不能通过 fixture 自动同意来证明可用性。

示意启动命令（先把占位路径换成已创建的合成路径；环境中的 key 由用户另行注入）：

```bash
/ABSOLUTE/CANDIDATE_VENV/bin/first-agent \
  --workspace /ABSOLUTE/SYNTHETIC_WORKSPACE \
  --state-root /ABSOLUTE/OWNER_ONLY_STATE \
  --provider openai_compatible \
  --model deepseek-v4-flash \
  --base-url https://api.deepseek.com \
  --request-path /chat/completions \
  --credential-env FIRST_AGENT_DOGFOOD_API_KEY \
  --thinking-mode disabled \
  --timeout 90 \
  --transport-audit-ledger /ABSOLUTE/SYNTHETIC_AUDIT.jsonl
```

workspace、state、Skill、Memory、MCP fixture 应位于本次新建临时根下的不同子目录；state/Memory 不在 workspace 内，owner-only。不要复用个人 state root。临时根用 `mktemp -d` 创建，文件用编辑工具写入，保留测试清单；不递归清理未确认的目录。

### 合成 fixture（UTF-8，结尾换行）

`notes/product.md`：

```text
# Product
- TODO: add CSV export
- Keep approval explicit
```

`notes/engineering.md`：

```text
# Engineering
- TODO: add an export test
- Never log credentials
```

`greet.py`：

```python
def greet(name):
    return f"Hello, {name}."
```

不要预建 `docs/`，以便测 missing-parent；其它写入任务用根路径避免混淆。

合成 Skill 文件必须先对照当前 catalog fixture 的合法布局，只注册这一个目录：

```markdown
---
name: release-check
description: Return a short text-only release checklist.
---
Use exactly these headings: Correctness, Safety, Evidence.
Write exactly one short check under each heading.
Do not create or change files. Do not run commands.
```

MCP 仅用 `tests/fixtures/mcp/stdio_server.py` 的 benign echo，按 `tests/mcp/test_integration.py` 当前 catalog 合同生成合成 operator catalog；固定解释器与 cwd，只暴露 echo，不使用真实 server 或 `environment` 工具。不要发明新的 catalog schema。

## 最小真实任务矩阵

每条用自然用户输入，不加“你必须先建 Goal”教模型绕过产品入口。仅 G8 因用户明确要求委派，保留委派本身；不强迫其内部控制实现。

| ID | 用户任务与操作 | 必須证明的结果 |
|---|---|---|
| G1 | 两句话解释高内聚低耦合；再用一句生活化例子 | 文本符合约束，无工具/副作用；跟随用户语言 |
| G2 | 只读取 `notes/product.md`，列 TODO，不修改 | 原文正确、有来源；workspace 不变 |
| G3 | 在根创建 `summary.md`，精确内容 `# Summary\nApproved fixture.\n`；第一次 n | 文件不存在；拒绝后不继续模型/工具调用或重弹批准；用户能退出/调整 |
| G4 | 新任务重复 G3 并批准；之后只改 greet 标点，批准前由测试者加一行注释 | 写入 exact preview/read-back；stale 批准不得直写；新批准保留外部注释；给 /new 提示 |
| G5 | 合成 `generate_report.py` 只写 `generated.txt` 为 `bounded process output\n`；要求运行并确认内容 | 批准前 preview 无矛盾；精确进程 effect、exit/status receipt、当前文件展示及单独确认；无“未来 SHA”要求 |
| G6 | 单独说 `本项目的测试代号是 SABLE-27`；再要求把上一条完整原文记入 Memory；批准；/new 后询问代号 | admission 精确匹配、合成 store 成功 receipt/记录、召回正确；记录额外澄清次数；不去改文件/外部求证 |
| G7 | “请使用 release-check Skill，按它要求输出三个 heading 各一句检查。只输出文本，不创建文件，不运行命令。” | activation receipt/正文进入对应上下文有证据；输出准确；无 write/process 请求 |
| G8 | “请委派给一个子 Agent，用两点解释小任务为什么也需要验收。父子都不要读写文件或运行命令，最后汇总两点。” | child 成功/失败 receipt 与答案分别记录；parent 交付；无不相关本机命令；不因只出现 tool result 就判 PASS |
| G9 | “只调用 mcp__dogfood__echo，传入 HELIX-13，然后直接告诉我结果。不运行本地命令。”（以实际 catalog 暴露名称替换） | exact approval、实际 tool status/receipt/返回标记、parent终答三层均证实；不能用本机 echo 替代 |
| G10 | provider 等待时 Ctrl-C，随后重启合成任务 | 无 traceback；无重复 effect；状态保留或进入准确恢复；不谎称远端调用已取消 |

G5 的脚本调用使用已解析的真实 Python executable，不使用 pyenv shim 作为“确定的解释器”证据。same-UID local_process 不是 sandbox；只允许本次合成脚本，不顺手批准模型临时发明的命令。

G8/G9 如遇既有 receipt 合同不能闭合，记录 BLOCKED 和具体缺口，不把“正确阻塞”算成功交付。没有可用 MCP/Skill extra 时，只标相应行 blocked，不影响其余离线修复。

W6 的配置切换、0755、缺父目录和 provider endpoint 用离线 fixture 验证；只在 J3 具体原因仍不清且额度允许时增加一条真实 missing-parent 对照，不自动扩大矩阵。

## 预算与度量（操作者规则，不是已内建的硬限额）

- 每个真实 journey 最多 8 次实际 HTTP model attempts（包括重试和 child）；整轮最多 50 次。工具/控制调用和人工确认另计。
- 每次授权/提交前后检查已有 audit ledger；达到上限就停止提交。运行中可能有多个内部调用，操作者计数不等于严格原子 hard cap：若无法在既有调用边界可靠控制，先停止真实测试并记录限制，不声称预算已被技术强制。
- 单次 HTTP timeout 90s；单 journey 活跃运行墙钟上限 5 分钟，等待用户审批的时间单列。没有进展或第二次相同失败时停止该用例诊断，不重复消费到“偶然成功”。
- 记录 provider attempt 数、重试数、tool call/effect 数、disclosure 数、effect approval 数、手动纠正次数、到首个可见反馈/终答的单调时钟时间。token/cost 仅用官方响应实际提供的 usage 或账户记录；缺失则 unknown，不由字数估算成事实。
- 检查进程是否仍活着，工具返回 session id 后追踪到 exit；没有进程/机制在运行时不要说“仍在 loop”。长等待给用户简短进展。

## 证据与完成标准

每条保存一份脱敏摘要：candidate identity、fixture hash、自然输入、各 approval 决定、实际 status/receipt（仅必要字段）、关键结果、文件 hash/副作用计数、计时方法、退出码。不要默认全量转储 checkpoint/context；合成记录也按最小字段导出。

- 纯文本成功≠tool 调用成功；tool result≠successful receipt；receipt成功≠parent交付；四者分别判断。
- 输出 truncated 的步骤不能证明未显示部分；重新用有界摘要/断言核对，不把 tail 当全部日志。
- 当前本包的 89 Green 是起始回归，不是新 Red 或最终验收。
- 没有真实模型/依赖/权限时可以交付离线修复，但结论必须是“离线通过，真实验证未完成”。
- F1–F11 都有明确处置记录、必须修复项有 Red/Green、安全回归和相关真实证据，才可宣布本包范围闭合。P3 不进入无限循环，不自动开下一轮架构/能力扩张。
