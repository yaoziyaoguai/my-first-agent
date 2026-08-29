# 017 Execution Log

- Plan: `docs/superpowers/plans/2026-08-26-017-sandboxed-workspace-execution.md`
- Spec: `docs/superpowers/specs/2026-08-26-governed-execution-program-design.md`
- Executor: Claude Code GLM 5.3 `effort=max`
- 起始状态：main 分支工作树含用户与前序已接受改动（016 seal 后续 + 未跟踪
  `agent/process/group.py`、`agent/runtime/tool_governance.py` 等），全部保留、不 revert。
- 规则：不 commit/push/branch；每任务记录 focused gate 与 next task；只有 Task 9 跑一次
  完整 source suite，Task 10 跑 materialized/full/真实三连。

## Design correction 2026-08-26（主审裁决：multi-command lease）

Plan Task 4 原文 argv 序列（每条命令 create→cp→start→wait/logs→copy-out→rm）与已批准
port contract（`provision(spec)` 无 command、`execute(handle, command)` 可多次）矛盾。
经主审批准冻结 corrected lifecycle：provision 一次 hardened long-lived container
（idle-command contract `sleep infinity`）+ copy-in + start；每条 exact command 一次
bounded `docker exec`（`max_command_count` durable 预算）；capture copy-out 到 fresh
empty attempt 目录；close 只做 exact-labelled（deterministic name + labels read-back）
精确清理。`docker wait/logs` 不属于 lifecycle。高层 owner/authority/UX 不变。
`combined_cap_bytes/disk_cap_bytes` enforcement 由 Task 6/7 governance 拥有（adapter v1
只实施 per-stream caps 与 wall/pids/memory/cpus）——已记录于 design 文档与
`SandboxResourceLimitsV1` 注释，不假装已实现。

## Session 记录

### Task 1 — Freeze contracts + backend qualification（2026-08-26）

- 创建 `docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md`（冻结 owner/state/
  authority/network/unknown-outcome/qualification 合同与 closed reason codes）。
- 创建 `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`（冻结 U0–U3 矩阵与三连
  真实 attempt 合同，含 `NEEDS_017_DOCKER_CONFIG(stage=U2)` 规则）。
- Red：`tests/sandbox/test_backend_qualification.py`（12 tests）先因
  `ModuleNotFoundError: agent.sandbox` 失败，符合预期。
- Green：`agent/sandbox/qualification.py`（`DockerQualification` + `SubprocessQualificationRunner`
  + frozen `QualificationReport`）。实现要点：仅 2 次 argument-vector `docker version/info
  --format {{json .}}` 调用、cap 64 KiB、deadline 5s、strict JSON、FileNotFoundError 单独
  分类为 `docker_cli_missing`；version 与 info 的 ServerVersion 任一 < 29 →
  `docker_server_too_old`；无 seccomp → `security_probe_failed`；零 host process 调用。
- Focused gate：`pytest tests/sandbox/test_backend_qualification.py` → **12 passed**；
  `ruff check agent/sandbox/ tests/sandbox/` → clean；`git diff --check` → clean。
- U0 本机探测（只读，未启动/安装任何服务）：`reason_code=docker_daemon_unavailable`
  （client 29.3.1 存在，daemon 未运行）。E3 U0 勾选项「qualification 结果记录」以此为准；
  Task 10 若其余前置全闭合，此为 Docker 配置缺口的实证。
- next_task=2

### Task 1 补丁 — Codex narrow audit：捕获期 cap（2026-08-26）

- Audit finding：`SubprocessQualificationRunner` 原实现 `subprocess.run(stdout=PIPE)` 后切片，
  cap 未在捕获期强制——恶意/异常 docker binary 可使 probe 无界缓冲。
- Red（先证伪）：`test_subprocess_runner_enforces_capture_cap_before_process_exit` 在旧实现下
  以 `TimeoutExpired(10s)` 失败（缓冲 200 KiB 后只能靠 timeout 兜底），复现 audit。
- 最小 fail-closed 修复：Popen + select 有界排空（每次 `os.read` 只取剩余 cap 额度）；
  cap 到达且进程仍在或 deadline 超时 → 复用 `agent.process.group` 共享 seam
  TERM→KILL→reap 确认；清理无法确认抛 `ProcessCleanupError`（probe 映射
  `docker_daemon_unavailable`，不 propagate）；超 cap 的 returncode 为负 → probe fail
  closed。argument-vector-only（`shell=False`，无 host fallback）由
  `test_subprocess_runner_is_argument_vector_only`（argv 单项含空格/分号）验证。
- 另新增 `test_subprocess_runner_deadline_kills_and_fails_closed`（timeout → reaped +
  TimeoutExpired）。
- Focused gate（只重跑 Task 1 范围）：`pytest
  tests/sandbox/test_backend_qualification.py` → **14 passed**（含 cap 测试 1.6s 完成，
  不再等 10s）；`ruff check agent/sandbox/ tests/sandbox/` → clean（test_contracts.py 的
  import 排序随 --fix 修正，属 Task 2 文件）；`git diff --check` → clean。
- E3 U0 qualification checkbox 已同步勾选（本机 daemon 未运行事实不变）。
- 继续next_task=2

### Task 1 补丁 2 — descendant 泄漏（Codex 追加审计 + 裁决，2026-08-26）

- Audit reducer：leader（start_new_session）spawn 同 PGID、继承 stdout 的 descendant 后立即
  退出（rc=0）；descendant 延迟写满 cap。共享核心 `agent/sandbox/bounded_exec.py` 旧逻辑在
  cap 达到且 leader 已退出时（`proc.poll() is None` 为假）跳过 terminate_group → 返回
  rc=0 且 descendant 仍处运行态。
- Red（`tests/sandbox/test_bounded_exec.py::test_cap_hit_with_same_pgid_descendant_terminates_whole_group`）：
  先以 pidfile 前置证明 descendant PID 存活且 `getpgid(child)==leader_pid`，再断言 runner
  返回后 descendant 不得运行态幸存。旧实现精确复现泄漏。
- 最小 Green（不改 `agent/process/group.py` 语义）：
  1) EOF 与 cap 截断后都先给 leader 短 grace `proc.wait`（reap-first，消除 zombie 成员
     导致的 killpg EPERM 误判）；
  2) `capped or timed_out or poll None or group_alive(pgid)` 任一为真 → 无条件
     `terminate_group`（TERM→KILL→reap→confirm whole group），无法确认时抛
     ProcessCleanupError fail-closed；只有干净 EOF + leader 已退 + group 确认消失才免杀。
- 裁决版测试语义：正常返回 → descendant 必须 ESRCH；若抛 ProcessCleanupError → 仅接受
  `__cause__` 为 errno.EPERM 的 PermissionError、message 为 closed
  `cannot determine process group liveness` form，且 `ps -o stat=` 证明 descendant 非
  运行态（gone 或 Z）。try/finally 对已知 PGID 精确 TERM→KILL 清理，不泄漏 60s 子进程。
- 另有 mock group seam 的确定性 success path（`test_cap_hit_always_invokes_confirmed_group_cleanup`）：
  注入替身证明 cap-hit 无论 leader poll 状态都进入 confirmed cleanup 并正常返回；
  `test_normal_eof_without_descendants_keeps_clean_exit` 证明干净 EOF 不误杀。
- qualification runner 重构为委托共享 `run_bounded_argv`（消灭双实现漂移）。
- Focused gate（未管道直跑）：`.venv/bin/python -m pytest -q
  tests/sandbox/test_bounded_exec.py tests/sandbox/test_backend_qualification.py -rx` →
  **17 passed，EXIT_CODE=0**；touched Ruff（Task 1 相关文件）clean；
  `git diff --check` → EXIT_CODE=0。
- 注：本机 macOS sandbox 下 killpg 从 worker 线程可能 EPERM——按裁决接受 fail-closed 分支
  （测试以 ps 证明 descendant 非运行态），不放宽 group primitive。

### Task 4 — Docker lifecycle（corrected：multi-command lease，2026-08-26）

按主审裁决实现（见文首 design correction）；`sleep infinity`+`docker exec` 的旧 Task 4
plan 序列作废，`wait/logs` 不在 lifecycle（fake 直接 AssertionError 拒绝假路径）。

**簇 B（store fail-closed）** Red→Green：
- `begin` 不覆盖既有 deterministic record（含损坏文件）→ `StoreConflictError`；provision
  将其映射为 `SandboxOutcomeUnknownError`（恢复必须 close/reuse，不得重复 create）。
- strict decoder：unknown keys / partial identity / malformed transitions /
  non-hex container_id / 非 str network_names / unknown phase 全部 → None（不可信记录，
  恢复只能走 read-back）。
- `SandboxRecordV1` 新增 durable `execution_count` + `last_execution_digests`；
  `record_execution` 仅允许 RUNNING/RESULT_OBSERVED。
- Gate：`.venv/bin/python -m pytest -q tests/sandbox/test_sandbox_store.py -rx` →
  **10 passed，exit 0**；ruff/diff-check clean。

**簇 A（adapter）** Red→Green（`agent/sandbox/docker.py` 重写）：
- provision 一次 `create --network none --cap-drop ALL --security-opt
  no-new-privileges --pids-limit/--memory/--memory-swap/--cpus + labels + sleep infinity` →
  cp-in → start；无 `--volume/-v/--mount`；request label 用 sha256(request)[:16] 稳定摘要
  （原文不进 argv，已测）；store 在首个 Docker effect 前落 PREPARING。
- create/cp/start 超时或 rc!=0 → **labelled read-back 分类**：`docker ps -a --filter
  label=agent.sandbox.environment=<id>` 证明 absent → `SandboxProvisionError`（安全失败）；
  存在或 read-back 失败 → `SandboxOutcomeUnknownError`。
