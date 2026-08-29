---
title: "017 Native Sandbox Design（corrected）"
date: 2026-08-27
status: frozen-user-approved-2026-08-27
authority: user-approved-written-spec-2026-08-27
supersedes: docs/superpowers/specs/2026-08-26-governed-execution-program-design.md §4 的 Docker/container sandbox 方向；docs/architecture/017_SANDBOXED_WORKSPACE_EXECUTION_DESIGN.md（Docker 版）；docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md（Docker 版）
---

# 017 Native Sandbox Design（corrected 017，frozen）

> **状态说明**：用户已于 2026-08-27 review 并批准本书面 spec。本文现为
> corrected 017 的 frozen authority；任何实现方向变更都必须先回到 design
> review。此前 Docker 版本及其证据继续作废。

## 0. 背景与裁决

官方源码研究（见 §14 来源）确认：Codex 与 DeepSeek Harness 共同采用
**same-world native process confinement**（OS 级机制约束本机 coding shell
进程，而非容器化副本）。二者各自的形状：**DeepSeek** macOS profile 是
allow-default + deny writes + write allowlists，且其 sandbox vocabulary
只声明 file effects；**Codex** 另行证明 full-disk read 可以叠加
unreadable carveouts，并把 `.git`/`.codex` 设为只读 metadata。**017 选择
组合这两者**——采用 DeepSeek 的 write-confinement 形状，叠加 Codex 式的
unreadable carveouts 与只读 metadata；credential carveout 是 017 的组合
选择，不归因于 DeepSeek 默认。此前 017 的
Docker/container/image/proxy/ChangeBundle 方向与该产品目标不符，经用户
批准整体重做。旧 Docker 设计与其全部 artifacts（seal/receipt/E3
receipts）一律 superseded，不得继续作为 promotion 证据。

## 1. 产品目标

像 Codex/DeepSeek Harness 的本机 coding shell：模型提出 **exact command**
（executable + argv + cwd），该命令在本机受限进程环境中执行——host
filesystem 默认可读（本机 toolchain 可用），写入限制在 workspace，
credential 类路径不可读，默认无网络。不是 devcontainer，没有副本搬运。

## 2. Backend（v1 只做 macOS Seatbelt）

- **macOS v1**：`/usr/bin/sandbox-exec`（Seatbelt）。profile 由 policy
  编译；进程树整体继承约束（子进程同 policy）。
- **Linux**：后续 platform adapter——bubblewrap 优先，Landlock 兜底；
  仅接口预留（§3），不实现。
- **Windows**：deferred；要求时 fail closed，不做模拟。
- **fail closed 边界**：`read-only` / `workspace-write`（confined modes）
  在 backend unavailable 时一律 fail closed，绝不静默降级；
  `danger-full-access` 是 §4 定义的显式 unconfined bypass，**不依赖**
  Seatbelt qualification，因此 backend unavailable 只使 confined modes
  不可用。

## 3. Deep module interface

```text
confine(argv: ExactCommand, policy: SandboxPolicy) -> ConfinedInvocation
# ConfinedInvocation = { wrapped_argv, enforcement_facts }
```

- adapter 只做一件事：把 exact argv 包装为受约束的可执行形式，并返回
  可验证的 enforcement facts（backend、profile digest、受约束范围；bypass
  时 `backend=none / enforcement=unconfined`）。
- adapter **不认识** Goal/provider/approval/checkpoint；不推进 state；
  不执行第二套 loop；不解析模型输出。
- 唯一 production 执行入口不变：`KernelToolRuntime` 在 durable
  `EXECUTING` checkpoint 之后 invoke 该 adapter；result checkpoint 顺序
  与现有合同一致（继承 AGENTS.md owner invariants）。

## 4. Policy modes（closed 三值）

