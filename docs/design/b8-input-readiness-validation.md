# B8 Input Readiness — IME / Paste / Multiline Validation

**创建日期**: 2026-06-02
**状态**: DRAFT — manual terminal validation pending
**范围**: B8 TUI InputBar 的 IME 输入、粘贴、多行输入 readiness
**Source**: handoff §8 D-06, M8 R14 (blocked-ime)

---

## 1. Current State

### 1.1 InputBar 实现现状

`tui/src/components/InputBar.tsx` 使用 Ink `useInput` hook 处理键盘输入：

```
useInput((input, key) => {
  if (key.return) { /* submit */ }
  if (key.backspace || key.delete) { /* 删除末字符 */ }
  if (input.length === 1 && !key.ctrl && !key.meta) { /* 追加字符 */ }
})
```

### 1.2 已知限制

| 限制 | 原因 | 影响 |
|------|------|------|
| **IME 组合态** | Ink `useInput` 不暴露 compositionstart/compositionend 事件 | CJK 输入时中间态字符可能被逐键提交 |
| **粘贴多行文本** | `key.return` 触发 submit，多行粘贴中的换行符可能意外提交 | 粘贴含换行的文本时行为不确定 |
| **剪贴板粘贴** | Ink `useInput` 不区分键盘输入和粘贴 | 粘贴长文本可能被截断或逐字符处理 |
| **Ctrl+V 处理** | 当前过滤 `key.ctrl` 时不追加字符 | Ctrl+V 粘贴无法工作 |
| **方向键/Home/End** | 未处理光标移动 | 无法编辑中间位置的文本 |
| **选中文本替换** | 无文本选中机制 | 粘贴无法替换选中文本 |

### 1.3 已处理

| 能力 | 状态 | 说明 |
|------|------|------|
| 基本英文输入 | done | 单字符追加正常工作 |
| 退格删除 | done | backspace/delete 均处理 |
| Enter 提交 | done | trim + 非空检查 + onSubmit |
| Ctrl 组合键 | done | 被显式过滤 |
| Meta 组合键 | done | 被显式过滤 |
| disabled 状态 | done | 无 lens 时阻止提交 |
| Tab focus cycling | done | WorkbenchLayout 层处理 |

---

## 2. Validation Checklist

### 2.1 IME 输入 (Chinese/Japanese/Korean)

| # | Scenario | Expected | Auto-testable? | Status |
|---|----------|----------|---------------|--------|
| I1 | 中文拼音输入 (macOS 拼音) | 组合态不提交，确认后完整中文进入 InputBar | **no** (需真实终端) | MANUAL_PENDING |
| I2 | 中文拼音输入中间态按 Enter | 不应提交中间态拼音 | **no** | MANUAL_PENDING |
| I3 | 日文输入 (macOS 假名) | 组合态不提交 | **no** | MANUAL_PENDING |
| I4 | 韩文输入 (macOS 韩文) | 完成态字符正确追加 | **no** | MANUAL_PENDING |
| I5 | IME 切换 (中文→英文→中文) | 切换不丢字符 | **no** | MANUAL_PENDING |
| I6 | 中文 + 英文混合输入 | 混合文本正确拼接 | **no** | MANUAL_PENDING |
| I7 | 中文输入后 Backspace | 按完整字符删除（不产生乱码） | **no** | MANUAL_PENDING |

### 2.2 粘贴 (Paste)

| # | Scenario | Expected | Auto-testable? | Status |
|---|----------|----------|---------------|--------|
| P1 | 粘贴短文本 (< 50 chars) | 正确追加到现有输入 | **partial** (可 mock) | NOT_TESTED |
| P2 | 粘贴长文本 (> 500 chars) | 全部追加或明确截断，不崩溃 | **partial** | NOT_TESTED |
| P3 | 粘贴含换行的多行文本 | 不意外提交，所有行可见 | **partial** | NOT_TESTED |
| P4 | 粘贴后 Enter 提交 | 仅提交 paste 后的完整文本 | **partial** | NOT_TESTED |
| P5 | 粘贴空字符串 | 无效果 | **partial** | NOT_TESTED |
| P6 | 粘贴含特殊字符 (tab, null, emoji) | emoji 保留，控制字符安全过滤或显示 | **partial** | NOT_TESTED |
| P7 | 粘贴含 CJK 的混合文本 | CJK + ASCII 混合文本完整保留 | **partial** | NOT_TESTED |

### 2.3 多行输入 (Multiline)

