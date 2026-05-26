# Run Summary Compact Report Design

- **Date:** 2026-05-26
- **Status:** active
- **Source:** Industry Capability Gap Audit §J Loop 5

## 1. 问题

当前 `run_summary_event()` 已产出结构化多行摘要，但缺少：
1. **Compact 单行格式** — 适合日志/脚本解析
2. **脱敏状态指示** — 用户不知道输出是否被脱敏过
3. **Provider mode 上下文** — 摘要中不含当前 provider 信息

## 2. Compact Format

```
[run] iter=N tools=N(t1,t2) mem=N(a1) sub=N(s1) mode=fake redacted=yes|no stop=<reason>
```

各字段仅在 >0 时展示。普通对话（全零）：
```
[run] iter=1 — 普通对话，无工具/Memory/SubAgent 活动。mode=fake
```

## 3. Redaction Status

- `redacted=yes`：至少一个字段被 `_mask_preview_secrets()` 修改
- `redacted=no`：所有字段保持原样
- 脱敏指示器不泄露被脱敏内容

## 4. CLI Integration

不新增 subcommand。compact format 通过 `render_compact_run_summary()` 函数提供，
调用方（CLI renderer、log viewer、health report）可直接使用。

## 5. Out of Scope

- 不新增 observability backend
- 不做 dashboard UI
- 不读取真实 traces
- 不改变 RuntimeAction semantics
- 不新增 subcommand
- 不改变 run_summary_event 的 text 格式（多行版本保持不变）
