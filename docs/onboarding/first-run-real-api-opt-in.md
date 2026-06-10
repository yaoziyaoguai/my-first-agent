# First Run & Real API Opt-In Guide

**日期**: 2026-05-27
**对象**: 首次运行 First Agent 的用户

---

## 1. 首次运行（Fake Mode）

First Agent 的默认安全模式使用 FakeProvider，零配置、零 API key 即可运行：

```bash
python main.py
```

Fake mode 下的行为：
- 所有 LLM 响应使用 scripted/deterministic 输出
- 不调用任何外部 API
- 工具执行使用本地 mock
- 所有能力（tool/memory/subagent/skill）在 fake 下可用

### 验证你的环境

```bash
# 检查依赖
python main.py --health

# 跑 fake/local 测试
.venv/bin/python -m pytest tests/ -q
```

### 常见首次运行问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'xxx'` | 缺少依赖 | `pip install -r requirements.txt` |
| `config/config.yaml not found` | 缺少配置文件 | 从 `config/config.example.yaml` 复制 |
| `Permission denied` | 脚本无执行权限 | `chmod +x main.py` |
| `ruff` pre-commit 失败 | ruff 未安装 | `pip install ruff` |

---

## 2. 真实 API 模式（Opt-In）

如果你有 Anthropic API key 或兼容端点，可以 opt-in 真实 API 模式。

### 配置

编辑 `config/config.yaml`：

```yaml
provider:
  enabled: true
  type: anthropic_native    # 或 anthropic_compatible / openai_native / openai_compatible
  api_key: sk-REPLACE_ME  # 你的 API key（格式如 sk-ant-... 或 sk-or-...）
  model_name: claude-sonnet-4-6
```

### 支持的 provider 类型

| type | 说明 |
|------|------|
| `anthropic_native` | Anthropic 原生 API（api.anthropic.com） |
| `anthropic_compatible` | Anthropic 兼容端点（如 DashScope kimi-k2.5） |
| `openai_native` | OpenAI 原生 API |
| `openai_compatible` | OpenAI 兼容端点 |
| `fake` | 默认安全模式（不需要 API key） |

### 安全警告

**config/config.yaml 包含你的真实 API key，绝对不要 commit！**

- 文件已被 `git update-index --skip-worktree` 保护
- pre-commit hook 会扫描 staged diff 中的真实 key 特征

---

## 3. 从 Fake 到 Real 的迁移

当你从 fake mode 切换到 real API 时：

1. **行为一致**：fake 和 real 共享核心 runtime 路径（dispatcher、tool pipeline、memory、subagent）
2. **首次验证**：先用 `--health` 检查连接，再运行明确授权的 local/real-provider validation
3. **已知差异**：
   - Fake mode 的 scripted response 可能不覆盖所有边缘情况
   - Real LLM 的 tool selection 行为可能与 fake scripted 不完全一致
   - 技能选择（skill selection）在 real API 下行为可能不同（见 skill system 已知限制）

---

## 4. 参考

- 配置示例：`config/config.example.yaml`
- 项目状态：`docs/PROJECT_STATUS.md`
- 运行流程：`docs/dev/AUTO_RUN_WORKFLOW.md`
- 能力边界：`docs/CAPABILITY_BOUNDARIES.md`