- execute：budget 检查（durable `execution_count >= max_command_count` →
  `KnownNotExecuted("command_budget_exhausted")`）→ bounded `docker exec --workdir …`
  exact argv → 分类：126/127 → `KnownNotExecuted("command_unavailable")`；125 → UNKNOWN；
  ≥128 → SIGNALED；TimeoutExpired → kill + `inspect {{.State.Running}}` verify →
  TIMED_OUT_KILLED 或 UNKNOWN。
- 同一 lease 多条命令（多次 exec）合同已测；environment_id 对 (request, spec)
  deterministic。

**簇 C（capture/close）**：
- capture：producing receipts 取自 store durable `last_execution_digests`（新 adapter
  实例/重启后仍可 capture，已测）；copy-out 到 fresh empty `mkdtemp` attempt 目录
  （连续两次 capture 产生两个独立目录、bundle digest 不变——无 stale 污染）；handle
  container_id/spec_digest 与 ledger 漂移 → fail closed。
- close：container_id 已知 → `rm -f` + inspect absence 验证；PREPARING+
  container_id=None → **必须 labelled read-back**（空 → CLEANED；发现 leaked id → 只
  rm 该精确 id + verify；read-back 失败 → CLEANUP_UNKNOWN）；无 broad cleanup；
  CLEANUP_UNKNOWN 禁止 execute reuse；CLEANED 幂等 CONFIRMED。

**边界闭合**：combined/disk caps ownership 已写入 `SandboxResourceLimitsV1` docstring 与
design correction（Task 6/7 governance 拥有，adapter 不假装实施）；production runner 委托
共享 `run_bounded_argv`（descendant 修复同一代码路径）；`agent/process/group.py` 未改动。

**Focused gate**（Task 4 收口，未管道直跑）：
`.venv/bin/python -m pytest -q tests/sandbox/ -rx` → **105 passed，PYTEST_EXIT=0**；
`.venv/bin/ruff check agent/sandbox/ tests/sandbox/` → **RUFF_EXIT=0**；
`git diff --check` → **DIFF_EXIT=0**。
- next_task=5

### Task 4 第二轮闭合 — 主审 6 项硬闭合（2026-08-26）

逐项 Red→Green（每项只跑对应定向测试，最后跑 Task 4 focused gate）：

1. **execute spec 漂移拒绝**：`command.spec.spec_digest != record.spec_digest` →
   `SandboxOutcomeUnknownError`，不发 exec（堵住新 spec 绕过预算/资源/网络身份）。
   Red→Green：`test_execute_rejects_command_spec_drift_against_lease`。
2. **store TOCTOU/原子性**：新增 `_with_ledger_lock`（owner-only `<env>.lock` 文件 +
   `fcntl.flock LOCK_EX`，参照 checkpoint 模式）保护 begin/CAS/record_execution 的
   read-modify-write；`_write_record` replace 失败清 temp；`record_execution` 入参
   digest 预校验（hex64，ValueError）；decoder 只允许 `last_execution_digests` 为空或
   恰 2 个 hex64、且末 transition phase 必须等于 record.phase。Red→Green 6 个新测试
   （含 4 线程 ×10 次 RMW 无丢失 = count 40）。
3. **exec 输出 cap 截断**：`stdout/stderr_truncated` 时 local CLI 已被杀、remote 可能
   仍在运行——统一走 `_kill_and_bounded_record`（kill + `inspect
   {{.State.Running}}`==false 验证 → TIMED_OUT_KILLED，保留截断前 bounded 输出）或
   UNKNOWN。Red→Green：cap 截断两测试。
4. **receipt lineage（修订版）**：capture 的 producing receipts 改为 **kw-only 必填
   `producing_receipt_digests` typed seam**——Runtime-owned governed caller 从 durable
   current execution receipt store 重读后显式传入；adapter 只验证 non-empty/exact
   hex64 并消费，不查询 Runtime（否决了 provider callback 方案：违反 design §2 port
   纯度）、不接受模型字段、不 fallback draft/command digest。未传 → TypeError；空/
   malformed → ValueError；无 prior observed execution → UNKNOWN；restart 场景由
   caller 重读后显式传入。ports.py/design 文档同步 correction。
5. **close 双 label 精确绑定**：rm 之前必须 `docker ps -a --filter
   label=agent.sandbox.environment=<id> --filter label=agent.sandbox.request=<digest>`
   双 label read-back——0 → absent；1 且与 ledger container_id 一致（或 ledger 无 id
   且恰 1 个）→ exact cleanup；>1 / 漂移 / read-back 失败 → UNKNOWN，禁止误删。fake
   改为从 create argv 真实提取 labels 并按 filter 全匹配。
6. **文字直接替换**：E3 U1 lifecycle 行与 Task 4 plan Step 1/2 的 wait/logs/
   start-before-wait 旧文字已替换为 corrected lifecycle 正文（不再只靠顶部 override）。

**Task 4 focused gate**（最终，未管道；排除 Task 5 in-progress 的
`test_egress_proxy.py`）：
`.venv/bin/python -m pytest -q tests/sandbox/{test_backend_qualification,
test_bounded_exec,test_contracts,test_snapshot,test_change_bundle,
test_sandbox_store,test_docker_adapter,test_docker_cleanup}.py -rx` →
**119 passed，PYTEST_EXIT=0**；touched `ruff check` → **RUFF_EXIT=0**；
`git diff --check` → **DIFF_EXIT=0**。

### Task 5 — Closed egress proxy + governed network 装配（2026-08-26）

**egress 层（`agent/sandbox/egress_proxy.py`，hermetic 单文件，17 tests）**：
- `admit_connect_target`：closed admission（OFF/policy_off、raw IP、非 443、
  domain 不在 policy（无 wildcard 后缀）、DNS 任一非 public IP（含 IPv6
  site-local `fec0::1`——`getattr(address, "is_site_local", False)`，裁决 B）、
  resolver 故障/空答案 → resolution_failed）。
- `parse_connect_request`：bounded header（8 KiB cap）、non-CONNECT 拒绝。
- `ConnectProxy`：单次 resolve+validate + 同批次 dial（裁决 C，resolver count=1
  已测）；dial 后 audit/send 失败 → fail-closed 断开且 target socket 必被
  close（裁决 D，socketpair EOF 已测）；audit sink 异常不杀代理线程。
- **hermetic helper 入口**（主审裁决）：单文件零本仓库 import；`--policy-file`
  bounded canonical JSON（closed keys）+ `--audit-file` payload-free JSONL ring
  （1024 行上限）；绑定后 `READY <port>` 行；SIGTERM 优雅退出；usage error 不回显
  argv。隔离 subprocess 测试（PYTHONPATH 置空、独立 cwd）证明不依赖 host repo。
- proxy 层 socket 测试经 127.0.0.1 ephemeral port + socketpair 替身 dialer，
  不发起真实外部连接。

**docker 装配层（`agent/sandbox/docker.py` + `tests/sandbox/
test_docker_network_policy.py`，7 tests）**：
- governed（PACKAGE_REGISTRY/EXACT_ALLOWLIST）：缺 proxy image/module → 首个
  Docker effect 前 `SandboxProvisionError`；OFF 仍 `--network none` 无 proxy。
- **资源身份先于资源创建落 ledger**（裁决 1）：`record_planned_networks`（网络名，
  PREPARING-only）与 `record_proxy_container`（proxy id，hex 预校验）在任何
  对应 effect 前写入；CAS/record_execution 保留该字段。partial-failure 测试：
  run 失败 → UNKNOWN 且 ledger 有完整网络名，recovery 可精确清理。
- **网络带 exact ownership labels**（裁决 2）：两个 network create 均带
  `--label agent.sandbox.environment/request/role=network-internal|network-egress`；
  close 用 `docker network ls --filter label=…` read-back 绑定 **id**（非可替换
  名字）后 rm 并二次 read-back 空。
- **role-specific close**（裁决 3）：target/proxy 分别按 (env, request, role)
  三 label read-back；rm 后二次 read-back 必须为空（replacement-after-rm race
  测试：同 label 新 id 出现 → CLEANUP_UNKNOWN，不误删不假 CLEANED）。
- proxy helper 以 wait-and-exec 脚本为容器主进程（`sh -c 'while [ ! -f … ];
  done; exec python /opt/egress_policy.py --policy-file …'`）；模块与 policy
  config 经 `docker cp` 进入（不挂 host source/socket）；launch 后
  `inspect {{.State.Running}}` 为真 helper-running read-back。target 只接
  `--internal` 网络 + 仅 `HTTPS_PROXY/HTTP_PROXY=http://<proxy>:3128`（直连
  egress 不可能——bridge 只挂 proxy）。
- policy config 由 `_egress_policy_config(NetworkPolicyV1)` 生成 canonical JSON
  （registry preset 来自冻结 REGISTRY_PRESETS；无 credential/raw host path）。

**Focused gate**（未管道真实 exit code）：
`.venv/bin/python -m pytest -q tests/sandbox/ -rx` → **145 passed，PYTEST=0**；
`.venv/bin/ruff check agent/sandbox/ tests/sandbox/` → **RUFF=0**；
`git diff --check` → **DIFF=0**。
- next_task=6

### Task 6 开工记录（2026-08-26）

研读既有 local_process 治理模式（`agent/runtime/contracts.py` L1528-1763+）：
- `ProcessAuthorityCandidateV1.create`：closed typed 投影 + `canonical_json_digest`
  绑定全部 identity（goal/revision/workspace/command fingerprint/executable/argv/
  cwd/profile/environment policy/authority/trust notice/max_uses=8/expiry=60 固定值）；
  `__post_init__` 校验 digest 一致性。