| mode | 语义 | 授权 |
| --- | --- | --- |
| `read-only` | host 可读（含 carveout 例外，§5），除 backend 必需 literal（如 `/dev/null`）外不写 | 默认可用于任意已批准命令 |
| `workspace-write` | workspace + per-invocation temp 可写（排除 carveouts），其余只读 | **default**（命令任务） |
| `danger-full-access` | **显式 unconfined bypass**——不做任何 OS 级约束 | **仅 exact user approval**，逐命令显式批准 |

- confined modes 在 backend unavailable 时 fail closed（§2），不静默降级。
- bypass 不依赖 sandbox backend；其 receipt/enforcement facts 必须如实
  记录 `backend=none / enforcement=unconfined`，不得伪装成受约束执行。
- 不存在第四种 mode；不允许 policy 字符串拼接。

## 5. 读写模型与路径（对齐官方 same-world 语义）

**默认可读**：`read-only` 与 `workspace-write` 都允许读取 host
filesystem（含 host PATH/toolchain），以保持本机工具链可用；在此之上
定义两类 closed carveout：

- **read-only metadata（可读、禁止写）**：`.git`（含 `gitdir:` 指向的
  目标）与 `.codex`。写成「读写都拒」会让 `git status` 等失效——不允许。
- **unreadable（读写都拒绝）**：credential/private/product runtime roots
  与 `.env`/secret 文件名模式。不得笼统宣称整个 host home 不可读。

**可写集**：

- `workspace-write`：仅当前 workspace（排除上述 carveouts）+ canonical
  per-invocation 临时目录。
- `read-only`：除 backend 必需 literal（`/dev/null` 等）外一律不写。
- workspace root 必须 **canonical**（resolve 后无 symlink 漂移）。

**环境与工具链**：

- confined 进程 env 使用 **closed allowlist**（最小白名单），不继承
  provider credential；`HOME`/XDG/cache 指向 per-invocation temp，而不是
  继承含 credential 的 host env。
- host PATH/toolchain 可读可执行；但**不承诺任意 host 工具一定兼容**
  （缺 env/缺 cache 的工具应准确失败，或经明确 escalation 到
  `danger-full-access`），不静默放宽约束。

## 6. Superseded 组件（本设计明确不需要）

image、image digest、Docker daemon、workspace snapshot copy-in/copy-out、
egress proxy sidecar、ChangeBundle host apply——全部删除，不再出现于任何
017 合同、工具面或 receipt。direct workspace mutation 就是已批准 exact
command 的 effect（§9）。

## 7. Shell 与工具链

- 使用**现有 host toolchain**（用户 PATH 里的 python/node/git/…）；不打包
  运行时、不固定 image。
- 模型只提出 exact command；`ToolRuntime` 保持唯一审批/执行 owner；
  bounded I/O、timeout、进程组清理沿用 015 既有合同（`agent.process.group`
  seam）。

## 8. Filesystem seam 与 network policy 的分离

- DeepSeek 的 sandbox seam **只声明 file effects**（其 vocabulary 不含
  network/env/process）；017 选择**复用 Seatbelt 的独立 network policy**
  作为额外约束层，二者不混同。
- v1 network **default OFF**；full network 与 exact command/policy 一起
  经用户显式批准后开启，且仅当 Seatbelt 可精确表达（否则不开）；
  domain allowlist / managed proxy **deferred**，永不需要 proxy image。
- **不得**把 credential/env 隔离或进程隔离虚称为 filesystem seam 本身的
  证明：env 最小化由 ToolRuntime/runner composition 负责；timeout 与
  进程组清理由现有 process owner（`agent.process.group`）负责。

## 9. Effects 与完成语义

- direct workspace mutation = 已批准 exact command 的 effect；没有
  bundle/apply 二段式。
- **completion 语义不变**：`VERIFIED_DONE` 仍需 durable tool receipt +
  host read-back evidence；exit 0 alone 不得声明完成（继承既有
  false-completion oracle）。

## 10. Non-goals（017 边界不变）

background process、TTY、daemon、sudo、跨 workspace 写、Windows、
credential broker、自动安装/启动任何 backend。

