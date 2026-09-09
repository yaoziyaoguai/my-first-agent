# Round 015：gitdir 指针文件可读禁写闭环计划

状态：**verified-closed / 未 commit、未 push**

## Outcome

在 `read-only` / `workspace-write` 两种 confined policy 中，workspace 根目录下经
既有 bounded parser 验证的普通 `.git` gitfile 与其 resolved `gitdir:` target 必须
同时进入既有 `SandboxPolicyV1.git_metadata_roots`，继续保持可读、禁止写。

本轮只修复 `workspace-write` 已允许 workspace 写入后遗漏 pointer carveout 的契约缺口：
普通 workspace 文件仍可写，`.git` pointer 不能被覆盖、替换或删除，target 不能写，
而真实 linked worktree 的 `git status --porcelain=v1` 仍可用。`danger-full-access`
保留显式 filesystem bypass 语义。

## Evidence and external grounding

本地源码事实：

1. `_git_metadata_roots()` 对普通 `.git` file 已做 256-byte 上限、UTF-8、单行
   `gitdir: ` parser、strict target resolve 与 workspace-parent bound；
2. valid branch 当前只 `roots.append(str(resolved))`，遗漏 `str(candidate)`；
3. `compile_seatbelt_profile()` 先允许 workspace/temp 写，再对
   `git_metadata_roots` 的每个路径追加 `deny file-write*`；
4. 既有测试只断言 resolved target，没有断言 pointer 或真实 OS namespace mutation。

Primary sources：

- Git 将 workspace 根的 `.git` plain-text `gitdir:` 文件定义为 gitfile，常用于
  worktree/submodule：<https://git-scm.com/docs/gitrepository-layout>；
- Git linked worktree 文档说明 `.git` file 指向 `$GIT_DIR/worktrees/...`，并由该
  pointer 维持连接：<https://git-scm.com/docs/git-worktree.html>；
- OpenAI Codex 当前公开合同明确在 `workspace-write` 下同时保持 `.git`
  directory/pointer、resolved gitdir target 与 `.codex` read-only：
  <https://github.com/openai/codex/blob/main/codex-rs/core/README.md>；
- DeepSeek Harness 公开 sandbox 合同强调集中式 per-call filesystem policy；未找到
  pointer-specific guarantee，因此只借鉴 ownership 形状，不宣称能力等价：
  <https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/sandbox.md>。

Oracle Web fresh consultation：
`first-agent-r15-git-pointer-20260908-1340-a7c2`。已验证最高档位置 5/5、
committed user turn、完整 answer capture、`status=completed`，且该 session 的专属
Chrome PID 已退出、临时 Profile 已删除。Oracle 结论为 `PROCEED`：这是既有
metadata-integrity contract repair；最小 production change 是在全部既有 validation
成功后，把 pointer path 加入现有 roots 并保留 resolved target。

## Frozen ownership and data flow

```text
shell/sandbox tool prepare
  → build_sandbox_policy (唯一 filesystem policy admission)
  → _git_metadata_roots
      → validate regular .git gitfile
      → append canonical workspace/.git pointer
      → append bounded resolved gitdir target
  → SandboxPolicyV1.identity_values / policy_digest
  → existing exact approval + EXECUTING checkpoint
  → fresh admission / policy_digest comparison
  → NativeSandboxExecutor
  → compile_seatbelt_profile
      → workspace/temp allow-write
      → pointer + target deny-write carveouts
  → SeatbeltConfiner → existing runner → result checkpoint
```

Ownership 不变：policy builder 独占 metadata path derivation；immutable policy identity
携带结果；compiler 只翻译 policy；registration/Runtime 继续负责 fresh binding、批准与
checkpoint。不得在 shell、executor 或 runner 复制 `.git` 特例。

## Acceptance contract

1. 仅在普通 `.git` file 完成既有 size/decode/shape/resolve/bound validation 后，按稳定
   顺序把 `str(candidate)` 与 `str(resolved)` 同时加入 `git_metadata_roots`；invalid
   pointer 不得产生 partial policy。
2. pointer 和 target 都必须出现在 compiled profile 的 `deny_write_subpath` 中，均不
   得出现 `deny_read_subpath`；`.codex`、writable roots、network/private/sensitive
   clauses 不变。
