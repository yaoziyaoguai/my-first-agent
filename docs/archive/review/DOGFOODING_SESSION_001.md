# Dogfooding Session 001 — 2026-05-11/12

## 1. 本轮 Usage Flows

| # | Flow | 执行 | 结果 |
|---|------|:--:|------|
| 1 | 显式 retain + recall | ✅ | semantic record 正确写入/读取 |
| 2 | L1 heuristic (4 rules) | ✅ | bug_fix_lesson / project_rule / architecture_decision 触发正确；repeated_preference ≥3次触发正确 |
| 3 | Suggestion → confirmation → store → snapshot | ✅ | procedural record 全链路 memory_type 正确 |
| 4 | Forget | ⚠️ | Decision 产出正确，但 source_summary 匹配失败导致未找到 record |
| 5 | Sensitivity blocking | ✅ | API key / password / token 关键词正确拒绝 |
| 6 | Prompt injection blocking | ✅ | "ignore previous instructions" 正确拒绝 |
| 7 | Filesystem inspection | ✅ | 目录结构正确：semantic/ + procedural/ + _meta/index.json |
| 8 | Manual markdown edit | ⚠️ | 可行但格式脆弱 — 分隔符必须是 `\n\n---\n\n` |
| 9 | Rebuild index | ✅ | 删除 index.json 后正确重建 |
| 10 | Duplicate detection | ⚠️ | suggestion engine 有去重，policy 显式路径无去重 |
| 11 | Frequency limiting | ✅ | ≤3/session 正确生效 |
| 12 | False-positive retention | ⚠️ | 3/4 L1 规则触发在无关内容上 |
| 13 | False-negative retention | ⚠️ | 5/5 有价值的隐式知识全部漏掉 |
| 14 | Recall quality | ⚠️ | 重复内容出现在 snapshot 中 |
| 15 | Memory growth | 📊 | 见下方数据 |
| 16 | Corruption recovery | ✅ | 轻微格式损坏不影响解析 |

---

## 2. Retain / Recall 行为

### 2.1 正常路径

- 显式 "记住 X" → policy RETAIN → confirmation → store → snapshot ✅
- L1 suggestion → engine candidate (带 metadata) → confirmation → store → snapshot ✅
- memory_type 全链路正确：semantic / episodic / procedural 各自 propagated ✅

### 2.2 异常路径

- **重复写入**：显式 "记住 X" 不检查已有 record，相同内容可写入两次，产生不同的 record ID
- **Forget 匹配失败**：forget 使用 `derive_memory_record_id(intent.source_summary)` 定位 record，但 source_summary 取决于原始输入文本，导致与已有 record 不匹配

---

## 3. 哪些体验好

1. **memory_type propagation (G1-G6)**：全链路打通，suggestion → intent → record → snapshot 类型一致
2. **Sensitivity / injection 阻断**：零误放，所有危险关键词正确拦截
3. **Frequency limiting**：第 4 次起静默跳过，不打搅用户
4. **Rebuild index**：删除 index.json 后自动重建，恢复正确
5. **recall() API**：支持 memory_type 过滤，语义清晰

---

## 4. 哪些体验差

1. **手动编辑 markdown 极易出错**：分隔符必须是 `\n\n---\n\n`，多一个少一个换行都会导致解析失败
2. **多 record 共享一个文件**：编辑一条时容易误伤同文件中的其他 record
3. **Snapshot 中出现重复内容**：同一事实以不同 ID 出现两次，降低 recall 质量
4. **Forget 功能不可靠**：用户说"忘记 Python"，但 source_summary 不匹配，record 删不掉

---

## 5. 哪些是 Bug

| # | Bug | 严重度 | 根因 |
|---|-----|:--:|------|
| B1 | 显式 retain 路径无去重 | P2 | `_apply_retain` 不检查 content 是否已存在 |
| B2 | Snapshot 展示重复 record | P2 | B1 的直接后果 |
| B3 | markdown 分隔符格式脆弱 | P2 | 分隔符与 frontmatter 起始标记共享 `---`，肉眼难区分 |

---

## 6. 哪些是 Architecture Issue

| # | Issue | 类别 |
|---|-------|------|
| A1 | L1 关键词匹配无语义理解 → 高 FP 率 | Extraction 设计局限 |
| A2 | 所有隐式知识 (不含 L1 关键词) 漏掉 → 高 FN 率 | Extraction 设计局限 |
| A3 | Forget 的 source_summary 匹配策略不可靠 | Store 设计 — 缺少 content-based lookup |
| A4 | 多条 record 共享一个文件的设计 | Store 格式 — 考虑 one-record-per-file 或更 robust 的分隔方案 |

---

## 7. 哪些是 Governance Issue

| # | Issue |
|---|-------|
| G1 | `project_rule` L1 规则将 "这个项目规定..." 直接标记为 `procedural`，不经过 procedural 五项判定标准检查 |
| G2 | DOGFOODING_GUIDE 中声称的 L1 规则在 `memory_policy.py`（实际在 `memory_suggestions.py`），文档模块引用不够精确 |

---

## 8. 哪些是 Future Work（Phase 5+）

| # | 内容 | 理由 |
|---|------|------|
| F1 | LLM-based extraction (L2) | 解决 FP/FN 问题 |
| F2 | Content-based dedup（不仅是 SHA256） | 解决 B1 |
| F3 | Forget 支持 content 匹配（不只是 source_summary） | 解决 A3 |
| F4 | One-record-per-file 或 JSONL 格式 | 解决 A4 |
| F5 | T2 auto-retain (episodic only) | 按 CANONICAL RFC 规划 |

---

## 9. 哪些绝对不该现在修

| # | 内容 | 理由 |
|---|------|------|
| ✗ | LLM extraction | Phase 5，禁止提前实现 |
| ✗ | Semantic dedup | 需要 embedding → 违反宪法禁止 |
| ✗ | T2 auto-retain | Phase 5，需 constitutional amendment 流程 |
| ✗ | One-record-per-file 重构 | 大范围格式变更，当前不是阻塞问题 |
| ✗ | L1 规则调优（加关键词） | 治标不治本，FP/FN 根因在缺乏语义理解 |

---

## 10. 下一轮 Dogfooding 建议

1. **真实多轮对话**：不止是 API 调用测试，而是在真实 agent conversation 中使用 retain/forget
2. **测试 session resume**：关闭 agent 后重新打开，验证 snapshot 质量
3. **测试 procedural over-retention**：刻意触发多次 project_rule，观察 procedural record 增长
4. **测试 200 条上限**：快速写入大量 record，观察上限行为
5. **测试并发写入风险**：虽然声称单进程，但验证实际是否有 race condition

---

## 附录: 当前 Memory Store 状态

```
Records: 4
  [semantic] 用户喜欢 Python 并且偏好类型安全的代码
  [semantic] 用户喜欢 Python 并且偏好类型安全的代码  ← 重复
  [procedural] 这个项目必须用 black 格式化所有 Python 代码
  [semantic] 用户偏好简洁的回答，不要冗长的解释

Files:
  semantic/user_preferences.md (2 records in 1 file)
  procedural/learned.md (1 record)
  _meta/index.json (auto-rebuilt)
```