- `ProcessAuthorityLeaseV1`：ResolveApproval 铸造、exact binding、uses_consumed、
  expires_at；Goal revision/terminal transition 失效。
- durable members：`ApprovalRequest.process_authority_candidate`、
  `ConversationState.process_leases`、`LoadedSnapshot.process_leases`、
  `ExecutionIntent.process_lease`；checkpoint strict round-trip。
- `ExecutionAuthorityClass`（L176）与 `EgressClass`（L171）需新增
  `ISOLATED_SANDBOX` / `GOVERNED_NETWORK`。

Task 6 计划（Red→Green，对齐上述模式）：
1. `tests/sandbox/test_authority.py`：approval 绑定全 identity；revision/correction/
   cancel/environment drift 清 lease；模型字段不能铸造/扩张；GOVERNED_NETWORK 需
   HIGH+EXTERNAL+ALWAYS 除非 exact active sandbox lease 匹配。
2. `tests/continuity/test_sandbox_checkpoint.py`：sandbox durable members strict
   round-trip；partial/unknown/forged 拒绝；credential/raw path 不进序列化 JSON。
3. `tests/sandbox/test_tools.py`：`sandbox_exec`/`sandbox_capture_changes` 注册、
   matched lease 跳过重复低风险审批、policy 扩张恒 ApprovalRequired、
   capture 显式传入已铸造 receipt digest（Task 4 第二轮 seam 的 Runtime 侧）。
4. 实现：`agent/runtime/contracts.py`（SandboxAuthorityCandidateV1/LeaseV1/
   SandboxReceiptV1 + 两个 enum 成员 + durable members）、`checkpoint.py` strict
   codec、`agent/sandbox/tools.py`（matching/registration）、`state.py`（lease
   失效）、`tools.py`（invoke gate：EXECUTING 持久化后才调 port）。

### Task 6 进度 1 — authority + checkpoint（2026-08-26）

- **Red→Green**：`tests/sandbox/test_authority.py`（11 tests）。
- 实现位置修正：durable 三类型（`SandboxAuthorityCandidateV1`/
  `SandboxAuthorityLeaseV1`/`SandboxReceiptV1`）定义在
  **`agent/runtime/contracts.py`**（Process 类型之后；checkpoint durable members
  需要 round-trip，依赖方向必须 sandbox→runtime）——`agent/sandbox/authority.py`
  改为单一 re-export（同 process 包 re-export 模式）。冻结值：
  `SANDBOX_MAX_USES=64`、`SANDBOX_EXPIRY_MINUTES=120`；receipt outcome closed
  {exited, signaled, timed_out_killed}（known-not-executed 不铸造 receipt）。
- enum 扩展（最小增量）：`ExecutionAuthorityClass.ISOLATED_SANDBOX`、
  `EgressClass.GOVERNED_NETWORK`（docstring 注明 017 语义）。
- durable members：`ApprovalRequest.sandbox_authority_candidate`、
  `ConversationState.sandbox_leases`、`LoadedSnapshot.sandbox_leases`（两处
  process_leases 旁）、`ExecutionIntent.sandbox_lease`。
- **Red→Green**：`tests/continuity/test_sandbox_checkpoint.py`（7 tests）。
  `_state_to_dict`/`_state_from_dict` 增加 sandbox_leases 编解码（新 encode 必备
  → SCHEMA_VERSION；旧版本缺失按空迁移）；`_sandbox_lease_to_dict/_from_dict`
  strict（closed keys；携带 digest 直接构造，`__post_init__` 重算比对——伪造/
  篡改/类型错误 → CheckpointError）；`_encode_state` version 判定包含
  sandbox_leases。credential/raw host path 不进序列化（已测）。
- Gate（未管道）：`pytest tests/continuity/ → 248 passed，EXIT=0`（既有
  checkpoint 语义零破坏）；`pytest tests/sandbox/test_authority.py
  tests/continuity/test_sandbox_checkpoint.py → 18 passed`。
- 剩余簇：`agent/sandbox/tools.py` 注册/matching + `tests/sandbox/test_tools.py`
  （lease 跳过重复审批、policy 扩张 ApprovalRequired、GOVERNED_NETWORK HIGH+
  EXTERNAL+ALWAYS、capture 显式 receipt 注入）+ `state.py` revision/terminal
  清 lease + `tools.py` EXECUTING-gate。

### Task 6 进度 2 — tools prepare 治理（2026-08-26）

- **Red→Green**：`tests/sandbox/test_tools.py`（13 tests）。
- `agent/sandbox/tools.py`：`build_sandbox_tool_registrations(environment_factory)`
  → sandbox_exec（HIGH/EXTERNAL/ALWAYS/ISOLATED_SANDBOX/egress 投影
  GOVERNED_NETWORK 最严情况）+ sandbox_capture_changes（MEDIUM/READ_ONLY/
  ISOLATED_SANDBOX）；`prepare_binding=_sandbox_authority_binding`（arguments →
  closed digest binding；模型提供的 spec_digest/lease 字段被忽略——白名单参数
  仅 executable/argv/cwd/network_mode/ecosystem/domains）；
  `configure_frozen_digests`（composition 启动期注入冻结 image/snapshot digest）；
  `build_sandbox_spec` helper。
- `agent/runtime/tools.py`：ISOLATED_SANDBOX prepare 分支（无 goal →
  `sandbox_requires_goal` error；`_build_sandbox_candidate(binding, context)`；
  REQUIRE_APPROVAL 时 `_match_sandbox_lease`——zoned RFC3339 数值时效 + 全
  binding identity exact（goal/revision/workspace/image/snapshot/spec）+ 预算；
  匹配 → ALLOW + `intent.sandbox_lease`）；ApprovalRequired 分支
  `request.sandbox_authority_candidate` 携带 durable candidate（对齐 F1 语义：
  authority 只能来自 ResolveApproval 铸造的 lease）。
- 语义澄清（测试固化）：**multi-command lease**——command 不进 spec，同一 lease
  下不同 argv 允许（主审裁决）；spec 任一成员（image/snapshot/network/limits/ttl）
  漂移或 network policy 扩张（OFF→PACKAGE_REGISTRY）→ 恒 ApprovalRequired；
  revision 漂移/过期 lease 不匹配。
- 既有测试合法扩展：`tests/kernel/test_contracts.py` closed
  ExecutionAuthorityClass 断言 + `isolated_sandbox`（017 合法扩展）。
- **Focused gate**（未管道）：`pytest tests/sandbox/ tests/continuity/ tests/kernel/
  → 627 passed，PYTEST=0`；ruff --fix 后 clean；`git diff --check` → 0。

**Task 6B 剩余（下一步继续点）**：
1. invoke gate：`KernelToolRuntime.invoke` 的 ISOLATED_SANDBOX 分支——
   `_sandbox_outcome`（SandboxExecutionDraftV1/KnownNotExecuted → ToolResult，
   对齐 `_process_outcome`/`_validate_process_draft`）+ `_mint_sandbox_receipt`
   （SandboxReceiptV1；closed outcome；uses_consumed++ 经 state）+ environment
   factory 接线（EXECUTING 持久化后才调 port——由 loop 侧顺序保证，测试对齐
   process invoke 的 EXECUTING gate 用例）。
2. `agent/runtime/state.py`：Goal revision/terminal transition 清 sandbox_leases
   （对齐 process_leases 的失效位置）+ 测试。
3. capture_changes 的 governed caller：从 durable sandbox receipt store 重读
   receipt digest 后显式传入（`producing_receipt_digests` seam 的 Runtime 侧）。

### Task 6B — invoke gate + receipt 铸造 + lease 失效（2026-08-26，完成）

- **Red→Green**：`tests/sandbox/test_tools.py` 追加 5 tests（共 18）。
- `agent/runtime/tools.py`：
  - invoke 顶部 + callable 前双重 gate（F1 对齐）：ISOLATED_SANDBOX intent 无
    `sandbox_lease` → `IntentConflictError`；lease 过期/超预算（zoned RFC3339 数值
    比较 + uses_consumed<max_uses）→ `IntentConflictError`。
  - `_sandbox_outcome`：draft 的 `command_identity_digest` 必须与已批准 intent 的
    binding 一致（漂移 → `sandbox_draft_identity_mismatch`，不铸 receipt）；验证
    通过后铸造 `SandboxReceiptV1`（closed outcome；绑定 lease id/digest +
    environment/request/command/draft identity），digest 进 `metadata
    ["sandbox_receipt_digest"]`——这是 capture producing receipts 的唯一来源
    （Task 4 第二轮 typed seam 的 Runtime 侧完成）。KnownNotExecuted 走既有
    executed=False 分支，不铸造 receipt。
- `agent/runtime/state.py`：
  - `_mint_sandbox_authority_lease`（ResolveApproval(approved=True) 对 sandbox
    candidate 铸造；时效锚定批准时刻，zoned RFC3339 fail-closed；expiry=
    SANDBOX_EXPIRY_MINUTES）。
  - lease 失效（对齐 process_leases 同位四处）：goal 修正/暂停/cancel/
    VERIFIED_DONE 全部清空 `sandbox_leases`。
- **Focused gate**（未管道）：`pytest tests/sandbox/ tests/continuity/ tests/kernel/
  tests/process/ → 719 passed，PYTEST=0`；`ruff check` → RUFF=0；
  `git diff --check` → DIFF=0。
