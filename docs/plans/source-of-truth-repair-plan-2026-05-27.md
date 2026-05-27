# Source-of-Truth Repair Plan

**日期**: 2026-05-27
**基于**: `docs/audit/global-readonly-audit-2026-05-27.md` 审计发现
**状态**: in_progress

## 背景

2026-05-27 全局只读审计发现 3 个 P1：

1. `config/config.yaml` tracked dirty / 本地真实 key 配置安全边界不清
2. active docs 仍有当前状态冲突（root README、CURRENT_CAPABILITY_STATUS、CURRENT_AUDIT_STATUS、TEST_MATRIX、config-legacy-sunset-contract、archive/README）
3. latest real API dogfood evidence 口径过乐观（19 PASS / 1 CONCERN 被描述得过于确定）

## 执行项（按优先级）

### 1. Config safety boundary [P1]

**问题**: `config/config.yaml` tracked 且 dirty，含用户本地真实 key。`git status -sb` 明确显示 `M config/config.yaml`。

**修复**:
- 不动 config/config.yaml 内容（含真实 key）
- 更新 PROJECT_STATUS 明确: config/config.yaml 当前可能是用户本地真实配置，auto-run 不得 commit
- 确保 .gitignore 覆盖所有敏感文件
- 检查 config/config.example.yaml 是否可作为安全模板

### 2. Source-of-truth repair [P1]

**问题**: 6 个 active docs 与 PROJECT_STATUS 冲突或内容过期。

**修复目标文件**:

| 文件 | 问题 | 修复 |
|------|------|------|
| root README.md | 旧状态 (2026-05-25)、DeepSeek 401、.env 推荐、manual dogfood 优先级、broken links | 重写为 PROJECT_STATUS 指针 |
| CURRENT_CAPABILITY_STATUS.zh.md | 声称 real provider 不可用 (401) | 更新为 post-dogfood 状态 |
| CURRENT_AUDIT_STATUS.zh.md | Cleanup-Only / DeepSeek 401 / manual dogfood | 更新为当前审计结论 |
| TEST_MATRIX.zh.md | 过期基线数字、过期 dogfood 结果 | 更新数字和注释 |
| config-legacy-sunset-contract.md | 仍推荐 .env、api_key_env | 更新为 inline key 优先 |
| archive/README.md | 过期路径引用 | 更新为当前 archive 结构 |

### 3. Dogfood evidence wording hardening [P1]

**问题**: 19 PASS / 1 CONCERN 被描述为 finished，但多数 case 是 direct provider smoke。

**修复**:
- PROJECT_STATUS 中明确 evidence level: REAL_DOGFOOD_SMOKE
- 标注缺失覆盖（交互式 y/n、resume、tool confirmation 等）
- dogfood/README.md 添加 evidence 限制说明

### 4. Guard tests [P2]

**问题**: source-of-truth tests 未覆盖 root README 和所有 active docs。

**修复**:
- 扩展 test_docs_source_of_truth.py
- 覆盖: root README 引用 PROJECT_STATUS、不再推荐 .env 为主路径、不指向过期 audit/plan links
- 不推荐 legacy provider/profile/env/request_path/api_key_env

### 5. Deferred: Interactive dogfood harness [P2]

不在本轮执行。需要 subprocess stdin/stdout harness，覆盖 y/n、resume、interrupt、tool/memory confirmation。

## 不在此计划中

- 真实 API 调用
- Runtime 行为修改
- Provider 新功能
- Provider identity / "我是 Claude"
- 大规模代码重构
