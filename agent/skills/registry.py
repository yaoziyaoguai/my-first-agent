# agent/skills/registry.py
"""Skill 注册表：管理项目里所有可用 skill 的清单。

启动时扫描 skills/ 目录，对每个 skill 做 parse + safety 检查，
通过的存入内存字典，供后续查询。
"""

from pathlib import Path
from typing import Optional

from agent.skills.parser import parse_skill_file, SkillParseError
from agent.skills.safety import check_skill_safety


# 默认 skill 根目录（相对项目根）
DEFAULT_SKILLS_DIR = Path("skills")


class SkillRegistry:
    """管理所有已加载的 skill。"""
    
    def __init__(self, skills_dir: Path = DEFAULT_SKILLS_DIR):
        self.skills_dir = Path(skills_dir)
        self._skills: dict = {}  # {name: skill_data}
        self._warnings: list = []  # 加载过程中的警告信息
    
    def discover_skills(self) -> None:
        """扫描 skills_dir，加载所有合法的 skill。
        
        - 解析失败的 skill：跳过，记录警告
        - 安全检查 rejected 的 skill：跳过，记录警告
        - 安全检查 warning 的 skill：加载但记录警告
        - 通过的 skill：存入 self._skills
        """
        # 清空旧数据（支持 reload）
        self._skills = {}
        self._warnings = []
        
        if not self.skills_dir.is_dir():
            # 目录不存在是正常情况（新项目还没创建）
            return
        
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue  # 跳过文件，只处理目录
            
            if skill_dir.name.startswith("."):
                continue  # 跳过隐藏目录
            
            self._load_one_skill(skill_dir)
    
    def _load_one_skill(self, skill_dir: Path) -> None:
        """加载单个 skill。出错不抛异常，记录警告。"""
        # 1. 解析
        try:
            skill_data = parse_skill_file(skill_dir)
        except SkillParseError as e:
            self._warnings.append(
                f"[跳过] skill '{skill_dir.name}' 解析失败：{e}"
            )
            return
        
        # 2. 安全检查
        safety_result = check_skill_safety(skill_dir, skill_data)
        
        if safety_result["level"] == "rejected":
            issues_text = "; ".join(
                f"{issue['location']}: {issue['reason']}"
                for issue in safety_result["issues"]
                if issue["severity"] == "rejected"
            )
            self._warnings.append(
                f"[拒绝] skill '{skill_data['name']}' 被安全检查拒绝：{issues_text}"
            )
            return
        
        if safety_result["level"] == "warning":
            issues_text = "; ".join(
                f"{issue['location']}: {issue['reason']}"
                for issue in safety_result["issues"]
            )
            self._warnings.append(
                f"[警告] skill '{skill_data['name']}' 有可疑内容：{issues_text}"
            )
            # warning 不拒绝，继续加载
        
        # 3. 存入字典
        self._skills[skill_data["name"]] = skill_data
    
    def list_skills(self) -> list:
        """列出所有 skill 的 name 和 description。
        
        用于注入 system prompt。只返回元数据，不含 body。
        """
        return [
            {"name": s["name"], "description": s["description"]}
            for s in self._skills.values()
        ]
    
    def get_skill(self, name: str) -> Optional[dict]:
        """按名字查一个完整的 skill 数据。
        
        找不到返回 None。
        """
        return self._skills.get(name)
    
    def reload(self) -> None:
        """重新扫描 skills_dir。用于运行时添加/修改 skill 后刷新。"""
        self.discover_skills()
    
    def get_warnings(self) -> list:
        """返回加载过程中累积的警告信息。"""
        return list(self._warnings)
    
    def count(self) -> int:
        """已加载的 skill 数量。"""
        return len(self._skills)


# 模块级单例（整个 Agent 共用一份 Registry）
_registry: Optional[SkillRegistry] = None


def get_registry() -> SkillRegistry:
    """获取全局 registry 单例。首次调用时自动扫描。"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.discover_skills()
    return _registry


def reload_registry() -> SkillRegistry:
    """强制重新扫描。"""
    global _registry
    _registry = SkillRegistry()
    _registry.discover_skills()
    return _registry


def build_skills_section() -> str:
    """生成 skills 在 system prompt 里的段落。"""
    registry = get_registry()
    skills = registry.list_skills()
    if not skills:
        return ""
    
    lines = ["## 可用 Skills", 
             "以下是你可以调用的专业能力包。需要时用 load_skill 工具加载：", 
             ""]
    for s in skills:
        lines.append(f"- **{s['name']}**: {s['description']}")
    
    return "\n".join(lines)