- 遗留（记入 Task 7/8）：`environment_factory` 的真实 invoke 接线（session 复用
  handle）与 `state.sandbox_receipts` durable 持久化（evidence 闭包需要）归
  composition/evidence 任务；SandboxReceipt digest 已在 ToolResult metadata 流动。

### Task 6 收口

Task 6 全部完成（6A prepare 治理 + 6B invoke gate/receipt/失效）。累计 017 新增
测试：authority 11 + checkpoint 7 + tools 18 = 36（另有 kernel closed-enum 合法
扩展 1 处）。`AgentRuntime.run_turn`/`ContextManager`/`KernelToolRuntime` 唯一
owner 未漂移（全部扩展对齐既有 process 治理模式）。
- next_task=7（ChangeBundle host apply + evidence closure：`sandbox_apply_bundle`
  WRITE 注册、`SandboxBundleReceiptV1` + `sandbox_bundle_v1` evidence predicate、
  journaled apply、`tests/sandbox/test_bundle_apply.py` +
  `tests/continuity/test_sandbox_verified_done.py`）









### Task 2 — Sandbox 域合同与 port（2026-08-26）

- Red：`tests/sandbox/test_contracts.py`（27 tests）先因
  `ModuleNotFoundError: agent.sandbox.contracts` 失败，符合预期。
- Green：`agent/sandbox/contracts.py`（`NetworkMode` closed union、`RegistryEcosystem`
  {python,node}、`NetworkPolicyV1.off/package_registry/exact_allowlist`、
  `SandboxResourceLimitsV1.standard()`、`SandboxSpecV1`、`SandboxCommandV1`、
  `SandboxHandleV1`、`SandboxDraftOutcome`、`SandboxExecutionDraftV1`、
  `SandboxCleanupStatus/ReceiptV1`、`ChangeKind/ChangeEntryV1/ChangeBundleV1`）+
  `agent/sandbox/ports.py`（`SandboxEnvironment.provision/execute/capture_changes/close`
  Protocol，无 factory/registry）。
- 合同要点：全部 frozen dataclass + `canonical_json_digest`（constructor 顺序稳定，已测）；
  image digest `sha256:<64hex>`、其余 bare 64-hex；bool-as-int 全字段拒绝；domain 校验
  拒 raw IP/localhost/wildcard/scheme/port/内网形态/数字 TLD；port 只允许 443；重复
  domain/重复 path 拒绝；DELETED 不带 digest、ADDED/MODIFIED 必带；CONFIRMED cleanup
  必须 container_absent；EXITED 必带 exit_code、SIGNALED 必带 signal、
  TIMED_OUT_KILLED 允许未知；bundle 必须引用 ≥1 producing receipt digest；
  `KnownNotExecuted` 自 `agent.runtime.contracts` re-export（与 process 包同模式）。
- Focused gate：`pytest tests/sandbox/test_contracts.py
  tests/sandbox/test_backend_qualification.py` → **41 passed**；
  `ruff check agent/sandbox/ tests/sandbox/` → clean；`git diff --check` → clean。
- next_task=3

### Task 3 — no-follow snapshot 与 ChangeBundle（2026-08-26）

- Red：`tests/sandbox/test_snapshot.py`（14）+ `tests/sandbox/test_change_bundle.py`（10）先因
  `ModuleNotFoundError: agent.sandbox.snapshot` 失败，符合预期。
- Green：`agent/sandbox/snapshot.py`。要点：
  - `SnapshotPolicyV1`（closed 上限 + 冻结顶层排除 `tui/.venv/*_cache/build/dist` +
    state roots；名称级拒绝先于 stat/open，sensitive 分类与 path_safety 同源冻结）。
  - `create_workspace_snapshot`：descriptor-relative copy-in（`O_NOFOLLOW`+dir_fd、
    root identity pinning、目录 (dev,ino) drift 检测、regular+nlink==1 才复制、
    边复制边 hash、复制后 re-stat 源 fd、失败只删本次 mkdtemp staging）。
    closed reason codes：workspace/staging_root_invalid、file_count/total_bytes/
    single_file_bytes/depth/deadline_exceeded、directory_identity_drift、
    file_identity_drift、source_mutated_during_copy。
  - `build_change_bundle`：digest-only walk（不复制）→ ADDED/MODIFIED/DELETED 分类 →
    content-addressed blob（0o444，bundle-owned storage）；bundle 无绝对 host 路径。
  - `verify_bundle_against_workspace`：closed 三态 CLEAN/BASE_DRIFT/BUNDLE_CORRUPT
    （重算 bundle_digest 的 forgery oracle + 可选 blob 存在性 + 当前 workspace digest
    对比），无任何 apply 语义。
  - `compute_workspace_digest` 与 snapshot_digest 同一算法（verify 与 snapshot 一致性）。
- mutation oracle 全 Green：symlink escape（不跟随不复制）、hardlink（两个名字都排除，
  与 WorkspaceBoundary multi-link 拒绝一致）、fifo 排除、`.env`/`id_rsa`/`.key`/
  `credentials.json`/`.git`/`.ssh`/`tui/`/state roots 不进 manifest 与 staging、
  file/bytes/depth 超限 fail closed 且只删本次 staging（哨兵兄弟目录存活）、
  rename+mkdir 目录替换 → identity_drift、复制期 size 漂移 →
  source_mutated_during_copy、entries 超限（deleted 放大 union）、result symlink 不进
  blob、tampered entries/forged digest/missing blob → BUNDLE_CORRUPT。
- Focused gate：`pytest tests/sandbox/` → **65 passed**；`ruff check agent/sandbox/
  tests/sandbox/` → clean；`git diff --check` → clean。
- next_task=4

### Task 7 — ChangeBundle host apply + evidence closure（2026-08-27）

- **Red**：`tests/sandbox/test_bundle_apply.py`（14）+
  `tests/continuity/test_sandbox_verified_done.py`（5）先因
  `ImportError: SandboxBundleReceiptV1` 失败，符合预期。
- **Green 实现**：
  - `agent/runtime/contracts.py`：`SandboxBundleReceiptV1`（绑定 Goal/revision、
    bundle/environment identity；outcome closed {applied, captured}；
    `paths_digest` 摘要 metadata 携带的 per-path outcomes；strict
    `from_json`/`to_json` + digest 重算）。
  - `agent/sandbox/contracts.py`：`ApplyOutcome`/`AppliedPathV1`/
    `ApplyResultV1`（REJECTED 必须携带 closed reason；APPLIED 至少一条 path）。
  - `agent/sandbox/apply.py`：`apply_change_bundle` 验证顺序冻结——
    journal_pending → empty → entries/bytes/single 超限 → denied_path（名称级
    先于任何 stat/open）→ symlink_swap（per-path lstat 含父组件）→
    blob_missing/blob_corrupt → base_drift（整树 manifest digest）→
    unapproved_deletion；**全部先于首个 host write**（known-not-executed）。
    owner-only journal（0o600 temp+replace，含 validation 期 base per-path
    digests）先于任何写入落盘；写入走 no-follow 目录链 + O_EXCL temp +
    `_os_replace` 原子替换 + fsync；DELETED 走 dir_fd unlink；中途 OSError →
    `ApplyOutcomeUnknownError`（journal 保留，恢复不得盲重放）；成功后清理
    journal（重复 apply 由 base drift 拒绝）。`inspect_apply_state`：journal +
    host digests → APPLIED/NOT_APPLIED/AMBIGUOUS 三态精确分类；无 journal ⇒
    零写入已发生。
  - `agent/sandbox/tools.py`：`build_sandbox_apply_registration`（HIGH/WRITE/
    ALWAYS、execution authority IN_PROCESS——host merge 是独立 governed
    effect，不消费 sandbox lease）；exact path/digest preview（每类 8 路径
    有界 + 未批准删除显式标注）；strict bundle 解析（forged bundle_digest
    拒绝）；composition 不注入 workspace/blob/journal 即不注册。
  - `agent/runtime/tools.py`：prepare 增加 `sandbox_apply_requires_goal`
    gate（receipt 必须绑定 durable Goal）；invoke 分发 `ApplyResultV1` →
    `_sandbox_bundle_outcome`（REJECTED → known-not-executed；APPLIED →
    Runtime 铸造 `SandboxBundleReceiptV1`，metadata 携带 canonical receipt +
    flat 投影 + bounded paths）。
  - `agent/runtime/evidence.py`：`_tool_receipt` 新增 `sandbox_bundle_v1`
    分支（closed keys：receipt_digest/bundle_digest 必填 hex64；outcome 与
    artifact_path+artifact_digest 成对可选；canonical receipt digest 重算 +
    flat 投影双核对 + 当前 Goal/revision 绑定 + artifact 绑定逐项比对
    metadata `sandbox_bundle_paths`）；`_GAP_REPAIRS` 新增
    "no exact sandbox bundle receipt proves the criterion" →
    (sandbox_capture_changes, sandbox_apply_bundle)。
- **完成语义（测试固化）**：sandbox exit 0 单独不满足 host artifact Goal；
  `VERIFIED_DONE` = applied bundle receipt criterion + filesystem read-back
  criterion 两条同时成立，或显式 sandbox-artifact-only criterion（captured
  receipt + artifact path/digest 绑定，无需 host read-back）；伪造 receipt
    （flat 投影不一致/别的 Goal/旧 revision）fail closed。
- **阶段内闭合（Task 6 遗留——其 focused gate 未跑 architecture 套件）**：
  `tests/architecture/test_cutover_absence.py` expected 集加入 `agent/sandbox`
  全部 12 文件与 `agent.sandbox` 包；checkpoint CAS owners 显式扩展
  `agent/sandbox/docker.py`（SandboxStore 是 design §3 冻结的独立状态面，
  conversation checkpoint owner 仍唯一 `loop.py`）；
  `test_014` EgressClass +`governed_network`、`test_015`
  ExecutionAuthorityClass +`isolated_sandbox`（017 合法扩展注释）。
