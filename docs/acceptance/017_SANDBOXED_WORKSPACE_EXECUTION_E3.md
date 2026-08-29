# 017 Sandboxed Workspace Execution E3（acceptance，frozen）

- Date: 2026-08-27（corrected native sandbox 版，取代 2026-08-26 Docker 版）
- Status: frozen-user-approved-2026-08-27（随 spec；用户已 review 并批准
  corrected native contract）
- Design: `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md`
- Spec: `docs/superpowers/specs/2026-08-27-native-sandbox-design.md`

> **Superseded 2026-08-27（用户裁决，方向层面）**：本文件原 Docker 版验收
> 合同（三连 Docker attempt、image digest、PACKAGE_REGISTRY proxy、
> ChangeBundle lifecycle、`NEEDS_017_DOCKER_CONFIG`）整体作废；既有
> Docker 017 的 seal/receipts（含 NEEDS marker）全部 superseded，不得
> 作为 promotion 证据。以下为 corrected native sandbox 验收合同。

E3 = 真实 macOS Seatbelt journey（bypass journey 除外）。receipt 绑定
source root digest、verifier digest、detached runner digest、wheel digest、backend identity
（**canonical executable path + platform/build facts + functional probe
result + profile digest**——`/usr/bin/sandbox-exec` 无稳定「版本事实」可
依赖；binary digest 若实现可安全绑定则作为额外字段，非当前承诺）、
policy mode（bypass 记 `backend=none / enforcement=unconfined`）；无
Docker receipt/镜像/proxy 字段。敏感读取验证一律使用**临时 fixture
sentinel**，不读取真实 credential。**所有拒绝 journey 必须非 vacuous**：
先以未隔离 control 证明测试前提（目标可写/可读/可连接），再证明
confined 失败且副作用未发生。

## U0 — Design/feasibility

- [x] corrected design/spec 已由用户于 2026-08-27 review 并批准冻结。
- [ ] 本机 backend qualification 只读探测结果记录于 execution log（不安装、
  不启动任何服务）：`/usr/bin/sandbox-exec` 存在性与最小 profile 可编译性。
- [ ] backend unavailable 的 closed reason codes 冻结（如
  `sandbox_exec_missing`、`seatbelt_profile_refused`、`qualified`）——
  仅作用于 confined modes。

## U1 — Deterministic（fake backend transcript）

全部 journey 用注入替身验证合同，不证明真实隔离：

- [ ] policy：三 mode closed 语义；`workspace-write` 可写集恰为 workspace
  （排除 carveouts）+ per-invocation temp；`read-only` 除 backend 必需
  literal 外不写。
- [ ] carveouts：`.git`/`.codex` 可读、写拒（git metadata 语义）；
  credential/private/product runtime roots 与 `.env`/secret 模式读写都拒
  （unreadable）；不笼统拒整个 host home 读。
- [ ] confine interface：`confine(argv, policy)` 返回 wrapped argv +
  enforcement facts（bypass 记 `backend=none / enforcement=unconfined`）；
  adapter 不认识 Goal/approval/state。
- [ ] 路径：workspace root canonical 化；symlink 漂移 fail closed。
- [ ] network：OFF 拒绝一切外联；full network 与 exact command/policy
  一起批准；filesystem seam 与 network policy 分离。
- [ ] env：confined env 只含 closed allowlist，无 provider credential；
  HOME/XDG/cache 指向 per-invocation temp。
- [ ] backend unavailable：仅 confined modes fail closed（零执行）；
  bypass 不依赖 backend。
- [ ] checkpoint/ordering：EXECUTING → invoke → result checkpoint 顺序不变。
- [ ] completion：exit 0 alone 不得 VERIFIED_DONE（receipt + read-back 不变）。
- [ ] mutation oracles：伪造 receipt、越权 mode、bypass 伪装成受约束执行、
  静默降级、cleanup 不确定复用、false completion 全部 fail closed。

## U2 — Materialized real E3（真实 macOS Seatbelt，三连 attempt 全 Green）

前置：sealed materialized tree、clean venv 离线安装与完整离线 gate、
backend qualification qualified（仅 confined journeys 需要）。

每 attempt（fresh workspace 与临时目录、临时 credential sentinel）：

1. **host toolchain 可用**：confined 进程读取并执行 host 工具链（至少
   `/bin/sh` 或当前 interpreter）成功。
2. **git metadata 可读、写被拒**：fresh git fixture（临时 repo）下 control
   先证明 fixture 可读；confined 读取成功、写入失败。
3. **workspace 内写成功**：confined 写入 + 读回一致。
4. **workspace 外写拒绝**：control 先证明临时 target parent 未隔离可写；
   confined 写失败且目标未出现。
5. **unreadable credential sentinel**：先创建 sentinel 并由 control 读取
   成功，再将 exact fixture path 加入 unreadable carveout；confined 读取
   失败。不得使用真实 credential。
6. **network OFF 拒绝**：启动临时 loopback listener，control 连接成功；
   confined 连接失败（不依赖公网状态）。
7. **process tree 继承**：child 写入一个 control 已证明可写的外部临时
   target；confined child 失败且目标未出现。
8. **timeout/cleanup**：超时被 cap、进程组清理可证明。
9. **backend unavailable fail closed（仅 confined modes）**：模拟探测失败
   时 read-only/workspace-write 零执行；danger-full-access 不受影响。
10. **approval escalation / bypass facts**：danger-full-access 无 exact
    approval 零执行；批准后只写**测试专用外部临时 fixture**，receipt 以
    明确 `backend=none / enforcement=unconfined` facts 记录，不碰用户其他
    路径（不要求 sandbox backend）。
11. **read-back completion**：exit 0 + receipt + host read-back 齐全才满足
    criterion。

失败处理：任一 attempt 任一步失败 → 该 attempt FAIL，不得重跑覆盖；三连全
Green 才 PASS。若代码、deterministic gates、materialized 前置全部闭合而
backend 真不可用（本机禁用 sandbox-exec 等）→ 记录
`NEEDS_017_SEATBELT_BACKEND(stage=U2)`（仅阻塞 confined journeys；bypass
journey 不受此 blocker 影响），不得降级。

## U3 — Fresh independent review

未参与实现的 reviewer 独立检查：产品旅程（自动 qualification → 三态提示
→ confined 命令 → escalation → read-back completion）、读写模型与
carveout 声明真实性（toolchain/git metadata 可用、credential sentinel
不可读）、唯一 Runtime/ToolRuntime owner、receipt identity 精确绑定
（含 bypass 的 unconfined facts）、false-completion oracle。任何 fix 使
seal 失效，重跑受影响 focused gate + 最终一次完整 source/materialized/E3。
