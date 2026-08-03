# E3 Independent Review Receipt (2026-07-25)

本 receipt 由**非 E3 executor session** 的独立 reviewer 填写（GLM 5.2[1M]、effort=max）。它不是产品能力，
也不是 executor 自评。reviewer 的首要职责是尝试**推翻** executor 的 E3 完成结论；只有独立证据通过后才
晋级 claims 并 re-seal。本 receipt 不复制 raw prompt/response、credential 值、绝对用户路径或临时 inventory；
只记录 bounded verdict、counts、destination/model identity（非秘密）与 limitations。

## 范围与边界

- 目标：隔离副本 `…/my-first-agent-general-loop.FMHzBg`（baseline_commit
  `7d935ac4af7121c54e1bdcc600763c3f0fbf54c2`，009 materialized 工作树）。
- 不触碰原仓库；不 commit/push/tag/改 remote；不读取/打印/记录 credential 值；不创建 Claude project
  memory/auto memory/外部持久记录。
- 批准的真实 destination：`anthropic_compatible`，base URL `https://open.bigmodel.cn/api/anthropic`，
  API model code `glm-5.2`（Claude UI `[1M]` 为上下文窗口标注）；credential env 名 `ANTHROPIC_AUTH_TOKEN`
  （由 composition root/child 自行读取，reviewer 从不接触其值）；timeout ≤ 120s。仅发送现场合成非敏感文本。
- 阶段 1 严格只读；进入阶段 2 写入前，所有独立检查与自动门均已通过。

## Phase 1：亲自执行的独立检查

### A. Records / claims 卫生
- 7 份 `docs/acceptance/records/2026-07-25-*.md` 模板字段完整（revision、user-approved task、
  destination/profile、data/effect scope、baseline、success criteria、result、counts、checkpoint
  terminal status、observable delta、limitations）。
- grep 全量 records：无绝对用户路径、无 credential 值、无 raw 私有 prompt/response；`ANTHROPIC_AUTH_TOKEN`
  仅作为 env 名出现；destination/model 为非秘密 identity。
- `CURRENT_CAPABILITY_STATUS.md` 被 executor 准确标注为“E3 evidence pending independent review”，
  control-seal digest drift 为有意 pending；executor 未自封 `accepted`、未伪造 reviewer receipt。

### B. Provider adapter smoke（独立，真实）
- 经产品入口 `main.main(argv, input_fn, write_fn)`（`--provider anthropic_compatible --model glm-5.2
  --base-url https://open.bigmodel.cn/api/anthropic --credential-env ANTHROPIC_AUTH_TOKEN --timeout 90`）
  对真实 `glm-5.2` 发送一条现场合成非敏感算术题。
- 结果：rc=0，模型返回**正确可核对算术答案**（非 fake、非 prompt-echo），output bounded。
- 意义：7 份 records 共用的真实 provider 适配器在批准 destination 端到端可用；攻击向量“fake provider 冒充”
  与“模型仅复述 prompt”被排除。

### C. MCP 首次 safety-state CLI bug 的 Red/Green（独立）
- Named test `tests/mcp/test_integration.py::test_main_composes_mcp_when_safety_latch_not_yet_created`
  显式运行：**PASSED**（Green）；它真实调用 `main.main()`，不是内部 API。
- Red 根因复现（mktemp，不改仓库）：不存在的路径 `Path.resolve(strict=True)` → `FileNotFoundError`
  （Red 根因）；`strict=False` → 正常（Green）；`McpSafetyLatch(missing).status() == "clear"`（产品
  “文件缺失即 clear、首次 invocation 才惰性创建”的设计，与 memory store 一致）。
- 安全独立性：`agent/mcp/safety.py` 的 `_read_unsafe`（`O_NOFOLLOW` + `S_ISREG` + owner-only mode）与
  `_write`（`O_NOFOLLOW` + `0o600` + atomic replace + fsync 目录）独立于 composition-time `resolve`。
  故 `strict=False` 修复**只放宽“路径不存在”要求，未放宽 owner/mode/no-follow 安全**；修复 surgical。