- **设计记录（对 plan 文件清单的最小偏离）**：`state.py`/`checkpoint.py` 未改
  ——apply/bundle receipts 经 durable ToolResult facts 流动（与 process
  receipts 同模式），无需新增 ConversationState durable member；Task 6B 记录
  的「state.sandbox_receipts 持久化」由 checkpointed facts 承担，避免状态面
  双写漂移。
- **Focused gate**（未管道直跑，覆盖 touched 面 sandbox/continuity/kernel/
  process/architecture/scheduler/subagent/cli）：
  `.venv/bin/python -m pytest -q -rx …` → **935 passed，PYTEST_EXIT=0**；
  `.venv/bin/ruff check agent/ tests/` → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。
- graphify update 按 AGENTS.md 安全跳过（无法确认不摄入 untracked `tui/`
  等私有输入）；graph 落后于新增 sandbox 模块，本次以直接读取源文件补偿。
- next_task=8（Static composition + everyday UX：composition/main/pyproject
  静态接线、Docker adapter 缺席即不注册、CLI 单动作解释、
  `tests/sandbox/test_composition.py` + `tests/cli/test_017_sandbox_experience.py`
  + `tests/architecture/test_017_sandbox_boundary.py`）

### Task 8 — Static composition + everyday UX（2026-08-27）

- **Red**：三个新测试文件先因 `ImportError: SandboxReadiness`（composition）
  与 `agent/sandbox/profile.py` 缺失失败，符合预期。
- **Green 实现**：
  - `agent/sandbox/profile.py`：`SandboxProfileV1`（docker_binary/context +
    固定 image digest，全非秘密）+ owner-only 0o600 原子存取 +
    profile_digest 自校验（篡改 → `SandboxProfileError` fail closed）。
  - `agent/composition.py`：`SandboxReadiness`（NOT_ENABLED/
    TEMPORARILY_UNAVAILABLE/READY）+ `SandboxResources` +
    `build_sandbox_resources`——未配置不注册；已配置先做两次只读
    qualification probe（`version`/`info`），不 qualified → closed
    reason_code + 零 environment/snapshot/registration（无 local-process
    fallback）；qualified → 一次 workspace snapshot + 冻结 digest 注入 +
    per-lease environment factory（同一 approved_request_identity 复用一个
    DockerSandboxEnvironment）+ 三个 registration + 单一逆序 closeable
    （environments 逆序 close）。snapshot 失败 → ValueError fail closed。
  - `agent/sandbox/tools.py`：`SandboxReceiptBook`（Runtime 铸造 → capture
    消费的 session 内 producing-receipt seam；每 environment 有界
    SANDBOX_MAX_USES 条）；`_command_from_arguments`（binding 与 invoke 同一
    构造）；**真实 invoke 接线**——exec 按 lease.approved_request_identity
    做 session handle cache（multi-command lease：provision 一次、每命令一次
    execute；session 上限 8 个 environment，spec 漂移/超限 known-not-executed）；
    capture 无 prior 执行/无已观测 receipt known-not-executed（restart 后
    book 为空即 fail closed，不重放）；capture 获得
    `_sandbox_capture_binding`（与 exec 同一 environment spec 身份——匹配
    lease 即免重复审批）；exec preview 渲染 image/network/命令（无内部
    ID/绝对根）。
  - `agent/runtime/tools.py`：`KernelToolRuntime(sandbox_receipt_book=…)`；
    `_sandbox_outcome` 铸造后记录 book；`ChangeBundleV1` dispatch →
    `_sandbox_capture_outcome`（铸造 outcome=captured 的
    `SandboxBundleReceiptV1`，content/metadata 携带 bounded canonical bundle
    manifest——模型原样传给 `sandbox_apply_bundle`）。
  - `agent/continuity/restart.py`：`sandbox_recovery_kind`（closed 三值：
    execution_unknown=EXECUTING+ISOLATED_SANDBOX executing record；
    bundle_review=pending sandbox_apply_bundle approval；base_drift=最后
    apply REJECTED code）+ `RestartProjection.sandbox_recovery`。cleanup_
    unknown 发生在 teardown close receipt，不进 conversation state——v1
    restart 投影不可见（诚实记录，不伪造检测）。
  - `main.py`：`setup-sandbox` 子命令（guided/flags，只存非秘密）；
    startup 三态行（not enabled → 一条动作 `first-agent setup-sandbox`；
    unavailable → reason + 「start Docker and rerun」，无 traceback）；
    READY 时 capabilities 行追加 ", sandboxed execution"；restart 投影的
    sandbox 恢复提示（closed 三值文案）。
- **pyproject.toml 未改**（偏离 plan 文件清单，原因：sandbox 依赖的是外部
  Docker Engine CLI 而非 pip 依赖；`packages.find` 的 `agent.*` 已自动包含
  `agent.sandbox`；空 optional-dependencies extra 无意义）。
- **测试侧修复**：`build_sandbox_resources` 会按真实 snapshot 覆写冻结
  digest——test_composition/test_tools 增加 autouse 复位 fixture 消除同
  会话顺序污染；test_tools 的 preview 断言更新为 Task 8 渲染（017 合法
  扩展：image/network 进 preview）。
- **Focused gate**（未管道直跑）：
  `.venv/bin/python -m pytest -q -rx tests/sandbox/ tests/continuity/
  tests/kernel/ tests/process/ tests/architecture/ tests/scheduler/
  tests/subagent/ tests/cli/` → **960 passed，PYTEST_EXIT=0**；
  `.venv/bin/ruff check agent/ main.py tests/` → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。
- next_task=9（Deterministic reference suite + 一次 source full gate：
  `tests/reference/test_017_sandboxed_workspace_execution.py` +
  `tests/reference/test_017_e3_harness.py`，U1 全 journey + mutation
  oracles；随后 `git diff --check` + ruff + 一次完整
  `.venv/bin/python -m pytest -q -rx`）

### Task 9 — Deterministic reference suite + 一次 source full gate（2026-08-27）

- **U1 journeys**（`tests/reference/test_017_sandboxed_workspace_execution.py`，
  冻结 `U1_CLAIMS` 10 条，与 journey 函数 1:1 由 harness 测试强制）：
  端到端走真实 composition 层（FakeQualificationCli probe →
  build_sandbox_resources → KernelToolRuntime + receipt book → exec/capture/
  apply），以 FakeDockerCli argv transcript + 独立计数器（docker 调用数、
  workspace 树 digest、host 效果、host_process_calls）证明：
  unqualified 注册为零、governed execution→captured→applied→read-back 全链
  （multi-command lease 只 create 一次；bundle apply 前 host 零变化）、
  OFF `--network none`、governed internal-only network + 仅
  HTTPS_PROXY/HTTP_PROXY env、无 `--volume/-v/--mount` 且 cp-in 只自 staging、
  oracle：forged receipt / 旧 image-snapshot lease 不匹配（零 create）/
  exit-0 假完成 / duplicate apply base_drift / cleanup 不确定禁止复用。
- **harness 完整性**（`tests/reference/test_017_e3_harness.py`）：claim↔journey
  1:1 闭合；fake transcript 拒绝已作废 `wait`/`logs` lifecycle；qualification
  与 docker 两替身计数互不串扰（exec 不触发额外 probe）；copy-out 物化只作用
  于 cp-out 且落在 product state root（不碰 workspace）。配套扩展
  `tests/sandbox/fakes.py`：`copy_out_writer`（cp-out 物化 sandbox 结果树）。
- **阶段内接线修复**（journey 暴露的真实缺口）：(1) `build_composition` 新增
  `sandbox_receipt_book` 参数并传入 KernelToolRuntime（此前真实 composition
  下 capture 永远 fail closed——book 未接进 runtime）；`SandboxResources`
  暴露 `receipt_book`，main.py 传入。(2) composition closer 改为
  `session_targets` 注入（exec 闭包登记 (env, handle)，teardown 逆序
  `environment.close(handle)`——port 合同是 handle-based，无 handle 无法
  exact 清理）。(3) `build_sandbox_resources` 新增 `proxy_image_digest` 参数
  （governed network 需要 project-owned proxy helper；未配置时 adapter 在首个
  Docker effect 前 fail closed）；egress 模块路径默认取 product 自身文件。
  (4) exec 闭包把 `SandboxProvisionError` 折叠为 known-not-executed
  （首个效果前的确定失败不进 unknown 恢复）。
- **Step 2 focused 017 suite**（未管道直跑）：
  `pytest -q -rx tests/sandbox tests/reference/test_017_sandboxed_workspace_
  execution.py tests/reference/test_017_e3_harness.py` → **213 passed，
  PYTEST_EXIT=0**。
- **Step 3 architecture gates**：`git diff --check` → **DIFF_EXIT=0**；
  `.venv/bin/ruff check .` → **RUFF_EXIT=0**；owner 静态测试
  （`tests/architecture/test_cutover_absence.py`：provider.generate/
  ToolRuntime.invoke 唯一 loop.py、conversation checkpoint CAS owner、
  product tree 闭合）→ **5 passed，EXIT=0**。
- **Step 4 一次完整 source gate**（未管道直跑，输出完整未截断）：
  `.venv/bin/python -m pytest -q -rx` → **1743 passed，PYTEST_EXIT=0，
  224.38s（0:03:44）**。
