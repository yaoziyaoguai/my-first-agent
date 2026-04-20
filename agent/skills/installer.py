# agent/skills/installer.py
"""Skill 安装器：从 GitHub 下载 skill 到本地 skills/ 目录。

Stage 2 只支持：GitHub 单个 skill 的 URL
  例：https://github.com/anthropics/skills/tree/main/pdf
"""

import re
import shutil
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from agent.skills.parser import parse_skill_file, SkillParseError
from agent.skills.safety import check_skill_safety
from agent.skills.registry import DEFAULT_SKILLS_DIR


class SkillInstallError(Exception):
    """Skill 安装失败"""
    pass


# GitHub URL 解析正则：匹配 /<owner>/<repo>/tree/<branch>/<path>
GITHUB_TREE_URL = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+?)/?$"
)


def install_from_github(url: str, skills_dir: Path = DEFAULT_SKILLS_DIR) -> dict:
    """从 GitHub URL 安装一个 skill。
    
    Args:
        url: GitHub skill 子目录的 URL
             例：https://github.com/anthropics/skills/tree/main/pdf
        skills_dir: 本地 skills 目录（默认 skills/）
    
    Returns:
        {
            "success": bool,
            "skill_name": str,
            "skill_path": str,
            "safety_warnings": list,  # 如果 safety 有 warning
            "error": str,             # 失败时的原因
        }
    """
    # 1. 解析 URL
    parsed = _parse_github_url(url)
    if parsed is None:
        return {
            "success": False,
            "error": "不支持的 URL 格式。当前只支持 GitHub tree URL：\n"
                     "  https://github.com/<owner>/<repo>/tree/<branch>/<skill-name>",
        }
    
    owner, repo, branch, subpath = parsed
    skill_name = subpath.split("/")[-1]  # 取路径最后一段作为 skill 名
    
    # 2. 检查目标是否已存在
    target_dir = skills_dir / skill_name
    if target_dir.exists():
        return {
            "success": False,
            "skill_name": skill_name,
            "error": f"skill '{skill_name}' 已存在。如要覆盖请先手动删除 {target_dir}",
        }
    
    # 3. 用临时目录克隆仓库
    with tempfile.TemporaryDirectory() as tmp_root:
        tmp_path = Path(tmp_root)
        repo_clone_dir = tmp_path / "repo"
        
        clone_result = _git_clone_shallow(
            repo_url=f"https://github.com/{owner}/{repo}.git",
            branch=branch,
            target=repo_clone_dir,
        )
        if not clone_result["success"]:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"git clone 失败：{clone_result['error']}",
            }
        
        # 4. 定位 skill 子目录
        source_skill_dir = repo_clone_dir / subpath
        if not source_skill_dir.is_dir():
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"仓库里找不到路径 '{subpath}'",
            }
        
        # 5. 验证是合法 skill（有 SKILL.md）
        if not (source_skill_dir / "SKILL.md").is_file():
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"目录 '{subpath}' 下没有 SKILL.md，不是合法 skill",
            }
        
        # 6. 复制到本地（先复制到临时位置验证）
        staging_dir = tmp_path / "staging" / skill_name
        staging_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill_dir, staging_dir)
        
        # 7. Parser 验证格式
        try:
            skill_data = parse_skill_file(staging_dir)
        except SkillParseError as e:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"skill 格式错误：{e}",
            }
        
        # 8. Safety 扫描
        safety_result = check_skill_safety(staging_dir, skill_data)
        
        if safety_result["level"] == "rejected":
            issues = "; ".join(
                f"{i['location']}: {i['reason']}"
                for i in safety_result["issues"]
                if i["severity"] == "rejected"
            )
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"安全检查拒绝：{issues}",
            }
        
        # 9. 检查通过，正式移到 skills/ 目录
        skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging_dir, target_dir)
        # 9.5. 写入 install metadata（供以后 update 用）
        from datetime import datetime
        import json

        install_meta = {
            "source": url,
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "subpath": subpath,
            "installed_at": datetime.now().isoformat(),
        }
        meta_file = target_dir / ".install.json"
        meta_file.write_text(json.dumps(install_meta, indent=2, ensure_ascii=False))
            
    # 10. 返回结果（包括 warning）
    warnings = []
    if safety_result["level"] == "warning":
        warnings = [
            f"{i['location']}: {i['reason']}"
            for i in safety_result["issues"]
        ]
    
    return {
        "success": True,
        "skill_name": skill_data["name"],
        "skill_path": str(target_dir),
        "safety_warnings": warnings,
    }


# ========== 辅助函数 ==========

def _parse_github_url(url: str) -> Optional[tuple]:
    """解析 GitHub tree URL，返回 (owner, repo, branch, subpath) 或 None"""
    match = GITHUB_TREE_URL.match(url.strip())
    if not match:
        return None
    return match.groups()


def _git_clone_shallow(repo_url: str, branch: str, target: Path) -> dict:
    """浅克隆一个仓库的指定分支。
    
    --depth=1 只拉最新提交，减少下载量。
    --sparse 不 checkout 所有文件（后面会用 sparse-checkout 指定）。
    
    实际实现先用简单版：直接浅克隆整个分支。
    """
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr.strip() or "未知错误",
            }
        return {"success": True}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "git clone 超时（60秒）"}
    except FileNotFoundError:
        return {"success": False, "error": "未找到 git 命令，请先安装 git"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_skill(skill_name: str, skills_dir: Path = DEFAULT_SKILLS_DIR) -> dict:
    """更新一个已安装的 skill（重新下载覆盖）。
    
    通过读 .install.json 拿到原始 URL，重新安装。
    """
    target_dir = skills_dir / skill_name
    meta_file = target_dir / ".install.json"
    
    # 1. 检查是不是通过 Installer 装的
    if not meta_file.is_file():
        return {
            "success": False,
            "error": f"skill '{skill_name}' 没有 .install.json，"
                     f"无法自动更新（可能是手动创建的本地 skill）",
        }
    
    try:
        install_meta = json.loads(meta_file.read_text())
    except Exception as e:
        return {
            "success": False,
            "error": f".install.json 损坏：{e}",
        }
    
    original_url = install_meta.get("source")
    if not original_url:
        return {
            "success": False,
            "error": ".install.json 缺少 source 字段",
        }
    
    # 2. 备份旧版本到临时目录（失败可回滚）
    with tempfile.TemporaryDirectory() as tmp_root:
        backup_dir = Path(tmp_root) / "backup"
        shutil.copytree(target_dir, backup_dir)
        
        # 3. 删除旧版本
        shutil.rmtree(target_dir)
        
        # 4. 重新安装
        result = install_from_github(original_url, skills_dir)
        
        if not result["success"]:
            # 安装失败，回滚
            shutil.copytree(backup_dir, target_dir)
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"更新失败，已回滚到旧版本：{result['error']}",
            }
    
    return {
        "success": True,
        "skill_name": skill_name,
        "message": f"skill '{skill_name}' 已更新",
        "safety_warnings": result.get("safety_warnings", []),
    }