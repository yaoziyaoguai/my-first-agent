---
title: Default Sandbox Private Roots Plan
date: 2026-09-08
status: frozen
---

# 013 default Sandbox private-root policy wiring

## Outcome

默认 CLI composition 构造的 `sandbox_exec` 与 `shell_exec`，在
`read-only` / `workspace-write` 下使用同一份可信、静态、进入 policy digest 的
host-home private-root 集合。即使某个受保护路径在 composition 时尚不存在，也不能因
漏参或 `strict=True` 解析而从策略中消失。

本轮只兑现 017 已批准的 credential/private-root carveout，不改变 host filesystem
默认可读、workspace 写入、network、approval 或 completion 语义。

## Evidence

- `main.py` 调用 `build_sandbox_resources(workspace, state_root, PATH)` 时没有传入任何
  private roots；`build_sandbox_exec_registration` 与
  `build_shell_exec_registration` 的默认值均为空 tuple。
- `build_sandbox_policy()` 只把 `state_root` 与显式 `private_roots` 放入
  `unreadable_roots`。全局文件名模式仅覆盖 `.env` 与四类证书/密钥后缀；
  `.ssh/id_ed25519`、`.aws/credentials` 等不靠该模式得到完整保护。
- `HOME`/`TMPDIR` 指向临时目录只关闭默认查找位置，不能阻止命令读取已知绝对路径。
- Oracle Web 会话 `first-agent-r14-013-sandbox-process-8f4c` 在页面验证
  `Pro，第 5 项，共 5 项` 后返回 `PROCEED`，把默认 private-root 漏接列为本模块
  唯一首选切片；三入口合并、跨平台 backend 和大规模拆分均判为非本轮工作。
- 当前 Codex Seatbelt primary source 把 unreadable roots/globs 作为明确 policy 输入；
  DeepSeek Harness 当前文档同样让 deployment sandbox policy 独占 mode/root 组合，
  不由模型或工具自行扩大权限。

## Frozen private-root contract

composition root 从显式 `host_home` 派生以下有限、closed 相对路径；该 tuple 不是模型
参数、环境扫描结果或动态 registry：

- 目录：`.aws`、`.claude`、`.codex`、`.config`、`.docker`、`.gnupg`、
  `.kube`、`.opencode`、`.ssh`、`.ua`。
- 文件：`.git-credentials`、`.netrc`、`.npmrc`、`.pypirc`。

这份 v1 集合保护常见 credential 与 Coding Agent 私有状态，但不宣称识别所有秘密、
macOS Keychain、浏览器 profile 或任意第三方目录。后续扩展列表属于新的安全/产品决定。

## Acceptance contract

1. `build_sandbox_resources` 必须显式接收可信 `host_home`；真实 CLI 只在 composition
   root 传入当前用户 home。Provider/model/action/tool arguments 不能提供或修改它。
2. `host_home` 必须是 canonical、existing、real directory；不确定、symlink 或无效时，
   `build_sandbox_resources` 直接 `raise ValueError`，由既有 startup error 路径终止启动。
   不得把它映射成 Sandbox readiness 降级，更不得注册空保护集合后继续执行。
3. 两个 registration 获得同一顺序、同一解释基准的绝对 private-root tuple；普通
   confined policy 的 `unreadable_roots` 与 policy digest 必须包含该集合。
4. private root 可在策略生成时不存在。解析必须锚定 canonical host home，拒绝 `..`、
   绝对替换、NUL、控制字符及逃出 home；不得读取路径内文件内容或为凑齐列表创建目录。
   若条目已经存在或是 broken symlink，必须用 `lstat` 识别并保持既有 strict
   canonical/real 合同：任何 symlink 条目直接拒绝，不能把 deny 只绑定在可绕过的字面
   link 路径上。仅确实不存在的尾部路径可按 canonical home 锚定后词法保留。
5. fake home 下不存在的 `.ssh` / `.aws` 在 policy 生成后再由测试 control 创建，仍被
   编译为 deny read/write。测试只用假 sentinel，绝不读取真实凭据。
6. 真实 macOS Seatbelt 对照必须非空洞：control 先读到 fake sentinel；随后
   `sandbox_exec` 与 `shell_exec` 分别在 `read-only`、`workspace-write` 下启动并由 OS
   拒读；sentinel 内容不能进入 tool output、event、checkpoint 或模型上下文。
7. 被 OS 拒读的命令是已启动的 child outcome，不得伪报 `KnownNotExecuted`；backend
   unavailable、approval 拒绝或 binding 漂移仍保持零 spawn。
8. 正向对照保持：workspace-write 仍能修改 workspace，普通非 private host fixture
   仍可读，host toolchain 基线不变。不能通过禁整个 home 或拒绝所有命令让测试变绿。
9. danger/network、one-shot approval、`EXECUTING`/result checkpoint、receipt 与 host
   read-back completion 顺序不变；不得 fallback 到 `local_process` 或新增 Runtime owner。
10. 任一派生 private root 与 workspace 相等、包含 workspace 或位于 workspace 内时，
    composition 直接拒绝该自相矛盾配置；不能以一份既承诺 workspace-write 又把 workspace
    设为 unreadable 的 policy 启动。

## Non-goals

- 不合并、删除或新增 `local_process` / `sandbox_exec` / `shell_exec`。
- 不修本轮 Oracle 另外发现的 PATH 批准/执行漂移、`.git` pointer、双 pipe EOF、
  多跳 symlink 或 truncation facts；这些各自需要后续独立轮次。
- 不新增 Linux/Windows backend、Docker、VM、credential broker、动态 secret 扫描、
  自动安装、后台进程、TTY 或权限 preset。
- 不读取真实 home 下任何 private 文件，也不把真实路径或内容写入测试证据。
- 不改 017 已冻结的 broad design；本计划只修复其已声明而未贯通的默认组合输入。

## Smallest expected change set

- `agent/composition.py`
- `agent/sandbox/policy.py`
- `main.py`
- `tests/sandbox/test_composition.py`
- `tests/sandbox/test_policy.py`
- 一处最接近现有真实 Seatbelt journey 的 sandbox test 或 runner（仅当可复用不足）
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

若需要修改 Runtime action/state/checkpoint、ToolRuntime approval/receipt、provider、
`agent/process/runner.py` 或新增持久化类型，停止并重新审查范围。

## Sequential TDD

1. Red：默认资源 builder 的两个 registration 必须收到同一 closed private-root tuple，
   且真实 `main.py` 显式提供 host home；Green：只在 composition 层派生和传参。
2. Red：不存在的 home-relative private path 被 policy 保留并编译为 deny；host home、
   existing/broken private symlink、非法/逃逸/与 workspace 重叠路径均直接 raise；Green：
   增加最窄的 private-root canonicalization seam，基础四 root 的 existing/canonical
   合同不变。
3. Red：两个公开工具 × 两种 confined mode 的 fake sentinel 行为；Green：复用已有
   registration/policy/executor，不加工具专属安全分支。
4. Real macOS：control readable 后，两个工具均由 Seatbelt 拒读，且正向 workspace/
   ordinary-host fixtures 不回归。非 Darwin 只做明确 skip，不伪装 E3。
5. 审查 diff 只覆盖本合同；Pi 独立审计无 P0-P2 后，运行 touched-area gates，最后只跑
   一次 `git diff --check`、Ruff 与完整 pytest。

## Promotion boundary

本轮通过只表示默认 private-root 输入已贯通，不重新铸造或声称更新 017 detached
delivery identity，也不表示 Oracle 的 PATH/metadata/process-lifecycle 后续发现已关闭。
