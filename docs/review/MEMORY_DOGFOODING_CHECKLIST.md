# Memory Dogfooding Checklist

> 使用指南: 每个 dogfooding session 前过一遍 checklist，session 后逐项填写观察结果。
> 目标不是"全部通过"，而是**暴露真实问题**。

---

## 1. Episodic Retention Sanity

- [ ] L1 `bug_fix_lesson` 规则是否能被正常触发？
- [ ] 被 retained 的 episodic memory 确实描述了经验教训，而非一般性讨论？
- [ ] Episodic record 的时间线是否正确（按日期组织）？
- [ ] 同一天多条 episodic 是否合并/追加到同一文件？

**观察**:

| 日期 | 触发次数 | 错误触发 | 漏触发 | 备注 |
|------|:--:|:--:|:--:|------|
| | | | | |

---

## 2. Semantic Correctness

- [ ] 显式 "记住 X" 是否正确写入 semantic store？
- [ ] L1 `architecture_decision` 是否正确识别架构决策？
- [ ] L1 `repeated_preference` 是否在 ≥3 次后才触发？
- [ ] Semantic record 的内容是否与用户实际表达一致？
- [ ] 是否存在 semantic 记录被错误标记为其他类型？

**观察**:

| 日期 | 显式 retain 次数 | L1 arch_decision 触发 | L1 repeated_pref 触发 | 内容错误 | 备注 |
|------|:--:|:--:|:--:|:--:|------|
| | | | | | |

---

## 3. Procedural Safety

> **定义参照**：此处的 "Procedural" 遵循 MEMORY_CANONICAL_RFC.md §2.3 的定义——从真实交互中浮现的、经显式确认的行为约束，不完全等同于经典认知心理学的 implicit procedural memory（技能自动化）。检查时应以 RFC 的 5 条法定判定标准（§2.4）为准。

- [ ] 所有 procedural record 都经过 explicit confirmation？
- [ ] 所有 procedural record 确实来自真实交互，而非预写规则？
- [ ] 是否存在 coding rule 被误标为 procedural？
- [ ] 是否存在 general guideline 被误标为 procedural？
- [ ] Procedural record 数量是否合理？（不应快速增长）

**五项判定标准检查**（逐条 procedural record 核对，标准见 MEMORY_CANONICAL_RFC.md §2.4）:
1. 来自真实交互？ □  2. 经过显式确认？ □  3. 交互习得的行为适应？ □
4. NOT 可事先写好？ □  5. NOT 一般性行为指南？ □

**观察**:

| 日期 | Procedural 总数 | 误标数 | 误标内容 | 备注 |
|------|:--:|:--:|------|------|
| | | | | |

---

## 4. Recall Usefulness

- [ ] Session 开始时 Snapshot 注入的内容是否与当前任务相关？
- [ ] Snapshot 中的 memory 是否对 Agent 行为产生了实际影响？
- [ ] 是否存在 Snapshot 中有用但未被 recall 的内容？
- [ ] 是否存在 Snapshot 中无用但被 recall 的内容？
- [ ] Snapshot 的 5 条限制是否合理？（是否总是满 5 条？是否应该更多/更少？）

**观察**:

| 日期 | Snapshot 条数 | 有用条数 | 无用条数 | 缺失内容 | 备注 |
|------|:--:|:--:|:--:|------|------|
| | | | | | |

---

## 5. Memory Growth

- [ ] 总 record 数量趋势？（记录每次 session 后的数量）
- [ ] 各 memory_type 占比是否合理？
- [ ] 是否存在同一主题的 records 过多？
- [ ] 是否接近 200 条 active records 上限？

**观察**:

| 日期 | semantic | episodic | procedural | 总计 | 增长率 | 备注 |
|------|:--:|:--:|:--:|:--:|:--:|------|
| | | | | | | |

---

## 6. Duplicate Memories

- [ ] SHA256 去重是否正常工作？
- [ ] 是否存在语义重复但字符串不同的内容？（去重漏网）
- [ ] 是否存在同一事实以不同 memory_type 重复存储？

**观察**:

| 日期 | SHA256 去重命中 | 语义重复（漏网） | 跨类型重复 | 备注 |
|------|:--:|:--:|:--:|------|
| | | | | |

---

## 7. False-Positive Retention

- [ ] L1 规则是否将不应该 retain 的内容标记为候选？
- [ ] 是否有临时性讨论被误 retention？
- [ ] 是否有 sarcasm/玩笑被误 retention？
- [ ] 是否有上下文高度依赖的内容被 retention？（脱离上下文无意义）

**观察**:

| 日期 | 误 retention 内容 | 触发规则 | 为什么不该 retain | 备注 |
|------|------|------|------|------|
| | | | | |

---

## 8. False-Negative Retention

- [ ] 是否有明显应该 retain 但未被识别的内容？
- [ ] 用户是否曾需要手动重复某信息因为系统没记住？
- [ ] 是否存在不含 L1 关键词但有长期价值的内容被漏掉？

**观察**:

| 日期 | 漏 retention 内容 | 为什么应该 retain | 为什么漏掉 | 备注 |
|------|------|------|------|------|
| | | | | |

---

## 9. Session Annoyance

- [ ] Confirmation 弹出频率是否影响工作流？
- [ ] Confirmation 是否在 task 中途弹出（而非 task 边界）？
- [ ] 用户 REJECT 次数？（高 REJECT 率说明 L1 质量低）
- [ ] 用户选择 SESSION_ONLY 次数？（说明不信任长期 retain）
- [ ] 频率限制 (≤3/session) 是否合理？

**观察**:

| 日期 | Confirm 次数 | REJECT | SESSION_ONLY | EDIT | 备注 |
|------|:--:|:--:|:--:|:--:|------|
| | | | | | |

---

## 10. Manual Edit Ergonomics

- [ ] 手动编辑 `.md` 文件是否方便？
- [ ] 编辑后索引重建是否正常？
- [ ] 修改 memory_type 后是否正确生效？
- [ ] 手动删除某条 record 后是否完全清除？
- [ ] Frontmatter YAML 手动编辑是否有格式陷阱？

**观察**:

| 日期 | 编辑操作 | 是否成功 | 遇到的问题 | 备注 |
|------|------|:--:|------|------|
| | | | | |

---

## 11. Rebuild Index Recovery

- [ ] 删除 `index.json` 后重建是否完整？
- [ ] 重建后的 index 与 markdown 文件是否一致？
- [ ] 重建索引是否影响已有 memory 的 id / audit_id？
- [ ] 存在损坏 markdown 文件时重建是否 graceful 降级？

**观察**:

| 日期 | 重建前 records | 重建后 records | 差异 | 备注 |
|------|:--:|:--:|------|------|
| | | | | |

---

## 12. Memory Corruption Recovery

- [ ] 手动损坏一个 markdown 文件后系统行为？
- [ ] Frontmatter 格式错误时是否可恢复？
- [ ] Body 为空时是否可恢复？
- [ ] 重复 id 冲突时如何处理？
- [ ] 文件系统只读/权限问题时系统行为？

**观察**:

| 日期 | 损坏类型 | 系统行为 | 是否可恢复 | 备注 |
|------|------|------|:--:|------|
| | | | | |

---

## Session 汇总

| 日期 | P0 发现 | P1 发现 | P2 发现 | 总体评估 |
|------|------|------|------|------|
| | | | | |