- **Step 5 source 证据冻结**：root=`<workspace-root>`
  （git HEAD `96a1d770ad5e98b2faab325bf2aebdc76767ec5d`，工作树含 017 未提交
  改动共 44 个路径——按项目规则不 commit）；此后仅做 log-only 追加，不重跑
  full suite。
- next_task=10（Materialized Docker E3 + seal：`scripts/run_017_e3.py`、
  `scripts/verify_017_materialized_tree.py`、E3 receipts、DELIVERY_SEAL、
  独立 review、README/STRATEGY/CURRENT_CAPABILITY_STATUS 提升；Docker daemon
  当前 `docker_daemon_unavailable`——若全部 deterministic/source/materialized
  前置闭合且 Docker 配置为唯一缺口 → 准确输出
  `NEEDS_017_DOCKER_CONFIG(stage=U2)`，不降级）





### Task 10 — Materialized gates、seal、receipts 与准确 blocked 状态（2026-08-27）

- **断点恢复事实**：前一 session 留下 `scripts/run_017_e3.py`、
  `scripts/verify_017_materialized_tree.py`、review PENDING stub 与 seal（267
  entries），但 `017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json` 从未落盘、
  materialized content gate 从未实跑（seal 在 gate 之前计算，时序颠倒）。
- **预检**：两脚本 py_compile 通过；parent seal（016）digest `9b05e552…` 匹配；
  `--check-membership`/`--control-seal` 对当前树双 exit 0；Task 9 freeze
  （08-27 02:31）后 `agent/`、`tests/`、`main.py` 零 mtime 漂移——1743-passed
  source 证据仍绑定当前产品树。
- **终循环（冻结合同允许的唯一一次）**：`run_017_e3.py` 一次。offline 前置
  （diff-check/ruff/source full）全 Green（静默通过）；materialized content
  gate **FAIL**：恰为 `OS_PRIMITIVE_TEST_IDS` 的 5 个测试在 deny-network sandbox
  下失败（1738+5=1743）——`--deselect` 传了绝对路径 node ID，pytest 只匹配
  rootdir 相对形式，排除完全失效（该机制此前从未实跑验证）。
- **最小修复 + reseal**：deselect 改传 `OS_PRIMITIVE_TEST_IDS` 原文（rootdir
  即 tree 根，pyproject.toml 在树内）；实测复现（绝对路径不排除/相对形式排除）
  后修改；`py_compile`+`ruff check .`+`git diff --check` 全 Green。reseal：
  entries 267 与 overlay_root `c9397676…` 不变（verifier 是 control path），
  仅 verifier_sha256 更新为 `a577ec51…`，新 seal digest `71a81c6c…`；
  membership/control-seal 重验双 Green。
- **content gate 重跑（一次，有据——首轮败于 harness 缺陷而非内容）**：
  deny-network 完整 suite **1738 passed, 5 deselected（254.25s）**；
  OS-primitives 独立运行 **5 passed（2.81s）**；**ALL CHECKS PASSED**。
  本地三前置（deterministic U1 / source full / materialized content）全部闭合。
- **Docker qualification（只读探测，未安装/启动/login/pull）**：**daemon 已
  qualified**（client 29.3.1、linux containers、seccomp 通过）——owner 已于
  会话外启动 daemon，与 2026-08-26 探测结果不同。唯一缺口：
  `FIRST_AGENT_017_E3_IMAGE_DIGEST` 未配置（`image_digest_not_configured`）。
- **receipts 落盘**（blocked 分支逐字复用 `run_017_e3` 冻结逻辑 + `receipt_errors`
  校验）：stage=`NEEDS_017_DOCKER_CONFIG`，reason=`image_digest_not_configured`，
  delivery_identity 绑定当前 seal（`71a81c6c…`/267/`c9397676…`/`a577ec51…`），
  closed_preconditions 四项全 true，attempts=[]。准确性修正：
  `missing_owner_actions` 改为从 reason 派生（daemon 已 qualified 时不再提示
  「start daemon」，避免与 qualification facts 自相矛盾）。
- **plan Step 3 验证**：`--check-membership`/`--control-seal`/`--attestation`
  三模式全部 exit 0。
- **已知缺口（留给 unblock 会话，诚实记录）**：runner 冻结的 `U2_JOURNEYS`
  只覆盖 E3 U2 step 2 的 OFF 半边；`PACKAGE_REGISTRY` 半边需要 owner 额外提供
  project-owned proxy helper image（Task 9 记录的 `proxy_image_digest`）并扩展
  runner journey 后才能在真实层验证。
- **capability docs（plan Step 5 gated on U3 PASS → 不改产品树，seal 绑定保持）**：
  README/STRATEGY/CURRENT_CAPABILITY_STATUS 核查均为保守免责（无 sandbox
  delivered 宣称），blocked 状态由 receipts + review + 本 log（皆 control
  path）准确记录。U3 独立 review 保持 PENDING（reviewer 不继承 executor 结论）。
- **017 本轮以 blocked-accurate 状态闭合**：
  `NEEDS_017_DOCKER_CONFIG(stage=U2, reason=image_digest_not_configured)`。
  owner 配置 image digest（及 PACKAGE_REGISTRY proxy image）后，重跑
  `run_017_e3.py`（其 offline 前置会自然重验）→ 三连真实 attempt → U2 PASS
  后执行 U3 fresh review 与 capability 提升。

### Task 10 终循环 — 五轮审计收敛后的官方一次循环与 blocked-accurate 闭合（2026-08-27）

- **五轮独立审计全部 Red→Green 收敛**（Codex 负向复核通过）：runner 补齐
  PACKAGE_REGISTRY 两半真实 oracle、E3 14-16 identity 绑定（server/context/
  wheel/target+proxy image digest）、closed receipt schema（per-stage exact
  keys、frozen attempt ids、readiness/counts/verdicts 类型 closed、U2_FAIL
  真 closed 且永不可 attestation）、`docker context show` 真 context pin
  （无 default fallback）、cleanup 单一 owner（`close_all_sessions` all-then-
  raise + attempt 幂等 close-once + absence 探测）、attempt-scoped request
  identities（environment ids 跨 attempt 两两不交）、C5 写前 identity/rea
  son/facts drift 重验、per-reason 精确 owner actions、probe 强化（mount
  clause-exact / ambient name-only patterns / host-home 通道 / 全 argv
  同一 --context）。合同测试累计 58 条（tests/reference/test_017_real_runner.py）。
- **官方终循环一次**：`scripts/run_017_e3.py` 本尊——offline 三前置
  （diff-check/ruff/未截断 source full，全静默通过）→ materialized content
  gate（clean venv + wheel `40d124eb…`，overlay_root `f38a92e1…` 绑定）
  → bounded `docker context show`（实测 `colima`）+ qualification
  （client 29.3.1 / server 29.2.1 / linux / seccomp → qualified）→
  **`NEEDS_017_DOCKER_CONFIG(stage=U2, reason=image_digest_not_configured)`，
  exit 2**——source/materialized/qualification/产品真实路径全部闭合，两个
  fixed image digest（target+proxy）为唯一缺口。
- **`--attestation` 抓到 verifier 真实缺陷**：脚本直跑上下文中 `agent` 包
  不在 sys.path（runner 有同款路径准备，verifier 的 check_attestation 缺）。
  一行修复（`sys.path.insert(repo_root)`）→ identity 重新闭合：reseal
  （overlay_root 不变 `f38a92e1…`——冻结源完好；verifier digest →
  `166a5cb4…`；seal digest → `18a8d5c0…`）→ receipt 重铸绑定新身份
  （gates 已在本 cycle 对同一 overlay 执行，不重跑；事实即时重探测 + C5
  drift 重验全过）。
- **三 verifier 模式全 exit 0**：membership（268 exact entries）/
  control-seal（009 manifest + 016 parent + verifier + overlay）/
  attestation（blocked shape 绑定当前 delivery identity + 四项 closed
  preconditions）。
- **最终状态**：`NEEDS_017_DOCKER_CONFIG(stage=U2,
  reason=image_digest_not_configured)`；U3 fresh review PENDING
  （reviewer 不继承 executor 结论）。README/STRATEGY/CAPABILITY_STATUS
  维持保守（plan Step 5 gated on U3 PASS；无 sandbox delivered 宣称）。
- **owner unblock 路径**：配置 `FIRST_AGENT_017_E3_IMAGE_DIGEST` 与
  `FIRST_AGENT_017_PROXY_IMAGE_DIGEST`（均 sha256:<hex64>）→ 重跑
  `scripts/run_017_e3.py`（offline 前置自然重验）→ 三连真实 attempt →
  U2 PASS 后执行 U3 fresh review 与 capability 提升。

---

# 017 Native Sandbox 执行记录（corrected 017；Docker 版见上方历史，已 superseded）

Plan: `docs/superpowers/plans/2026-08-27-017-native-sandbox.md`；Executor:
Claude Code GLM 5.3 `effort=max`。规则：T1–T8 只跑 focused + touched Ruff +
`git diff --check`；T9 才跑一次完整 source/materialized/E3；不 commit/push。

### Task 1 — Freeze native contracts and policy identity（2026-08-27）

- Red：`tests/sandbox/test_contracts.py`（重写，9 tests）+
  `tests/sandbox/test_policy.py`（新建，11 tests）先因 native 符号缺失
  collection error 失败，符合预期。
