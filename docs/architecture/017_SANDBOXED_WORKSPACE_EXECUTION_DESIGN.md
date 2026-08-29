# 017 Sandboxed Workspace Execution Design

- Date: 2026-08-27（corrected native sandbox 版，取代 2026-08-26 Docker 版）
- Status: frozen-user-approved-2026-08-27（随 spec；用户已 review 并批准
  corrected native design）
- Authority: `docs/superpowers/specs/2026-08-27-native-sandbox-design.md`

> **Superseded 2026-08-27（用户裁决，方向层面）**：本文件原 Docker/container
> 版设计（multi-command lease、copy-in snapshot、ChangeBundle、egress
> proxy、image digest）整体作废，不得继续作为 promotion 证据；其
> seal/receipt 一律 superseded。以下为 corrected native sandbox 设计，与
> 上述 frozen spec 一致。

本文定义用户已批准冻结的 corrected 017 合同（owner、backend、policy、
路径与 unknown-outcome）。实现不得偏离本文；修改本文必须先回到 design
review。

## 1. 用户结果

用户可以要求 First Agent 在当前 workspace 用本机受限进程环境运行 shell、
脚本、测试与构建（同 Codex/DeepSeek Harness 的本机 coding shell）。模型
提出 exact command；命令在自己的机器与工具链上执行——host 可读、写受限
于 workspace、credential 区不可读、默认无网络。不是容器化开发环境，没有
副本搬运。

## 2. 不可破坏的 owner 合同（继承 spec §3 与 AGENTS.md）

- `AgentRuntime.run_turn` 是唯一 production model/tool loop 与 checkpoint
  mutation owner。
- `ContextManager` 独占模型上下文选择；`KernelToolRuntime` 独占 tool
  callable 的 admission、policy、approval 与 invoke。
- sandbox adapter 是纯 external-effect 模块：`confine(argv, policy) ->
  wrapped argv + enforcement facts`（bypass 时 `backend=none /
  enforcement=unconfined`）；不认识 Goal/Provider/ContextPack/approval/
  checkpoint，不推进 state，不执行第二套 loop。
- 所有 side effect 仍走 policy/approval、`EXECUTING` 与 result checkpoint
  顺序；不出现 service locator、compatibility fallback 或 dormant flag。

## 3. Backend（v1 只做 macOS Seatbelt）

- macOS：`/usr/bin/sandbox-exec`（Seatbelt）；profile 由 policy 编译；
  进程树继承约束。
- Linux：后续 adapter（bubblewrap 优先、Landlock 兜底），仅接口预留。
- Windows：deferred / fail closed。
- backend unavailable → **仅 confined modes（read-only/workspace-write）
  fail closed**，绝不静默降级；`danger-full-access` 是 §4 的显式
  unconfined bypass，不依赖 Seatbelt qualification。

## 4. Policy modes（closed 三值）

`read-only` / `workspace-write`（default，命令任务）/ `danger-full-access`
（**显式 unconfined bypass**，仅 exact user approval，逐命令批准；其
receipt/enforcement facts 如实记录 `backend=none / enforcement=
unconfined`）。无第四种；policy 不可拼接。

## 5. 读写模型与路径（对齐官方 same-world 语义）

- **默认可读**：两种 confined mode 都允许读取 host filesystem（含 host
  PATH/toolchain）以保持本机工具链可用；在此之上定义 closed carveouts：
  - **read-only metadata（可读、禁止写）**：`.git`（含 gitdir 目标）与
    `.codex`——不能写成读写都拒，否则 `git status` 等失效。
  - **unreadable（读写都拒）**：credential/private/product runtime roots
    与 `.env`/secret 文件名模式；不笼统宣称整个 host home 不可读。
- **可写集**：`workspace-write` = 当前 workspace（排除 carveouts）+
  canonical per-invocation 临时目录；`read-only` 除 backend 必需
  literal（`/dev/null` 等）外不写。
- workspace root 必须 canonical；symlink 漂移 fail closed。
- **环境**：confined env 使用 closed allowlist（不继承 provider
  credential）；`HOME`/XDG/cache 指向 per-invocation temp。host
  PATH/toolchain 可读可执行，但不承诺任意 host 工具一定兼容——不兼容的
  工具准确失败或经明确 escalation，不静默放宽。

## 6. Superseded 组件（不存在于本设计）

image、image digest、Docker daemon、snapshot copy-in/copy-out、proxy
sidecar、ChangeBundle host apply。direct workspace mutation 就是已批准
exact command 的 effect。

## 7. Filesystem seam 与 network policy 的分离

- filesystem sandbox seam 只声明 file effects（同 DeepSeek vocabulary）；
  017 复用 Seatbelt 的**独立 network policy** 作为额外约束层，不与
  filesystem seam 混同。
- v1 network default OFF；full network 与 exact command/policy 一起经
  用户显式批准，且仅当 Seatbelt 可精确表达；allowlist/managed proxy
  deferred；永不需要 proxy image。
- credential/env 隔离不虚称为 filesystem seam 的证明：env 最小化由
  ToolRuntime/runner composition 负责；timeout/进程组清理由现有 process
  owner（`agent.process.group`）负责。

## 8. Unknown outcome（继承既有合同）

- effect 前明确失败 → `KnownNotExecuted`，可重新规划。
- effect 已执行且 receipt 完整 → read-back/verify，不重复。
- 无法确认 → unknown-outcome recovery；不盲目重放。
- cleanup 无法证明 → `CLEANUP_UNKNOWN`：禁止复用，保留诊断，needs-human。

## 9. 完成语义（不变）

`VERIFIED_DONE` 需 durable tool receipt + host read-back evidence；
exit 0 alone 不得声明完成。

## 10. 明确 non-goals

background process、TTY、daemon、sudo、跨 workspace 写、Windows、
credential broker、自动安装/启动 backend。

## 11. E3 验收矩阵

见 `docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3.md`（含
toolchain/git-metadata 可用性 journeys 的真实 macOS Seatbelt 版）。
