import json
from datetime import datetime, timedelta
from config import PROJECT_DIR
from agent.logger import log_event

MEMORY_DIR = PROJECT_DIR / "memory"
PROFILE_PATH = MEMORY_DIR / "profile.json"
EPISODES_DIR = MEMORY_DIR / "episodes"
RULES_DIR = MEMORY_DIR / "rules"

# 情景记忆保留天数
EPISODE_RETENTION_DAYS = 20


def init_memory():
    """初始化记忆目录结构"""
    MEMORY_DIR.mkdir(exist_ok=True)
    EPISODES_DIR.mkdir(exist_ok=True)
    RULES_DIR.mkdir(exist_ok=True)

    if not PROFILE_PATH.exists():
        default_profile = {
            "user": {},
            "preferences": {},
            "knowledge": [],
            "projects": {},
        }
        PROFILE_PATH.write_text(
            json.dumps(default_profile, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log_event("memory_initialized", {"path": str(MEMORY_DIR)})


def load_profile():
    """加载语义记忆"""
    if not PROFILE_PATH.exists():
        return {}
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log_event("memory_load_error", {"type": "profile", "error": str(e)})
        return {}


def load_rules():
    """加载程序性记忆（所有 rules/*.md 文件）"""
    rules = []
    if not RULES_DIR.exists():
        return rules
    for rule_file in sorted(RULES_DIR.glob("*.md")):
        try:
            content = rule_file.read_text(encoding="utf-8").strip()
            if content:
                rules.append({
                    "name": rule_file.stem,
                    "content": content,
                })
        except Exception as e:
            log_event("memory_load_error", {"type": "rule", "file": str(rule_file), "error": str(e)})
    return rules


def build_memory_section():
    """
    把语义记忆和程序性记忆组装成一段文本，
    追加到 system prompt 里。
    """
    parts = []

    # 语义记忆
    profile = load_profile()

    if profile.get("user"):
        user_info = profile["user"]
        user_parts = []
        if user_info.get("name"):
            user_parts.append(f"用户名: {user_info['name']}")
        if user_info.get("role"):
            user_parts.append(f"角色: {user_info['role']}")
        if user_info.get("tech_stack"):
            user_parts.append(f"技术栈: {', '.join(user_info['tech_stack'])}")
        if user_info.get("os"):
            user_parts.append(f"操作系统: {user_info['os']}")
        if user_parts:
            parts.append("[用户信息]\n" + "\n".join(user_parts))

    if profile.get("preferences"):
        pref_lines = [f"- {k}: {v}" for k, v in profile["preferences"].items()]
        if pref_lines:
            parts.append("[用户偏好]\n" + "\n".join(pref_lines))

    if profile.get("knowledge"):
        knowledge_lines = [
            f"- {item['fact']}（{item.get('reason', '')}）"
            for item in profile["knowledge"]
            if item.get("fact")
        ]
        if knowledge_lines:
            parts.append("[已知知识]\n" + "\n".join(knowledge_lines))

    if profile.get("projects"):
        project_lines = []
        for name, info in profile["projects"].items():
            desc = info.get("description", "")
            tech = ", ".join(info.get("tech_stack", []))
            project_lines.append(f"- {name}: {desc} ({tech})")
        if project_lines:
            parts.append("[项目信息]\n" + "\n".join(project_lines))

    # 程序性记忆
    rules = load_rules()
    if rules:
        rule_lines = [f"### {r['name']}\n{r['content']}" for r in rules]
        parts.append("[行为规则]\n" + "\n\n".join(rule_lines))

    if not parts:
        return ""

    return "\n\n".join(parts)


def search_episodes(query, max_results=3):
    """
    搜索情景记忆（简单关键词匹配）
    当用户提到"上次""之前""继续"等词时调用
    """
    if not EPISODES_DIR.exists():
        return []

    results = []

    # 分词（简单按空格和标点切分）
    keywords = set(query.lower().replace("，", " ").replace("。", " ").split())
    # 过滤掉太短的词
    keywords = {k for k in keywords if len(k) > 1}

    if not keywords:
        return []

    for episode_file in sorted(EPISODES_DIR.glob("*.jsonl"), reverse=True):
        try:
            for line in episode_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                episode = json.loads(line)
                summary = episode.get("summary", "").lower()
                tags = [t.lower() for t in episode.get("tags", [])]
                all_text = summary + " " + " ".join(tags)

                # 计算匹配度
                matches = sum(1 for k in keywords if k in all_text)
                if matches > 0:
                    results.append({
                        "score": matches,
                        "episode": episode,
                        "date": episode_file.stem,
                    })
        except Exception:
            continue

    # 按匹配度排序，返回前 N 条
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:max_results]


def save_episodes(episodes):
    """保存情景记忆（追加到今天的文件）"""
    today = datetime.now().strftime("%Y-%m-%d")
    episode_file = EPISODES_DIR / f"{today}.jsonl"

    try:
        with open(episode_file, "a", encoding="utf-8") as f:
            for episode in episodes:
                episode["timestamp"] = datetime.now().isoformat()
                f.write(json.dumps(episode, ensure_ascii=False) + "\n")
        log_event("episodes_saved", {"count": len(episodes), "file": str(episode_file)})
    except Exception as e:
        log_event("episodes_save_error", {"error": str(e)})


def update_profile(updates):
    """更新语义记忆"""
    profile = load_profile()

    # 合并 user 信息
    if "user" in updates:
        profile["user"].update(updates["user"])

    # 合并 preferences
    if "preferences" in updates:
        profile["preferences"].update(updates["preferences"])

    # 追加 knowledge（去重）
    if "knowledge" in updates:
        existing_facts = {k["fact"] for k in profile.get("knowledge", [])}
        for item in updates["knowledge"]:
            if item["fact"] not in existing_facts:
                profile["knowledge"].append(item)
                existing_facts.add(item["fact"])

    # 合并 projects
    if "projects" in updates:
        profile["projects"].update(updates["projects"])

    try:
        PROFILE_PATH.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log_event("profile_updated", {"updates": list(updates.keys())})
    except Exception as e:
        log_event("profile_update_error", {"error": str(e)})


def save_rule(name, content):
    """保存或更新一条程序性记忆"""
    rule_path = RULES_DIR / f"{name}.md"
    try:
        rule_path.write_text(content, encoding="utf-8")
        log_event("rule_saved", {"name": name})
    except Exception as e:
        log_event("rule_save_error", {"name": name, "error": str(e)})


def cleanup_old_episodes():
    """清理过期的情景记忆"""
    if not EPISODES_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=EPISODE_RETENTION_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    removed = 0
    for episode_file in EPISODES_DIR.glob("*.jsonl"):
        if episode_file.stem < cutoff_str:
            episode_file.unlink()
            removed += 1

    if removed:
        log_event("episodes_cleanup", {"removed": removed, "retention_days": EPISODE_RETENTION_DAYS})


def extract_memories_from_session(messages, client, model_name):
    """
    Session 结束时，用 LLM 从对话中提取三种记忆：
    - 情景记忆：关键事件摘要
    - 语义记忆：新学到的知识
    - 程序性记忆：新的行为规则
    """
    from agent.logger import make_serializable
    
    serializable = make_serializable(messages)
    # 截断过长的内容，只取最近的消息
    if len(serializable) > 20:
        serializable = serializable[-20:]
    
    conversation_text = json.dumps(serializable, ensure_ascii=False)
    # 防止太长
    if len(conversation_text) > 10000:
        conversation_text = conversation_text[:10000] + "\n...(已截断)"
    
    extract_prompt = """请从以下对话中提取有长期价值的信息，严格按 JSON 格式输出，不要有其他内容。

提取规则：
1. episodes：本次对话中的关键事件，重点关注：
   - 用户做了什么决策，怎么回应模型的建议
   - 任务的关键转折点（遇到问题、改变方向、做出选择）
   - 不要记录每一步的工具调用细节，只记事件级别的摘要
   每条带 summary 和 tags

2. knowledge：从对话中提取关于用户的长期偏好和决策习惯，重点关注：
   - 用户主动表达的观点和偏好（"我觉得..."、"我更偏向..."）
   - 用户在多个方案中的选择，以及选择的理由
   - 用户对建议的接受或拒绝
   - 用户反复提及或深入追问的话题
   - 用户有明显情绪反应的观点和决策
   - 尽量将具体行为抽象为习惯或模式
   不要提取：
   - 模型单方面的输出内容（代码细节、工具返回值、具体参数）
   - 没有经过用户确认或选择的信息
   - 一次性的任务细节
   每条带 fact、confidence（high/medium/low）和 reason（为什么提取这条）

3. rules：从对话中提炼可复用的行为模式，重点关注：
   - 用户多次纠正 Agent 的同一类行为（需要形成新规则）
   - 用户明确描述的操作流程（"遇到 X 应该先做 A 再做 B"）
   - 一个成功完成的复杂任务的步骤模式（可复用到类似任务）
   规则必须包含具体的操作步骤，不能只是一个观点
   每条带 name 和 content

4. 如果某个类别没有值得提取的内容，返回空列表

输出格式：
{"episodes": [{"summary": "...", "tags": ["..."]}], "knowledge": [{"fact": "...", "confidence": "high", "reason": "..."}], "rules": [{"name": "rule_name", "content": "规则内容"}]}

对话内容：
""" + conversation_text


    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": extract_prompt}],
        )
        
        result_text = ""
        for block in response.content:
            if block.type == "text":
                result_text = block.text
                break
        
        # 剥掉可能的 markdown 代码块
        clean_text = result_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1]
        if clean_text.endswith("```"):
            clean_text = clean_text.rsplit("```", 1)[0]
        clean_text = clean_text.strip()
        
        extracted = json.loads(clean_text)
        
        # 保存情景记忆
        episodes = extracted.get("episodes", [])
        if episodes:
            save_episodes(episodes)
            print(f"  [记忆] 提取了 {len(episodes)} 条情景记忆")
        
        # 更新语义记忆
        knowledge = extracted.get("knowledge", [])
        if knowledge:
            today = datetime.now().strftime("%Y-%m-%d")
            for item in knowledge:
                item["source"] = today
            update_profile({"knowledge": knowledge})
            print(f"  [记忆] 提取了 {len(knowledge)} 条新知识")
        
        # 保存程序性记忆
        rules = extracted.get("rules", [])
        if rules:
            for rule in rules:
                save_rule(rule["name"], rule["content"])
            print(f"  [记忆] 提取了 {len(rules)} 条行为规则")
        
        if not episodes and not knowledge and not rules:
            print("  [记忆] 本次对话无新的长期记忆")
        
        log_event("memory_extracted", {
            "episodes_count": len(episodes),
            "knowledge_count": len(knowledge),
            "rules_count": len(rules),
        })
        
    except Exception as e:
        print(f"  [记忆] 提取失败：{e}")
        log_event("memory_extract_error", {"error": str(e)})
