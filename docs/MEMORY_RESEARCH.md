# Stage 3 Memory Research Notes

This note records the public research inputs for Stage 3 Memory System
Discovery. It is an architecture reference, not an implementation plan by
itself. No source here is copied into production code; ideas are adapted to
`my-first-agent`'s local-first runtime boundaries.

## Research matrix

| Source | Core idea | Memory model | Adopt for `my-first-agent` | Do not adopt now | Risk | Relevance |
|---|---|---|---|---|---|---|
| [MemGPT paper, arXiv 2310.08560](https://arxiv.org/abs/2310.08560) | Treat limited LLM context as a virtual memory problem. Move information between fast context and slower external memory tiers; use interrupts to control flow when memory access is needed. | OS-inspired virtual context, hierarchical memory tiers, paging, long-session chat consistency. | Adopt the mental model that memory is **context governance**, not just storage. Add a future "memory interrupt" concept only after runtime lifecycle is ready. | Do not implement paging, autonomous interrupts, or model-driven memory tools in Stage 3 Slice 1. | If copied literally, it would force a runtime/control-flow rewrite and blur checkpoint vs memory. | Helps prevent a naive `memory.json` + prompt injection design. |
| [Letta agent memory guide](https://docs.letta.com/guides/agents/memory) | Stateful agents persist messages, reasoning, tool calls, memories, and important core memories; attached memories can be injected into context. | Stateful agent with memory blocks, message history, runs, steps, tools, and threads. | Adopt the distinction between "core memory shown in context" and "full history available out-of-context". | Do not let the agent autonomously edit long-term memory before First Agent has policy and approval. | Always-visible blocks can become stale prompt pollution or privacy leaks. | Useful as a reference for durable agent state, but First Agent should keep policy local. |
| [Letta memory blocks](https://docs.letta.com/guides/agents/memory-blocks) | Memory blocks are labeled, described, bounded context sections; some are read-only, some are shared, and attached blocks are always visible. | Label / description / value / limit blocks, optionally read-only and shared. | Adopt "description matters" and bounded approved snapshots. Use read-only/project policy records as a future idea. | Do not make all memories always visible; do not create shared blocks before scope/isolation exists. | Always-visible memory can overfit answers and leak personal/project data into unrelated tasks. | Inspires `MemorySnapshot` fields: scope, reason, omitted count, safety filter. |
| [LangChain/LangGraph memory concepts](https://docs.langchain.com/oss/python/concepts/memory) | Distinguish short-term thread-scoped state from long-term namespace-scoped stores; classify semantic, episodic, and procedural memory. | Short-term state/checkpointer, long-term store namespaces, memory types, hot-path vs background writes. | Adopt the boundary vocabulary: short-term, semantic, episodic, procedural, namespaces. Adopt "hot path vs background" as a design tradeoff. | Do not LangGraph-ify First Agent or treat checkpoint as long-term memory. Do not add stores/providers yet. | Namespaced store can become provider-first architecture if policy is skipped. | Directly maps to current `MemoryState` cleanup questions. |
| [MCP resources spec](https://modelcontextprotocol.io/docs/concepts/resources) | Servers expose URI-addressed resources; hosts decide how to list/read/select context; resources may include annotations like audience, priority, and lastModified. | Application-driven external context provider with list/read/subscribe and resource templates. | Treat MCP resources as a future **external memory provider input**, not internal memory. Adopt annotations as inspiration for snapshot metadata. | Do not implement MCP resources/prompts/sampling/roots in Stage 3. | A resource may be untrusted or stale; reading it is not consent to remember it. | Clarifies why MCP resources are not equivalent to MemoryPolicy. |
| [MCP prompts spec](https://modelcontextprotocol.io/docs/concepts/prompts) | Servers expose user-controlled prompt templates; clients retrieve prompt messages with arguments; implementations must validate against injection. | User-selected workflow templates, not memory records. | Future memory UX could use prompts as workflow templates for "review what to remember", but policy remains internal. | Do not store memory as MCP prompts or let external prompts decide retention. | Prompt templates can smuggle policy changes or unsafe resource use. | Helps separate Skills/prompts/procedures from personal/project memory. |
| [MCP tools spec](https://modelcontextprotocol.io/docs/concepts/tools) | Servers expose model-controlled tools with schemas; clients should confirm sensitive operations, validate results, and audit usage. | External action interface, optional structured/unstructured results and resource links. | External memory providers can expose tools later, but First Agent must keep confirmation/policy and map results through existing ToolResult contracts. | Do not put memory tools in base registry; do not bypass confirmation; do not let external provider write internal memory directly. | Tool output can contain prompt injection or sensitive data; tool errors must not become trusted memory. | Reinforces current MCP explicit opt-in and ToolResult legacy boundary. |
| Common provider/store patterns | Stores include JSON, SQLite, namespaced KV, document stores, event logs, vector stores, and hybrid retrieval. | Storage/retrieval backend, often separate from policy. | Stage 3 should design `MemoryStore` and `MemoryProvider` seams before choosing storage. Event-log audit and namespaced records are good future primitives. | Do not add SQLite/vector DB/RAG now. Do not equate provider availability with permission to remember. | Premature provider choice can dominate architecture and create migration/privacy debt. | Keeps local-first fallback and external provider adapters possible. |

## Architecture takeaways

1. **Memory is policy before storage.** All reviewed systems need some way to
   decide what becomes durable context. For First Agent, that decision must be
   explicit and local.
2. **Thread/checkpoint state is not long-term memory.** LangGraph's short-term
   checkpointer is useful vocabulary, but First Agent already has checkpoint
   recovery; Stage 3 must not overload it.
3. **Always-visible context is dangerous by default.** Letta-style blocks are
   powerful, but First Agent should only inject an approved `MemorySnapshot`
   selected for the current task.
4. **External context is not internal memory.** MCP resources/tools/prompts can
   supply candidates or workflows later; they must not decide retention,
   recall, or forgetting.
5. **Forget and provenance are first-class.** A memory system without origin,
   approval, freshness, conflict, and deletion semantics is just a hidden log.

## Adopted vocabulary for Stage 3

- **Short-term memory**: current thread/session working context and summary.
- **Checkpoint**: crash/resume state for runtime recovery.
- **Context compression**: summarization of the current conversation to fit a
  context budget.
- **Long-term memory**: approved, scoped, updateable, forgettable records that
  can cross sessions.
- **Memory provider**: a source of memory candidates/snapshots, internal or
  external.
- **Memory policy**: the local decision layer that can retain, recall, update,
  forget, reject, no-op, or ask for clarification.