### D. SubAgent 真实 HTTP child 路由（独立，结构性）
- `agent/subagent/contracts.py`：`ProviderDeadlineCapability.from_provider` 用
  `getattr(provider, "deadline_contract", None)` 判定；真实 HTTP provider 不暴露 `deadline_contract`
  属性 → 返回 `None` → `main.py` 走 `ChildProcessRunner`（进程隔离、`process_terminated` receipt），
  **非** in-process `ChildAgentRunner`。
- 攻击向量“SubAgent 没走真实 child HTTP”被结构性排除；确定性 suite（`test_process_runner`、
  `test_receipt_contract`）覆盖 `process_terminated` receipt 与 killpg/exit-confirm。

### E. Memory / Scheduler / TUI（独立结构性核验 + 确定性 suite）
- Memory：`test_integration`（跨会话同 workspace/profile 召回）、`test_store`（revision CAS）、
  `test_source`（被动 ContextSource 投影、bounded untrusted）通过；record 的 MARLIN/OAK 类 token 仅存在于
  workspace-外 store 文件、model 不可能凭空猜中。
- Scheduler：`test_caller`/`test_contracts` 覆盖 external caller fire → `needs_human` → resolution →
  duplicate replay（`accept_action` 返回 `REPLAYED`，不触达 provider/tool，不增 effect）。
- TUI：`tests/tui/test_approval_journey.py` 用 `app.run_test() as pilot` + `pilot.press("enter"/"a"/"r")`
  真实键盘按压（非内部 API）；attack“TUI 不是键盘路径”被排除；restart 零 provider 调用由 R19 oracle 覆盖。

### F. 自动门（亲自重跑，真实 exit code）
- `git diff --check` → exit 0（无 whitespace/conflict）。
- `ruff check .` → All checks passed，exit 0。
- `python -m pytest -q`（普通）→ **375 passed**，exit 0。
- `python -W error -m pytest -q`（warnings-as-errors）→ **375 passed**，exit 0，零 warning。
- `verify_materialized_tree.py --check-membership` → 954 entries ok，exit 0。
- `verify_materialized_tree.py --content` → non-editable install / origin / console-entrypoint origin /
  deny-network（sandbox-exec）/ ruff / pytest 375 全部 PASSED，exit 0。
- `verify_materialized_tree.py --control-seal` → **仅** `CURRENT_CAPABILITY_STATUS.md` digest drifted
  （预期的 pending-reviewer 状态），**无其他** control file 失败、无 ordinary digest drift；executor 未
  自行 re-seal、未伪造历史 control file。

### G. 进程 / repo stray state 核查
- 发现两个孤儿进程（`…/T/tmp4kcty3n5.py`，executor 13:16 创建，PPID=1 已 reparent 到 launchd，运行 ~5h50m）：
  脚本为故意忽略 SIGTERM 的 sleeper（进程隔离 fault-injection fixture 残留）；**无网络连接、无打开的
  repo/credential 文件、脚本内无 token/secret 引用**。已 SIGKILL 进程组并移除 tmp 脚本；最终复扫为空。
- repo 根目录无 stray 状态/临时文件；repo 内无近 1 天 stray 写入。**repo 无 stray state**。

## Phase 1 结论

7 项 capability 均有独立可信 pass；自动门满足（control-seal 仅预期的 CURRENT_CAPABILITY_STATUS drift）。
无 P0/P1/P2 证据完整性缺陷；无 credential 泄漏；无 repo stray state。唯一非证据项（孤儿 sleeper 进程）为
mktemp 外部残留，已按 protocol 授权清理。→ **REVIEW_PASS，进入 Phase 2**。

## Phase 2：晋级 / receipt / re-seal（已完成）

