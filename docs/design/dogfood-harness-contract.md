# Dogfood Harness Contract

- **Date:** 2026-05-26
- **Status:** active
- **Source:** Industry Capability Gap Audit §J Loop 4

## 1. 问题

当前 `scripts/dogfood*` 脚本存在 bespoke/stateful 问题：

1. **硬编码报告路径**：每个脚本自己写 `docs/dogfood/*.md` 或 `*.json`，重跑可能覆盖历史报告
2. **无统一 StepResult schema**：每个脚本的 pass/fail/skip 记录格式不同
3. **无脱敏 helper**：每个脚本自己处理 secret redaction，容易遗漏
4. **无 temp workspace 约定**：公开文档中的 workspace 路径依赖不确定

## 2. 合同

### 2.1 StepResult

所有 dogfood step 使用统一的 `StepResult` dataclass：

```python
@dataclass(frozen=True)
class StepResult:
    step_id: str           # e.g. "BL1-P2-01"
    description: str        # 人类可读的步骤描述
    status: str             # "pass" | "concern" | "fail" | "skipped"
    actual_summary: str     # 观察到的实际行为摘要
    expected: str           # 期望行为描述
    provider_mode: str      # "fake" | "real" | "none"
    detail: dict | None     # 补充信息（脱敏后）
```

### 2.2 Report Writer

```python
def write_dogfood_report(
    results: list[StepResult],
    output_path: Path,           # 必须是 tmp/ 或指定输出路径
    *,
    overwrite: bool = False,     # 默认不覆盖已有报告
) -> Path:
```

- 默认不覆盖已有 active report
- 输出到 tmp-root-first（`workspace/dogfood/` 或用户指定路径）
- 不直接写 `docs/dogfood/` 以避免覆盖人工报告

### 2.3 Redaction Helper

```python
def redact_secrets(text: str) -> str:
```

- 脱敏 `sk-ant-*`, `sk-*`, `Bearer *` pattern
- 不可逆——不会在 log 中出现 raw secret

### 2.4 Temp Workspace Helper

```python
@contextmanager
def temp_workspace(prefix: str = "dogfood_"):
```

- 创建临时 workspace 目录
- yield Path
- 自动清理（context manager exit）

## 3. Migration Strategy

只迁移 1 个低风险 dogfood script 到共享 helpers 证明可行。如迁移风险高，停在 contract + helper tests，不强制全量迁移。

## 4. Out of Scope

- 执行 dogfood
- 真实 API 调用
- 读取真实 sessions/runs/memory
- 全量重写所有 scripts
- 复杂 runner/orchestrator