3. policy identity 已包含 ordered `git_metadata_roots`；新 pointer entry 自然改变
   policy/profile digest。不得新增 digest、schema、receipt、migration 或兼容旧 digest
   的 fallback。旧 pending binding 由既有 fresh-admission comparison fail closed。
4. policy/profile Red 必须因 pointer 缺失或 pointer deny 缺失而失败，不能因 fixture
   malformed/unresolved 失败。覆盖 absolute 与 relative 的合法 in-bound target。
5. out-of-bound test 必须使用真实存在、但位于允许 parent 外的 synthetic target，证明
   命中的是 bound rejection 而不是 resolution failure；既有 oversized/malformed/
   unresolved rejection 保留。
6. 真实 Darwin test 必须走既有 public `shell_exec` registration → binding → real
   `SeatbeltConfiner` → executor/runner；不得 hand-write profile 或 mock confiner/runner。
7. 真实测试至少证明：普通 workspace write 成功；`.git` 与 target sentinel 可读；
   `.git` truncate/overwrite、prepared-file atomic replacement、unlink 均失败；pointer
   仍为普通文件且原 bytes 不变；target overwrite/create 失败且 bytes 不变。
8. target 写拒绝必须用位于 otherwise-writable workspace 内的 valid synthetic gitfile
   fixture 证明，排除“只是 workspace 外默认禁写”的假阳性。
9. genuine linked worktree fixture 必须证明 ordinary `git status --porcelain=v1` 成功并
   报告已知 working-tree state；不得静默替换为 `--no-optional-locks`，也不得开放
   `index.lock` 例外。
10. explicit danger shell control 只在 disposable/reset fixture 上证明上述 mutation
    本来可执行；由于 `shell_exec` 固定 network=off，evidence 必须如实记录 Seatbelt
    network-only，而不能标为 backend-none。
11. denied mutation 必须检查 operation exit/error 与 host-side bytes/existence/type；
    missing fixture、profile load failure、backend unavailable 或后续成功命令掩盖前序失败
    均不算保护成功。
12. macOS acceptance 机上的 backend unavailable 是失败，不以 skip 替代；非 Darwin
    仍沿用现有 skip convention。

## Product contract

- 用户无需理解 linked-worktree administrative layout：工作文件可写、仓库状态可读，
  confined 命令不能悄悄重定向 workspace 的 repository identity。
- 需要修改 Git metadata 的 `git add`、`git commit`、`worktree repair` 等继续按既有
  read-only metadata 边界准确失败；本轮不自动升级权限、不增加 approval。
- 本轮只保证已存在、稳定、普通 regular gitfile 的 scoped contract；不宣称 arbitrary
  host write、Seatbelt escape、content/inode pinning 或全拓扑原子性。

## Non-goals

- 不新增第二套 Runtime/model/tool loop、backend、approval path、feature flag、schema、
  service locator、capability 或 dynamic permission。
- 不修改 Runtime、ContextManager、ToolRuntime、shell/executor/runner、PATH、checkpoint
  ordering、process recovery 或 output bounds。
- 不扩大既有 gitdir target bound，不递归读取 `commondir`，不 broad-deny parent，
  不扫描 nested repository，不预留不存在的 `.git`。
- 不解决 symlink/hardlink、ancestor replacement、concurrent host mutation、open fd、
  admission-to-spawn TOCTOU；不因本轮暗示这些已经安全。
- 不新增 Git metadata write exception，不把 metadata 改为 unreadable。
- 不触碰 root untracked `tui/`、真实用户 repo、secret/credential/private/runtime 数据；
  不 commit、push、tag 或修改 remote。

## Smallest expected change set

Production：

- `agent/sandbox/policy.py`

Tests：

- `tests/sandbox/test_policy.py`
- `tests/sandbox/test_network_only_macos.py`

Evidence/status：