1. 本 receipt（`docs/acceptance/2026-07-25-E3_INDEPENDENT_REVIEW.md`）创建。
2. `docs/architecture/CURRENT_CAPABILITY_STATUS.md`：Minimal Runtime Kernel / Skill / MCP / Memory /
   SubAgent / Scheduler / TUI 七项由 `locally-verified` 晋级 `accepted`（v1 reference task）；保留准确
   limitations；历史 G0–G8 / 009 段落原文不改写。
3. `README.md` 的“晋级 `accepted` 仍待独立 review”更新为 independently accepted。
4. `009_DELIVERY_MANIFEST.json`：新增本 receipt 的 ordinary entry（add）；更新 README 等 ordinary
   changed file 的 sha256；以独立 reviewer 身份更新 `CURRENT_CAPABILITY_STATUS.md` 的 control digest，
   `seal_state` 保持 gate 要求的 `sealed-u8`；**未改动其他历史 control file**。
5. 重跑全部门：`git diff --check`、ruff、pytest（普通 + warnings-as-errors）、`--check-membership`、
   `--control-seal`、materialized `--content` 全部 exit 0、无 warning/截断（结果见下“最终复跑”）。
6. 复确认无测试进程/临时数据/secret 泄漏；未写任何 Claude memory。

## Verdict（七项）

| Capability | E3 verdict | 独立核验依据 | 仍不宣称的范围 |
|---|---|---|---|
| Minimal Runtime Kernel | accepted | 真实 provider smoke + 375 suite + record honest | 非完整通用 Agent；非任意 provider 语义 |
| Skill | accepted | governed activation/resource-read 应用 baseline 不具备的合成规则；375 suite | 不等于任意/远程/可执行 Skill |
| MCP | accepted | Red/Green 独立 + latch 安全独立 + repo-owned benign stdio 单次可数 effect | 不等于任意第三方/网络 MCP server |
| Memory | accepted | 跨会话同 workspace/profile 召回；CAS/revision；被动 untrusted 投影 | 非语义/向量化 Memory；非跨 owner 共享 |
| SubAgent | accepted | 真实 HTTP → 进程隔离 `ChildProcessRunner`（结构性强制）+ receipt suite | 非并发 SubAgent；非任意 child provider |
| Scheduler | accepted | external caller fire→needs_human→resolution→duplicate 不增 effect | 非 Scheduler CRUD；非持久化调度策略 |
| TUI | accepted | Pilot 键盘 `press` 真实路径 + CLI digest 等价 + restart 零调用 | 非跨平台；非并发会话已验证 |

## 最终复跑（Phase 2 收尾）

- `git diff --check`：exit 0。
- `ruff check .`：exit 0。
- `pytest`（普通）：375 passed，exit 0。
- `pytest`（warnings-as-errors，`-W error`）：375 passed，exit 0。
- `--check-membership`：954 entries ok，exit 0。
- `--control-seal`：all digests verified，exit 0（CURRENT_CAPABILITY_STATUS 已 re-seal）。
- materialized `--content`：ALL CHECKS PASSED，exit 0。
- 进程/临时数据复扫：空；无 secret 泄漏。

## Limitations（不因 accepted 而扩大的边界）

- `accepted` 仅对各自 **v1 reference task 的 bounded 任务**成立，**不是 production-ready**。
- 不等于：任意第三方/网络 MCP server；任意/远程/可执行 Skill；语义/向量化 Memory；并发 SubAgent；
  Scheduler CRUD/持久化调度；跨平台 TUI；并发会话。
- 真实 provider E3 仅覆盖各 capability 的**正向/bounded 路径**；unknown-outcome / fault 分支由 E1/E2
  确定性 fault matrix 覆盖（reviewer 已确认其存在于 375 suite），未在真实 provider 下现场重放。
- reviewer 未改写历史 `009_EXECUTION_LOG` / `009_INDEPENDENT_REVIEW` / `009_G0_G7_PROMOTION_REVIEW` /
  `009_G8_SUBAGENT_PROMOTION_REVIEW` 的当时事实。