- Green：`agent/sandbox/contracts.py` 重写（closed 三值 mode/network、
  `SandboxPolicyV1` digest 绑定全成员、`SandboxBackendIdentityV1` =
  canonical path + platform/build facts + probe digests、
  `SandboxEnforcementFactsV1` 一致性（none⇔unconfined、seatbelt⇒confined
  +hex64 profile）、`ConfinedInvocationV1`、`SandboxExecutionDraftV1` digest）；
  `agent/sandbox/policy.py` 新建（唯一 admission `build_sandbox_policy`：
  canonical strict + root 不重叠 + git metadata/gitdir bounded 解析 +
  unreadable 派生；`compile_seatbelt_profile` 固定子句 + 单一转义点拒绝
  NUL/换行/引号/反斜杠 + 敏感文件名 regex 子句 + network OFF 独立子句；
  danger 无 profile）；`agent/sandbox/ports.py` 重写为 `SandboxConfiner`
  protocol；`agent/sandbox/__init__.py` native 导出。
- Focused gate：`pytest -q tests/sandbox/test_contracts.py
  tests/sandbox/test_policy.py` → **19 passed，PYTEST_EXIT=0**；
  `ruff check agent/sandbox/ <两测试文件>` → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。
- 已知中间态（按 plan 由 T4/T5/T7 收口）：`agent/runtime/tools.py:52` 的
  Docker 时代 module-level import 与旧 sandbox 模块对旧 contracts 的引用
  暂时断裂；其测试属 plan 替换/删除清单。
- next_task=2

### Task 2 — Qualify and wrap macOS Seatbelt without executing user commands（2026-08-27）

- Red：`tests/sandbox/test_backend_qualification.py`（重写，7 tests）+
  `tests/sandbox/test_seatbelt.py`（新建，7 tests）先 collection error，符合预期。
- Green：`agent/sandbox/qualification.py` 重写（`MINIMAL_PROBE_PROFILE` 与真实
  profile 同方言；`SeatbeltCommandRunner` argument-vector + timeout kill +
  16 KiB cap）；`agent/sandbox/seatbelt.py` 新建（`SeatbeltConfiner`：
  qualify 平台→binary→probe 三段 fail closed、实例级缓存、backend identity
  绑 canonical path/platform/build/probe digests；confine pure wrapping——
  confined 编译 profile 内联 `-p` 传递、danger bypass 不探测 backend、
  unavailable ⇒ `KnownNotExecuted`）。
- 实现注记：`KnownNotExecuted` 为 `(code, message)` 双必填；FakeRunner 记录
  (argv, cwd, env, timeout) 供「绝不执行用户命令」断言。
- Focused gate：`pytest -q tests/sandbox/test_backend_qualification.py
  tests/sandbox/test_seatbelt.py` → **14 passed，PYTEST_EXIT=0**；touched
  Ruff → **RUFF_EXIT=0**；`git diff --check` → **DIFF_EXIT=0**。
- next_task=3

### Task 3 — Share exact process preparation and execute the wrapped invocation（2026-08-27）

- Characterization Green：新增 `tests/process/test_preparation.py`，先保护 exact
  executable identity、cwd descriptor、argv/profile 限制、closed environment、
  approval 后 executable/cwd 漂移与既有 trust preview；抽取前 7 项全部通过。
- Red→Green：新增 `agent/process/preparation.py`，集中纯 process
  preparation/revalidation/environment/path 规则；`agent/process/tools.py` 改为调用
  public seam 并删除已被取代的私有 helper。抽取后完整 `tests/process/` 为
  **98 passed**，证明 local_process 行为保持。
- Executor Red→Green：新增 `tests/sandbox/test_executor.py`（先因
  `agent.sandbox.executor` 缺失而 Red）与 `agent/sandbox/executor.py`；executor 只
  负责 revalidate、per-invocation temp env、confine enforcement-facts 校验与把
  wrapped argv 交给既有 `run_local_process`，不另建 timeout/进程组 owner。
  定向 executor **6 passed**。
- 为解除 import-chain 的计划内硬切换阻塞，提前从 `agent/runtime/tools.py` 删除
  已失效的 Docker capture/apply/bundle dispatch 与其 orphan imports；没有保留
  compatibility fallback，T4/T5/T7 继续完成其余 native cutover。
- Focused closing gate：process 全套 + T1/T2 contracts/policy/qualification/
  Seatbelt + executor 共 **137 passed in 23.34s，PYTEST_EXIT=0**；touched Ruff
  初次发现 7 个 extraction 后 orphan/ordering 问题，机械修正后
  **RUFF_EXIT=0**；`git diff --check` → **DIFF_EXIT=0**。
- next_task=4

### Task 4 — Replace Docker authority with exact native one-shot authority（2026-08-27）

- Red：重写 native authority/tool tests 与 checkpoint v7 continuity tests；初次定向
  运行 **16 failed / 4 passed**，失败均来自旧 reusable Docker authority 与旧
  checkpoint shape，符合预期。
- Green：`SandboxAuthorityCandidateV1` / `SandboxAuthorityLeaseV1` /
  `SandboxReceiptV1` 只绑定 Goal revision、workspace、原始 command fingerprint、
  native policy/mode/network 与 enforcement facts；lease 固定 one-shot、bounded
  capacity，审批后在 durable `EXECUTING` checkpoint 消费。`KernelToolRuntime`
  只接受 exact active lease 与 `SandboxExecutionDraftV1`，重验 lease/draft digest，
  plain-success fail closed；SPAWN_FAILED 不铸 receipt。
- Checkpoint：schema 升到 v7；native candidate/lease exact-key + digest round-trip；
  unknown/missing/forged candidate/lease mutation fail closed；v6 Docker lease 只失效，
  不重签为 native authority，同时保留 non-sandbox v2–v6 migration。
- Focused closing gate：sandbox authority/tools、checkpoint/contracts、approval/
  effect-ordering/process regression 共 **97 passed in 2.04s，PYTEST_EXIT=0**；
  touched Ruff → **RUFF_EXIT=0**；`git diff --check` → **DIFF_EXIT=0**。
- 按阶段规则未跑 full suite；旧 bundle/evidence/tool registration 与 composition
  wiring 由 T5/T6/T7 hard cutover 删除，本阶段没有将它们作为 native 能力证据。
- next_task=5

### Task 5 — Register one native sandbox tool and close completion evidence（2026-08-27）

- Red：新增 single-registration schema/preview 与 native receipt + host read-back
  closure；初次定向 **9 failed / 11 passed**，准确暴露旧 Docker tool import、
  bundle oracle/repair mapping 与缺失 native receipt oracle。
- Green：`agent/sandbox/tools.py` hard replace 为唯一 `sandbox_exec` registration；
  exact 六字段 schema，默认 `workspace-write/off`，共享 process preparation +
  `build_sandbox_policy`，callable 仅委托 `NativeSandboxExecutor`。preview 展示 exact
  command/cwd/profile/mode/network 与 risk notice，不暴露内部 digest/profile source。
  executor 的 ephemeral HOME/TMPDIR 改为在已批准 canonical temp parent 下创建，
  policy 与真实写根不漂移。
- Evidence：删除 `SandboxBundleReceiptV1`、bundle parser/oracle 与 capture/apply gap
  repair；新增 `native_sandbox_v1` closed receipt oracle，重算 canonical receipt、
  核对 flat projection/Goal revision/policy/enforcement/exit-zero。artifact 完成仍同时
  要求独立 `FILESYSTEM_DIGEST` host read-back；output-only、receipt-only、readback-only、
  forged/stale/policy/enforcement drift 全 fail closed。
- Focused closing gate：sandbox tool/executor、evidence registry、VERIFIED_DONE 共
  **63 passed in 0.36s，PYTEST_EXIT=0**；touched Ruff → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。按阶段规则未跑 full suite。
- next_task=6

### Task 6 — Compose automatic qualification and everyday UX（2026-08-27）

- Red：`tests/sandbox/test_composition.py`（重写，7 tests）+
  `tests/cli/test_017_sandbox_experience.py`（重写，8 tests）初次定向
  **13 failed**——native 签名/UNSUPPORTED 状态/三行文案/parser/recovery kinds
  全部缺失，符合预期。`tests/cli/test_everyday_entrypoint.py` 核实零 sandbox
  耦合（plan 的 Modify 落为无改动，记于此）。
- Green：`agent/composition.py` sandbox 区整段替换——`SandboxReadiness
  {UNSUPPORTED, TEMPORARILY_UNAVAILABLE, READY}`、`SandboxResources
  (registrations, readiness, reason_code)`（无 closeables/receipt book）、
  `build_sandbox_resources(workspace, state_root, captured_path, *,
  confiner=None)`：自动 qualification 一次、无论可用性都注册唯一
  ``sandbox_exec``（danger bypass 不依赖 backend；confined 在 confine 处
  fail closed）、per-invocation temp/home 基座在系统 temp 下的 session
  专属目录（policy 冻结四 root 两两不交——修正点：不得位于 state_root
  carveout 内）。删除 Docker 时代的 egress module 引用与 close_all_sessions。
  `main.py`：删除 setup-sandbox 子命令/`_run_sandbox_setup`/profile 持久化
  import 与调用；`_sandbox_status_lines` 重写为三行 closed 文案（ready 带
  默认 mode/network；unavailable 按 closed reason 映射文案；unsupported
  平台行），无 traceback/digest/绝对路径；build 调用改 native kwargs +
  `os.environ PATH`；drop receipt_book/closeables 接线与 SandboxProfileError。
  `agent/continuity/restart.py`：`SANDBOX_RECOVERY_KINDS` 收缩为
  ``{execution_unknown}``，删除 bundle_review/base_drift 分支与
  `_BASE_DRIFT_CODES`（不做 compatibility 映射）。
- Focused closing gate：composition+CLI+everyday+continuity 共
  **282 passed in 1.79s，PYTEST_EXIT=0**；touched Ruff → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。按阶段规则未跑 full suite。
