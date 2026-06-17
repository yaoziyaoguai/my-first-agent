# Graphify Queries — Independent S1 Priority Audit (2026-06-16 run 3)

> 中间产物（非权威）。记录本轮 Graphify 定向查询与用途；结论一律回源码/`git` 核验。

| # | 查询 | 用途 | 命中节点（已回核） |
|---|---|---|---|
| 1 | `graphify query "main entry chain main.py main_loop _run_chat_for_backend core.chat"` | 核验 G-01 入口链 | `main()@main.py:637`、`main_loop()@main.py:335`、`chat()@agent/core.py:763`、`record_evidence()@evidence_recorder.py:728`、`try_resume_from_checkpoint()@session.py:405`、`EventLogWriter@event_log.py:153`、`load_checkpoint()@checkpoint.py:466` |
| 2 | `graphify query "provider factory protocol fake real same spine loop provider_type"` | 核验 G-04/G-05 provider 边界 | `ModelProvider@agent/provider/protocol.py:78`、`factory.py`、`protocol.py`、`dispatcher.py`、`test_provider_contract.py` |

## 说明

- Graphify 仅用于**定位事实**，不作为最终证据；所有 load-bearing 结论用 `git`/`sed`/`grep` 回核（见 `code_evidence_index.md`）。
- 本轮以「核验上一轮 gap 的 file:line 是否仍成立」为主，而非重新发现架构。graphify 命中的 protocol.py:78 / evidence_recorder.py:728 / session.py:405 与 gap 文档引用一致（gap 文档写 protocol.py:77，相邻定义行，等同）。