| # | Scenario | Expected | Auto-testable? | Status |
|---|----------|----------|---------------|--------|
| M1 | 手动输入多行 (Shift+Enter 或类似) | 多行可见，不提交 | **partial** | NOT_IMPLEMENTED |
| M2 | 多行文本导航 (上下方向键) | 可在多行间移动 | **partial** | NOT_IMPLEMENTED |
| M3 | 多行文本 Backspace 跨行删除 | 正确合并行 | **partial** | NOT_IMPLEMENTED |
| M4 | 多行模式提交 (专用快捷键) | 只在显式 submit 时提交全部行 | **partial** | NOT_IMPLEMENTED |

### 2.4 终端兼容性

| # | Terminal | 版本要求 | Status |
|---|----------|---------|--------|
| T1 | iTerm2 (macOS) | latest stable | MANUAL_PENDING |
| T2 | Terminal.app (macOS) | bundled with macOS | MANUAL_PENDING |
| T3 | Warp (macOS) | latest stable | MANUAL_PENDING |
| T4 | kitty (macOS/Linux) | latest stable | MANUAL_PENDING |
| T5 | Windows Terminal | latest stable | MANUAL_PENDING |
| T6 | VS Code integrated terminal | latest stable | MANUAL_PENDING |

### 2.5 安全 / 边界

| # | Scenario | Expected | Auto-testable? | Status |
|---|----------|----------|---------------|--------|
| S1 | ANSI escape injection 粘贴 | 不渲染 escape 序列 | **yes** | NOT_TESTED |
| S2 | 超长输入 (> 10000 chars) | 截断或限制，不 OOM | **yes** | NOT_TESTED |
| S3 | null byte 粘贴 | 不崩溃 | **yes** | NOT_TESTED |
| S4 | 粘贴后立即 Ctrl+C | 不崩溃，不丢 session 状态 | **no** | MANUAL_PENDING |

---

## 3. Testability Assessment

### 3.1 可自动化

这些场景可通过 Ink `render()` + 模拟 `useInput` 事件测试：

- 基本字符追加 (已有 implicit 覆盖在 layout.test.tsx)
- 特殊字符过滤
- 输入长度边界
- disabled 状态下输入被忽略
- Enter 提交 + trim 行为

### 3.2 仅限手动验证

这些场景必须真实终端：

- IME 组合态 (compositionstart/compositionend 事件在 Ink 模拟环境中不可用)
- 系统剪贴板粘贴 (依赖 OS clipboard API)
- 终端 emulator 特定行为 (Kitty 键盘协议 vs xterm)
- CJK 渲染宽度 (全角/半角)

### 3.3 诚实声明

**IME/paste/multiline 输入 readiness 不能用自动化测试完全覆盖。**
M8 R14 在以下条件满足前保持 `blocked-ime`：
1. 至少一个真实终端验证通过
2. CJK IME 输入无字符损坏
3. 粘贴多行文本不意外提交

---

## 4. Implementation Options (参考)

以下方案仅记录为设计参考，**不在本阶段实现**（blocked by user validation）：

### Option A: 保持当前 InputBar (简单场景可用)
- 纯英文 + 短输入 OK
- CJK/IME/paste 期望用户使用终端自带功能
- 不实现多行

### Option B: 接入 Ink TextInput
- Ink 有 `<TextInput>` 组件，支持 cursor/IME/paste
- 需完全重写 InputBar
- 需确认 `ink` 版本 ≥ 4.x 的 TextInput 稳定性

### Option C: 用 raw `process.stdin` 替换 useInput
- 最大控制权，但需自行处理 ANSI escape / raw mode / 跨平台
- 工作量大，不推荐

**推荐路径**: 在当前 fake/local MVP 阶段保持 Option A。default entry 激活前必须验证真实终端 IME 行为，根据结果选择 Option A 继续或迁移 Option B。

---

## 5. Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-02 | 不实现多行输入 (M1-M4 not implemented) | 当前 interaction MVP 不要求多行 |
| 2026-06-02 | IME/paste 归入 manual validation pending | Ink `useInput` 不支持 composition/IME events 的自动化测试 |
| 2026-06-02 | R14 保持 blocked-ime | 需真实终端至少一次验证通过 |

---

## 6. Related

- `tui/src/components/InputBar.tsx` — 当前实现
- `tui/src/components/WorkbenchLayout.tsx` — Tab focus cycling
- `tui/src/data/defaultEntryReadiness.ts` — M8 R14 (blocked-ime)
- `docs/design/first-agent-tui-design.md` — 终端原生设计原则
- `docs/handoff/first-agent-current-stage-close-out-2026-06-02.md` — §8 D-06