- 执行注记：本轮起所有文件修改仅用 Edit/Write 工具（用户指令）；两处
  测试侧修正（parser seam 名 `build_parser`、roots 系统 temp 设计）经
  外部核对后保留。
- next_task=7

### Task 7 — Hard cutover and architecture absence gates（2026-08-27）

- Red：重写 `tests/architecture/test_017_sandbox_boundary.py`（6 tests：纯模块
  禁 import runtime 器官、Docker 词汇 absence、无动态 registry、sandbox 永不
  回落 local_process、main 只经 build_composition、不 import Coding Agent
  产物）+ `test_cutover_absence.py` expected 集改 native 9 文件、CAS owner
  收缩为唯一 loop。初次定向 **4 failed**（Docker 文件仍在/组合面过宽），
  修正测试边界后进入切除。
- Cutover（rm，逐项核对 plan 清单后删除 20 文件）：
  `agent/sandbox/{apply,bounded_exec,docker,egress_proxy,profile,snapshot,
  store}.py` + 9 个 Docker 测试 + `tests/sandbox/fakes.py` + 3 个旧 reference
  测试（U1/harness/real_runner，后两者本任务重建，real_runner 由 T8 重建）。
  删除后 agent/tests 零残留 importer。附带切除 `agent/runtime/tools.py` 的
  死 `sandbox_apply_bundle` prepare gate（T5 遗漏，kind 永不匹配）。
- U1/harness 重建：`tests/reference/test_017_sandboxed_workspace_execution.py`
  （10 claims↔journeys 1:1：closed modes/默认、carveout profile 断言、
  confine 纯 wrapping 观察、canonical drift、network 分离、closed env、
  backend unavailable confined 零执行+bypass 完好、one-shot receipt 绑定、
  永不裸降级、mutation oracles）+ `test_017_e3_harness.py`（4 tests：claim
  闭合、盲 fake 必被抓、计数器独立、替身不 spawn）。
- Residue gate（plan Step 4 rg）：agent/ **零命中**；tests 命中全为负向
  oracle（v6 fixture 拒绝测试）；docs 命中仅在新 plan 自身删除清单文本。
  scripts/ 属 T8 重写范围（T8 后复查）。
- Focused closing gate：reference+architecture+sandbox 共
  **307 passed in 131.42s，PYTEST_EXIT=0**；touched Ruff → **RUFF_EXIT=0**；
  `git diff --check` → **DIFF_EXIT=0**。按阶段规则未跑 full suite。
- next_task=8

### Task 8 — Native real E3 runner and fail-closed attestation（2026-08-27）

- Receipt/attempt closed schema：native delivery + backend identity；每 attempt 恰有
  11 个 bool journey，并绑定同一 materialized wheel、互异 workspace/temp/sentinel
  digest 与 exclusive `attempt-result.json` journal digest。attempt root 复用与失败重跑
  覆盖均 fail closed；blocked qualification 只接受单一 closed reason。
- Non-vacuous real journeys：control failure 与 unconfining mutation 都会使相应拒绝
  journey 失败；loopback control 改为直接以 `nc` exit status + listener accept 证明
  真实连通；read-back journey 改为 exact one-shot approval 后同时核对 native receipt、
  exit success 与 host digest。
- 真执行发现并闭合 argv ownership bug：`ConfinedInvocationV1.wrapped_argv` 是完整命令，
  `run_local_process` 自行放置 argv[0]；`NativeSandboxExecutor` 现只传 argv[1:]，避免
  真实 spawn 形成 `sandbox-exec sandbox-exec -p ...`。U1 tests 改为同时观察
  `resolved_executable` 与 argument-only `argv`，未放宽 wrapping 合同。
- Materialized execution：source tree 只 materialize 一次；每 attempt 从该 tree 的
  独立 build copy deterministic 构建一次 wheel，wheel digest 必须逐字匹配 content
  artifact；clean venv 禁 system-site-packages、product 与 base dependency 均离线安装；
  child 强制从 installed wheel 导入且校验 origin；每 attempt 后重算 tree digest，任何
  drift 在 receipt 前中止。旧 Docker OS-primitive node/deselect 与安装路径已删除。
- Focused closing gate：reference/harness/sandbox/checkpoint/evidence/architecture 共
  **129 passed in 9.01s，PYTEST_EXIT=0**；deterministic wheel/journal 小组包含在内；
  touched Ruff → **RUFF_EXIT=0**；`git diff --check` → **DIFF_EXIT=0**。按阶段规则
  尚未跑 full/materialized/real 三连。
- next_task=9

### Task 9 — Final source/materialized/real E3 and delivery review（2026-08-27）

- Final ordinary delivery identity：
  - overlay root：`0c261e7f3d38a782ccbe880693614e9bd218ea1d979f2a17fb79432fbac4d6a1`
  - seal SHA-256：`527f47ce26a9eb2f8311fa4a78684dd6854f0e9dfe81dac91a31bc89817989d1`
  - verifier SHA-256：`420617c05052374a511375a70193c7075ce66293a1e66a6f0f7610a798a7b203`
  - runner SHA-256：`91e38340414f48809d023b446da3e5e3da04dfe771c3d69fe403572228f73184`
  - materialized wheel SHA-256：`0ddb10f4bdef4949b9afa395232a626015840e20a9285e46a8aaf428fdf2c3a1`
  - receipt SHA-256：`c8b9c66b7ad649ce6758328afc750bc15c8222dae3d83192aadf15f53f608d08`
- Source/full/materialized 执行：最终冻结 root 上运行
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_017_e3.py`，exit 0，输出
  `017_E3_REAL_PASS attempts=3`。runner 在写 receipt 前依次强制执行 source
  `git diff --check`、全量 Ruff、全量 pytest，以及从 exact materialized source
  deterministic 构建 wheel、clean venv/no-system-site-packages、deny-network
  materialized full suite。3 个必须建立本地 listener 的 control tests 在同一 clean
  interpreter 下以注册 marker 单独执行，恰好 3 项；它们不被当成公网访问。
  runner 的 full-suite 输出只作为 closed pass/fail gate 留存，本记录不猜测被抑制的
  最终 test count。
- 真实 E3：backend 为 `/usr/bin/sandbox-exec`，Darwin `24.5.0`，backend identity
  digest `ce9f27c161d386d703fca10e466350c627cbc4a4b1d2a188a8099d9a0bb5c244`。
  三个 fresh installed-wheel attempts 各 11 journeys，全部为 true；三个 attempt 的
  workspace root、temp root、credential sentinel 与 journal digest 分别两两不同，
  wheel digest 全部与 delivery wheel 精确一致。receipt stage 为 `U2_PASS`。
- 失败轮次没有被覆盖成 Green：
  1. 首次 source full 暴露 v5 checkpoint fixture 仍带当前 native candidate，
     `1649 passed / 1 failed`；修正 fixture 后才进入正式 pipeline。
  2. 两轮 materialized gate 先后暴露 MCP child 缺 verified dependency bridge、
     loopback deselect 使用绝对 node id 无效；改为先证明 optional deps 缺失，再以
     verified `.pth` bridge 注入 test deps，并用注册 marker 精确分离 3 个 loopback
     controls。
  3. 第一轮真实 attempts 因 macOS `/var` → `/private/var` canonical root 不一致而
     11 journeys 全部失败；attempt root 在创建后 resolve，未复用旧 attempt。
  4. 下一轮只剩 timeout profile 与 unavailable-confiner fake 两项失败；前者改为
     exact short profile，后者按 production contract 返回 `KnownNotExecuted`。
  5. 一轮已得到 real pass，但 README/STRATEGY/status 仍是旧 candidate wording；
     用户文档进入 ordinary root 后重新封存并完整重跑，得到上述最终 identity。
- Final host verification（非嵌套 Seatbelt 宿主）：
  - `verify_017_materialized_tree.py --check-membership` →
    `017 overlay membership ok: 261 exact entries`
  - `verify_017_materialized_tree.py --control-seal` → Green
  - `verify_017_materialized_tree.py --attestation` →
    `3 real attempts × 11 journeys bind the current delivery + backend identity`
  - `git diff --check` → exit 0；`.venv/bin/ruff check --no-cache .` →
    `All checks passed!`
- Fresh Codex U3 reviewer（session `01a042e8-a955-7903-92d9-602eb82acb08`）以
  CLI `read-only` sandbox 运行。它独立通过 membership/control-seal、diff-check、
  Ruff、6 architecture tests 与 6 receipt mutation tests，并未发现 Docker product
  path、第二 loop、owner drift 或 receipt shape blocker。其本地 `--attestation`
  因 reviewer 自身已处于 Seatbelt 中，嵌套 `/usr/bin/sandbox-exec` 返回 exit 71
  `sandbox_apply: Operation not permitted`；同一命令紧接着在外层宿主 exit 0，故该
  现象记录为 reviewer 环境限制，不改写 qualified backend 的真实 receipt。
- U3 authoritative verdict 只写入 detached
  `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md`；在 reviewer
  完成对上述三项初始 finding 的复核前，本日志不自行宣称 promotion PASS。
- Reviewer recheck：同一 fresh session 重新核对 Task 9 记录与当前 digest，亲自
  通过 diff-check、Ruff、membership、control-seal、6 architecture tests 与 8 个
  receipt/negative-oracle tests；确认 nested Seatbelt 是 reviewer 环境限制，撤回
  三项初始 blocker，并对 exact overlay root `0c261e7f…` 给出 **PASS**。
- detached independent review 已绑定 seal/verifier/runner/wheel/receipt/backend identity，
  明确记录 reviewer 亲验范围、外层 attestation 与产品限制。
- next_task=none（017 accepted/delivered within frozen macOS native sandbox scope）
