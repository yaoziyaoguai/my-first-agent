# Runtime v0.3 M3 · Skill 体系坦诚化（Skill System Status）

> 本文件目的：**诚实**记录当前 Skill 子系统的真实能力、明确不该被高估的部分，
> 并为后续真正的 Skill 化设计留下基线。**M3 不实现 Skill runtime**，只做状态
> 澄清和用户预期降级。

---

## 1. 当前 Skill 子系统真实能力（事实清单）

### 1.1 已经存在 ✅
- `agent/skills/registry.py` — 模块级单例 `SkillRegistry`，启动时扫描
  `skills/*/SKILL.md`。
- `agent/skills/parser.py` — 解析 SKILL.md frontmatter（`name` /
  `description` / `metadata`）。
- `agent/skills/safety.py` — 在加载时做基础 prompt-injection 检测，
  `rejected` 的 skill 不进入 registry，`warning` 的会进 registry 但记录告警。
- `agent/skills/loader.py::format_skill_for_model` — 把已加载 skill 的 body
  格式化成模型可读文本。
- `agent/prompt_builder.py` — 把 `name + description` 列表注入 system prompt
  的「## 可用 Skills」段。
- `agent/tools/skill.py` — `load_skill(name)` 工具，模型显式调用后返回完整
  SKILL.md body。
- `agent/tools/install_skill.py` / `update_skill.py` — 写文件后调
  `reload_registry()`。

### 1.2 看起来像、但其实不存在的能力 ❌
- ❌ **slash command `/reload_skills` 没有 handler**。v0.2 启动屏曾印
  `输入 'quit' 退出，'/reload_skills' 重新加载 skill`，但主循环里**根本没有
  `/` 解析逻辑**——这行字符串纯粹是误导。**v0.3 M3 已删除该提示**，并在
  本 doc 第 4 节登记，避免后来读 README 的人误以为 slash command 还活着。
- ❌ Skill 不是独立 runtime：本质就是「prompt + 文本 body 注入」。
- ❌ 没有 sub-agent / 子进程 / 隔离执行环境。
- ❌ 没有 skill 级别的 tool 权限白名单（skill body 能让模型调用任何已注册工具）。
- ❌ 没有 skill activation policy / lazy loading 策略（只有「模型自己选择是否调
  `load_skill`」）。
- ❌ 没有 skill 单元测试（`tests/` 下没有 `test_skill_*.py`）。
- ❌ 没有 skill 版本管理 / 升级路径 / 远端 skill 加载。
- ❌ 没有 skill marketplace。

### 1.3 仓库里实际存在的 skill
| 目录 | 用途 | 评级 |
|---|---|---|
| `skills/blog-writing/SKILL.md` | 4 行风格指南 demo | demo-level |
| `skills/evil-skill/SKILL.md` | 含 prompt injection，专门用来跑 safety 拒绝路径 | 故意保留的反例 |

**没有任何「生产级」skill**。当前 skill 子系统是**研究/实验性脚手架**。

---

## 2. v0.3 M3 改了什么（不改运行时，只改文案 + 文档）

| 文件 | 改动 |
|---|---|
| `agent/cli_renderer.py` | 启动屏移除 `'/reload_skills' 重新加载 skill`，改为「Skill 是实验性能力（详见 docs/V0_3_SKILL_SYSTEM_STATUS.md）」 |
| `tests/test_cli_renderer.py` | 断言启动文案不再印 `/reload_skills`，且必须出现「实验性」三个字 |
| `tests/test_skill_system_honesty.py` | 新增：守护 README / 启动文案 / commands 不再暗示成熟 Skill；空 skills/ 时 registry 优雅降级 |
| `docs/V0_3_PLANNING.md` | M3 标 ✅，明确 M3 = 状态澄清，不是 Skill runtime 实现 |
| `README.md` | v0.3 段补 Skill 实验性声明 |

**没有改的**（M3 严格自律）：
- `agent/skills/registry.py / parser.py / safety.py / loader.py / installer.py`
- `agent/tools/skill.py / install_skill.py / update_skill.py`
- `agent/prompt_builder.py` 的 skills section 注入逻辑
- `agent/core.py` 主循环
- v0.2 已锁的工具结局四分类、checkpoint、safety 边界

---

## 3. 显式非目标（M3 一律不做）

- ❌ 实现真正的 slash command 解析器（slash command 在 v0.1 已经下线，本轮不复活）
- ❌ 实现 skill activation / lazy loading
- ❌ 实现 skill 级 tool 权限白名单
- ❌ 实现 sub-agent 触发 skill
- ❌ 写 skill marketplace / 远端加载
- ❌ 把 evil-skill 删掉（它是 safety 测试样本，应该留）
- ❌ 在 init_session 里默认 print 整张 skill 列表（避免刷屏）

---

## 4. 后续真正 Skill 化需要做的事（推迟到 v0.3 M3.next 或 v0.4）

下面列出**未来真要把 Skill 做成产品级能力**时需要的最小事项，作为后续 milestone
的输入；本轮只登记，不实现：

1. **Skill metadata 契约固化**
   - frontmatter schema 用 jsonschema/pydantic 校验
   - 引入 `requires_tools: [...]` / `forbidden_tools: [...]` 字段
2. **Skill 级 tool 权限边界**
   - 在 `load_skill` 后，对接下来若干轮 tool call 做白名单/黑名单检查
   - 跨 skill 调用时强制重新 `load_skill`
3. **Skill activation policy**
   - 由 prompt 里 `name + description` 注入升级为「按 user goal 关键词匹配触发」
   - 但**不引入 LLM judge / Reflect**，匹配规则保持显式
4. **Skill 单元测试**
   - 每个 skill 至少一条 happy-path 测试
   - safety 测试覆盖 evil-skill 拒绝路径（部分已被 registry 测试隐式覆盖，
     但应显式化）
5. **Skill 文档**
   - 新增 `docs/SKILL_AUTHORING.md`，写清楚怎么写一个安全的 SKILL.md
6. **与 sub-agent 的明确划界**
   - sub-agent 是「另一个 LLM 上下文 + 自己的 tool registry」
   - skill 是「同一个 LLM 上下文里的指令包」
   - 两者**不要混淆**；sub-agent 在本 Runtime 路线图里不在 v0.3 范围

---

## 5. 给读者的一句话总结

> **当前的 Skill 是 prompt 注入级别的实验性脚手架，不是成熟的能力子系统。**
> 你可以用它做小型风格指南、写作模板这种 prompt-only 的复用，但**不要**指望
> 它做权限隔离、sub-agent 执行、自动激活。真正的 Skill runtime 是 v0.3 M3
> 之后的工作。
