# Runtime v0.2 · Release Candidate Decision

> **本文件目的**：把 v0.2 RC 当前是否「可以宣告 release candidate」「可以进入
> 人工试用」「可以决定 push 时机」这三件事一次性写清楚，让后续操作不再
> 反复在「是否宣告 RC」上纠结。
>
> **本文件不是 spec，不引入新功能，不重写 roadmap**。它是判定与操作清单。

---

## 1. v0.2 RC 判定

**判定结果**：✅ **满足 release candidate 条件**。

依据：
- M1-M4 主线 + M5/M6（preflight + P0/P1/P2）全部闭环（见
  `docs/V0_2_RC_STATUS.md` §1）。
- 自动化 smoke 100% 覆盖 v0.2 RC 范围内的安全断言、状态机不变量、
  checkpoint 恢复、错误恢复、CLI 输出契约（见 RC_STATUS §2.2.1）。
- `pytest -q`：**528 passed, 3 xfailed**；`ruff check`：0 错误。
- 3 个 xfailed 全部归属 v0.2 输入语义治理 / v0.2 cancel 生命周期 /
  v0.3 高级 TUI，**不阻塞 RC**（见 RC_STATUS §3）。
- 真实 smoke 暴露的两个非平凡缺口（项目外写硬拦截 / policy denial 误归类
  为用户连续拒绝）已修复并固化回归测试。

**仍未提供，但**不阻塞 RC**的能力（明确登记非目标）：
- 基础 TUI / 状态面板（规划在 `docs/V0_2_BASIC_TUI_PLAN.md`）
- Skill 子系统正式化、sub-agent
- complex topic switch / slash command 体系
- `generation.cancelled` RuntimeEvent + Textual Esc 集成
- 完整安全沙箱（文件系统 / 网络 / 子进程隔离）
- read 路径内容前缀扫描（write 已有 P1-B 收敛）
- `install_skill` 单次确认即执行（依赖 Skill 整体设计）
- shell `$()` / `eval` / hex 转义高级绕过（v0.3 命令解析层）

---

## 2. 已完成能力清单

| 能力 | 文档 | 状态 |
|---|---|---|
| Runtime 状态机集合 + 转移规则 | `docs/RUNTIME_STATE_MACHINE.md` | ✅ |
| 事件边界（InputIntent/RuntimeEvent/DisplayEvent） | `docs/RUNTIME_EVENT_BOUNDARIES.md` | ✅ |
| Checkpoint 恢复语义 + 字段白名单硬化 | `docs/CHECKPOINT_RESUME_SEMANTICS.md` | ✅ |
| 错误恢复 / loop guard / no-progress | `docs/RUNTIME_ERROR_RECOVERY.md` | ✅ |
| 工具体系审计 + 安全权限边界 | `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` | ✅ preflight + P0/P1/P2 全部落地 |
| 自动化 smoke 收口 | `docs/V0_2_RC_STATUS.md` §2.2.1 | ✅ 528 passed |
| LLM Processing MVP + 错误分类 + live smoke | `docs/LLM_PROCESSING_CAPABILITY_MATRIX.md` | ✅（v0.2 早期已收口） |
| CLI 输出契约（v0.1 冻结） | `docs/CLI_OUTPUT_CONTRACT.md` | ✅ 不退化 |

---

## 3. 人工试用最短路径

**目标**：在 10-15 分钟内观察自动化无法替代的三类人工体验。
**前提**：`pytest -q` 已通过。如未通过，先停止试用，回到自动 smoke。

### 步骤 1：CLI 启动 + 简单工具（约 3 分钟）

```bash
.venv/bin/python main.py
```

输入：
```
请用 calculate 算 (13*17)+1，然后用 read_file 读取 README.md 的开头部分。
```

观察点：
- 状态/进度提示是否人能看懂
- 工具确认 prompt 文案是否清晰
- 工具结果不被打印为 raw dict
- 输出无 ANSI 控制字符乱码、无 protocol dump

### 步骤 2：安全拒绝消息可读性（约 3 分钟）

继续在同一会话或新会话输入：
```
请读取 ~/.env
```

期望：
- 收到 `[安全策略] 路径 ... 被识别为敏感配置/密钥文件...`
- 任务停止消息是「工具调用被安全策略阻断，本任务已停止。具体拒绝
  原因见上方工具消息。」
- **绝不**应出现「用户连续拒绝多次操作」

再输入：
```
请把 hello 写到 ~/v0_2_smoke.txt
```

期望：
- 直接被拒，提示路径在项目目录之外
- **不询问** confirm

### 步骤 3：plan / step 流转可读性（约 5 分钟）

输入一个真实需要 plan 的任务：
```
请读取 README.md 第 1-30 行，并把一段中文摘要写入 workspace/v0_2_smoke_summary.md
```

观察点：
- plan 渲染清晰、step 推进有可见提示
- write_file 的 confirm prompt 显示路径与内容预览
- 完成后 `summary` 类输出可读
- 退出后 `state.json` / `runs/` 不被 git 追踪
  （`git status --short` 不应有这些）

### 步骤 4：（可选）真实 LLM live smoke

仅在你愿意花费真实 API 配额时按
`docs/LLM_PROVIDER_LIVE_SMOKE.md` 执行。**默认不跑**。

---

## 4. push 前需要用户确认的事项

1. ✅ `pytest -q` 通过（528 passed, 3 xfailed）。
2. ⬜ 步骤 1-3 人工试用无主观体验阻塞问题。
3. ⬜ 同意「v0.2 RC 不包含基础 TUI、Skill 正式化、generation cancel UI 集成」
   这一非目标范围。
4. ⬜ 同意当前本地 34 commits 的提交历史**不重写**、**整段 push**。

如果以上 4 条都满足，可以由用户在自己机器上执行：
```bash
git push origin main
```
本工作链**不会自动 push**。

---

## 5. 本地 34 commits 处理建议

**强烈建议**：
- ❌ 不要 rebase / squash 已有 commit 历史。每个 commit 是一段
  可独立审计的 spec/test/fix 迁移单元，合并后会丢失「哪一步在解决
  哪个真实问题」。
- ❌ 不要分批 push。整段 push 时间线最干净。
- ✅ 等用户人工试用通过后，统一一次 push。

---

## 6. 下一个 milestone

参见 `docs/V0_2_BASIC_TUI_PLAN.md`：v0.2 基础 TUI / CLI UX milestone。
**该文档仅做 planning，不做 Textual 实现**；v0.3 才是高级 TUI 实现的
发起阶段。
