# Memory Phase 5 Dogfood 001

日期: 2026-05-12
extractor: llm (deepseek-v4-pro)
pipeline: LLM extraction → bridge → confirmation → filesystem store → recall

## 1. 使用命令

```
python dogfood_phase5.py
```

> 脚本内部调用 LLMMemoryExtractor → proposal_to_confirmation_request →
> resolve_and_store → FilesystemMemoryStore。与 `python main.py memory extract`
> 走完全相同的代码路径，差异仅在于用户输入由预编排的 choice map 提供。

## 2. Provider 加载状态

| 配置项 | 状态 |
|---|---|
| MODEL_NAME | loaded (deepseek-v4-pro) |
| API_KEY | loaded |
| BASE_URL | loaded (api.deepseek.com) |

provider loaded: True

## 3. 5 组 Case 结果

### Case 1: Semantic Memory

- Extractor: llm
- Total proposals: 3
- Confirmable: 3
- Summary: llm extractor (deepseek-v4-pro): 3 proposals from 6 messages

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 0 | semantic | 用户偏好代码中使用中文注释，保留英文变量名 | 6 | 1.00 | propose |
| 1 | procedural | 在建议用户提交代码时，应先提醒用户执行 git diff --stat 查看变更概览，然后用 git add -p 逐块审计，确认无误后再提交 | 8 | 1.00 | propose |
| 2 | semantic | 用户喜欢技术讨论用简体中文，但代码、命令、错误日志保留英文原文不翻译 | 7 | 1.00 | propose |

**用户选择**:
- [0] accept: ✅ stored
- [1] accept: ✅ stored
- [2] edit_and_accept: ✅ stored
  - edited: 用户偏好简体中文技术讨论，但代码/命令/错误日志保留英文原文不翻译

### Case 2: Procedural Memory

- Extractor: llm
- Total proposals: 2
- Confirmable: 2
- Summary: llm extractor (deepseek-v4-pro): 2 proposals from 6 messages

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 0 | semantic | 项目定位为学习型agent，要求用最简单方案，不为未来可能的需求预先加抽象层 | 7 | 0.90 | propose |
| 1 | procedural | 调试 bug 必须：先查日志和 checkpoint 实际数据，找到根因，再最小修复，不做表面 patch | 9 | 0.95 | propose |

**用户选择**:
- [0] accept: ✅ stored
- [1] accept: ✅ stored

### Case 3: Episodic Memory

- Extractor: llm
- Total proposals: 2
- Confirmable: 2
- Summary: llm extractor (deepseek-v4-pro): 2 proposals from 6 messages

| # | type | content 摘要 | importance | confidence | action |
|---|---|---|---|---|---|
| 0 | episodic | 五一前（4月28日）的PostgreSQL迁移事故：全表UPDATE缺少复合索引导致全表锁，迁移超时40分钟。 | 9 | 0.95 | auto_retain_candidate |
| 1 | procedural | 进行大规模PostgreSQL迁移时必须执行三步骤checklist：① 分批UPDATE（每批5000行）② 使用CONCURRENTLY创建索引 ③ 设置l | 10 | 0.95 | propose |

**用户选择**:
- [0] accept: ✅ stored
- [1] session_only: ❌ not stored

### Case 4: Negative (临时任务)

- Extractor: llm
- Total proposals: 0
- Confirmable: 0
- Summary: llm extractor (deepseek-v4-pro): 0 proposals from 6 messages

**用户选择**:
- (无 proposal 需要确认)

### Case 5: Secret (含 API key/token)

- Extractor: llm
- Total proposals: 0
- Confirmable: 0
- Summary: llm extractor (deepseek-v4-pro): 0 proposals from 6 messages

**用户选择**:
- (无 proposal 需要确认)

## 4. Proposal 分类合理性

- Case 1: ⚠️ 分类包含非 semantic: ['semantic', 'procedural', 'semantic']
- Case 2: 1/2 分类为 procedural
- Case 3: 1/2 分类为 episodic
- Case 4: ✅ 临时任务正确返回 0 proposals
- Case 5: 0 proposals (应 0，secret 被过滤)

## 5. Importance / Confidence 合理性

- case_1_semantic [0]: importance=6 confidence=1.00 ⚠️ confidence 过高
- case_1_semantic [1]: importance=8 confidence=1.00 ⚠️ confidence 过高
- case_1_semantic [2]: importance=7 confidence=1.00 ⚠️ confidence 过高
- case_3_episodic [1]: importance=10 confidence=0.95 ⚠️ importance 偏高

## 6. Confirmation 体验问题

- Case 3 episodic 使用了 session_only 选择，确认链正确：procedural checklists 标记为 session_only → 不写入长期 store
- Case 1 semantic 使用了 edit 选择，编辑后内容正确写入 store
- 所有 accept 的 proposal 正确写入了 filesystem store
- 所有 reject 的 proposal 未写入 store

## 7. Markdown Memory 可读性

- 生成 3 个 markdown 文件：
  - `episodic/2026-05-12.md`: ---\nid: "memory:fake:53614254a4b79faa"\nmemory_type: "episodic"\nscope: "user"\nsource_type: "llm_extraction"\napproval_status: "approved"\ncreated_at: "2026-05-12T08:37:38Z"\nupdated_at: "2026-05-12T08:37:...
  - `procedural/learned.md`: ---\nid: "memory:fake:b168b576587e8c68"\nmemory_type: "procedural"\nscope: "project"\nsource_type: "llm_extraction"\napproval_status: "approved"\ncreated_at: "2026-05-12T08:36:18Z"\nupdated_at: "2026-05-12T0...
  - `semantic/user_preferences.md`: ---\nid: "memory:fake:9dc4c36b8a21be4d"\nmemory_type: "semantic"\nscope: "user"\nsource_type: "llm_extraction"\napproval_status: "approved"\ncreated_at: "2026-05-12T08:36:18Z"\nupdated_at: "2026-05-12T08:36:...

## 8. Recall 是否有用

- store.list_records() 返回 6 条记录
- 所有写入的记录均可通过 recall API 读回
  - `memory:fake:53614254a4b79faa`: type=episodic scope=user
    content: 五一前（4月28日）的PostgreSQL迁移事故：全表UPDATE缺少复合索引导致全表锁，迁移超时40分钟。...
  - `memory:fake:5758981c9d727ce6`: type=semantic scope=user
    content: 项目定位为学习型agent，要求用最简单方案，不为未来可能的需求预先加抽象层...
  - `memory:fake:74788760917fd1ee`: type=procedural scope=project
    content: 调试 bug 必须：先查日志和 checkpoint 实际数据，找到根因，再最小修复，不做表面 patch...
  - `memory:fake:9dc4c36b8a21be4d`: type=semantic scope=user
    content: 用户偏好代码中使用中文注释，保留英文变量名...
  - `memory:fake:b168b576587e8c68`: type=procedural scope=project
    content: 在建议用户提交代码时，应先提醒用户执行 git diff --stat 查看变更概览，然后用 git add -p 逐块审计，确认无误后再提交...
  - `memory:fake:b594e9fc0dc7ee98`: type=semantic scope=user
    content: 用户偏好简体中文技术讨论，但代码/命令/错误日志保留英文原文不翻译...

## 9. P0 / P1 / P2

- **P2**: semantic case 中出现 procedural 分类

## 10. 是否建议修复，按优先级排序

- [P2] semantic case 中出现 procedural 分类
  - 建议: 检查该 proposal 的内容和 LLM 分类逻辑

---
报告生成时间: 2026-05-12T08:37:45.968974+00:00