## 11. Setup UX

- 默认**自动 qualification**（启动时只读探测 backend 可用性）；不要求
  `setup-sandbox`、不要求 image digest 配置。
- 不可用 → 一条 actionable fail-closed 消息（说明缺什么、如何修；仅影响
  confined modes），无 traceback、无静默降级。

## 12. E3 验收（真实 macOS Seatbelt journey，含可用性）

每 journey 用真实 `/usr/bin/sandbox-exec` 驱动（bypass journey 除外），
无 Docker receipt/镜像字段。receipt 的 backend identity 是 **canonical
executable path + platform/build facts + functional probe result +
profile digest**——`/usr/bin/sandbox-exec` 没有稳定的「版本事实」可依赖；
若实现最终能安全绑定 binary digest 可作为额外字段，但不是当前承诺。不
读取真实 credential——敏感读取一律用**临时 fixture sentinel**；所有拒绝
journey 必须非 vacuous：先以未隔离 control 证明测试前提（目标可写/可读/
可连接），再证明 confined 失败且副作用未发生：

1. **host toolchain 可用**：confined 进程能读取并执行 host 工具链（至少
   `/bin/sh` 或当前 interpreter）。
2. **git metadata 可读、写被拒**：fresh git fixture 下 control 先证明可读；
   confined 读取成功（`git status` 类操作可用）、写入失败。
3. **workspace 内写成功**：confined 进程在 workspace 写文件并读回一致。
4. **workspace 外写拒绝**：control 先证明临时 target parent 未隔离可写；
   confined 写失败且目标未出现。
5. **unreadable credential sentinel**：先创建 sentinel 并由 control 读取
   成功，再将 exact fixture path 加入 unreadable carveout；confined 读取
   失败。不得使用真实 credential。
6. **network OFF 拒绝**：启动临时 loopback listener，control 连接成功；
   confined 连接失败（不依赖公网状态）。
7. **process tree 继承**：child 写入一个 control 已证明可写的外部临时
   target；confined child 失败且目标未出现。
8. **timeout/cleanup**：超时命令被 cap 且进程组清理可证明。
9. **backend unavailable fail closed（仅 confined modes）**：探测失败时
   read-only/workspace-write 命令零执行；danger-full-access 不受影响。
10. **approval escalation / bypass facts**：`danger-full-access` 未经
    exact approval 零执行；批准后只写**测试专用外部临时 fixture**，receipt
    以明确 `backend=none / enforcement=unconfined` facts 记录，不碰用户
    其他路径（不要求 sandbox backend）。
11. **read-back completion**：exit 0 + receipt + host read-back 三者齐全才
    满足 criterion（false-completion oracle 保持）。

## 13. 迁移策略

1. 现有 Docker 017 artifacts（design/E3 文档、`agent/sandbox/*` Docker
   路径、scripts、receipts、seal、execution log 记录）**冻结为
   superseded**；其 seal/receipt 不再采信，不作为 promotion 证据。
2. 实现阶段按 TDD 删除/替换**仅 017 相关路径**；保留 016 成果与架构
   深化改动（`agent/process/group.py`、`tool_governance` 等被 017 复用
   的 seam 一并保留）。
3. promotion 流程照旧：E3（§12）全绿 + 独立 review 后才更新 capability
   文档。

## 14. 官方来源与事实（研究依据）

- DeepSeek sandbox README:
  https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox/README.md
  ——macOS Seatbelt profile 为 allow-default（默认允许）+ deny writes +
  write allowlists 的形状；其 sandbox vocabulary **只声明 file effects**。
- Codex core: https://github.com/openai/codex/blob/main/codex-rs/core/README.md
- Codex Linux sandbox:
  https://github.com/openai/codex/blob/main/codex-rs/linux-sandbox/README.md
- Codex Seatbelt source:
  https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/seatbelt.rs
  ——允许 full-disk read + unreadable carveouts，并把 `.git`/`.codex` 设为
  只读 metadata。