- 本计划
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`（只在 Green + audit 后记录事实）

若必须修改上述以外的 product code，停止并重新审查 scope。

## Sequential TDD and proof

1. Red A：扩展 gitfile policy/profile test，要求 pointer + target、两项 deny-write、无
   deny-read、稳定 identity；当前只因 pointer omission 失败。
2. Red B：增加 real macOS public-path regression；旧实现必须真实允许至少一次 pointer
   mutation，而测试要求拒绝。保留 mutation viability positive control。
3. Green：在现有全部 validation 与 bound check 后，只新增
   `roots.append(str(candidate))`，紧邻保留的 target append；可加一条解释边界的中文注释。
4. Focused：policy/profile unit、真实 Darwin pointer/target/read/status/mutation probes，
   再运行 sandbox public-path 邻接测试；迭代期只跑 touched-area。
5. Pi fresh diff audit 使用 `cc-switch-zhipu-glm` / `glm-5.3` / `thinking=max`、只读、
   无 session/tools/skills；P0–P2 必须为零。
6. 最后只运行一次 full gate：`git diff --check`、`.venv/bin/ruff check .`、
   `.venv/bin/python -m pytest -q -rx`。超时、截断或无 exit code 不算 PASS。

## Promotion boundary

本轮 PASS 只关闭 regular `.git` gitfile pointer 的 write-protection omission。它不重铸
017 detached delivery identity，不晋级跨平台/production-ready 声明，也不关闭
process EOF、多跳 symlink 或 truncation facts 等后续轮次。

## Independent review record

- 实施前 fresh Pi 使用 `cc-switch-zhipu-glm` / `glm-5.3` /
  `thinking=max`，以无 session、无 tools、无 skills 的只读方式审查 plan 与相关
  policy/tests，结论 `VERDICT: PASS`，无 P0/P1/P2。
- 其 P3 只记录既有病态 target 几何、gitfile symlink、Git optional-lock 版本差异、
  Darwin probe 文件命名与 private-root overlap；均未扩大本轮 scope。

## Implementation record

- Red A：unit test 精确显示 policy roots 首项仍是 resolved target 而不是 pointer；
  absolute/relative valid gitfile 的 expected tuple 因 pointer omission 失败。
- Red B：两个真实 Darwin public-path test 都到达 child 且 pointer overwrite 返回
  exit 0，证明旧实现真实允许 synthetic 与 genuine linked-worktree `.git` 被改写；不是
  malformed fixture、backend unavailable 或 profile load failure。
- Green 只在 `agent/sandbox/policy.py` 的全部既有 validation/bound check 后新增
  `roots.append(str(candidate))`，保留紧随其后的 resolved target；无其他 product code
  变化。
- unit 现在覆盖 read-only/workspace-write、absolute/relative target、pointer/target/
  `.codex` deny-write + readable、writable roots、stable digest，以及 malformed、>256-byte、
  unresolved、existing out-of-bound target 的 fail-closed。
- 真实 macOS 15.5 / arm64 / `/usr/bin/sandbox-exec` evidence：pointer overwrite、atomic
  replace、unlink 与 otherwise-writable workspace 内 target overwrite/create 均被拒；
  host-side pointer/target bytes、type/existence 均保持；独立 danger/network-off Seatbelt
  control 证明 mutation 可执行。genuine linked worktree 的 pointer/target 可读，普通
  `git status --porcelain=v1` 成功并精确报告 `?? untracked.txt`。
- focused evidence：新增三个 Red 曾为 `3 failed`；最小 Green 后同组 `3 passed`；两条
  real evidence probe `2 passed`；完整 policy/shell/tools/real-macOS 邻接集 `101 passed`；
  补齐 review P3 unit coverage 后最终 targeted set `21 passed`。touched Ruff 与 scoped
  `git diff --check` 均通过。
- fresh Pi diff audit 与补测后最终复核均使用 `cc-switch-zhipu-glm` / `glm-5.3` /
  `thinking=max`、无 session/tools/skills；两次均 `VERDICT: PASS`，无 P0/P1/P2。
- 本轮 final full gate 只运行一次：`git diff --check` PASS、全仓 Ruff PASS、pytest
  `3314 passed, 3 skipped in 347.65s (0:05:47)`，完整 exit 0。其后仅回填本计划文字；
  product code 与 tests 未再改变。本轮未 commit、未 push，未重铸 017 delivery identity。
