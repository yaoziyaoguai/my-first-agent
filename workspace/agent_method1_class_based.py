"""
Method 1: 基于类的重构 (Class-based Agent)

重构思路：
1. 将 Agent 组织为类，封装状态和行为
2. 使用配置对象管理参数（会话ID、路径等）
3. 将工具实现为类方法，工具描述动态生成
4. 添加中间件/钩子机制实现权限控制
5. 更好的错误处理和日志系统
"""

import os
import json
import datetime
import uuid
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional, Set
from dotenv import load_dotenv
import anthropic

load_dotenv()


# ============================================
# 配置数据类
# ============================================
@dataclass
class AgentConfig:
    """Agent 配置"""
    # API 设置
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    base_url: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL"))
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "claude-3-5-sonnet-latest"))
    max_tokens: int = 8192
    
    # 路径设置
    log_file: Path = Path("agent_log.jsonl")
    snapshot_dir: Path = Path("sessions")
    project_dir: Path = field(default_factory=lambda: Path.cwd().resolve())
    
    # 上下文管理
    max_messages: int = 10
    max_message_chars: int = 50000
    keep_recent_messages: int = 6  # 压缩时保留最近的消息数
    
    # 权限设置
    protected_extensions: Set[str] = field(default_factory=lambda: {".py"})
    
    # 日志设置
    enable_logging: bool = True
    log_to_console: bool = True


# ============================================
# 工具描述生成器
# ============================================
class ToolSchemaBuilder:
    """动态生成工具 schema"""
    
    @staticmethod
    def build_calculate_schema() -> Dict:
        return {
            "name": "calculate",
            "description": "计算一个数学表达式，支持基本数学运算(+,-,*,/,括号)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，例如 '2 + 3 * 4'"
                    }
                },
                "required": ["expression"]
            }
        }
    
    @staticmethod
    def build_read_file_schema() -> Dict:
        return {
            "name": "read_file",
            "description": "读取文件内容。大文件返回概览（前3000字符、函数/类目录）",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，可以是相对路径或绝对路径"
                    }
                },
                "required": ["path"]
            }
        }
    
    @staticmethod
    def build_read_file_lines_schema() -> Dict:
        return {
            "name": "read_file_lines",
            "description": "按行号范围读取文件内容，支持查看特定代码段",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "起始行号（从1开始）"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "结束行号（>= start_line）"
                    }
                },
                "required": ["path", "start_line", "end_line"]
            }
        }
    
    @staticmethod
    def build_write_file_schema() -> Dict:
        return {
            "name": "write_file",
            "description": "写入文件内容（自动备份原文件，自动创建目录）",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容"
                    }
                },
                "required": ["path", "content"]
            }
        }


# ============================================
# 日志系统
# ============================================
class Logger:
    """结构化日志系统"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.session_id = str(uuid.uuid4())
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        self.config.snapshot_dir.mkdir(exist_ok=True)
    
    def log(self, event_type: str, data: Dict):
        if not self.config.enable_logging:
            return
        
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "session_id": self.session_id,
            "event": event_type,
            "data": data,
        }
        
        with open(self.config.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        if self.config.log_to_console:
            print(f"[LOG] {event_type}: {data}")
    
    def save_snapshot(self, messages: List[Dict]):
        snapshot = {
            "session_id": self.session_id,
            "saved_at": datetime.datetime.now().isoformat(),
            "message_count": len(messages),
            "messages": self._make_serializable(messages),
        }
        snapshot_file = self.config.snapshot_dir / f"session_{self.session_id}.json"
        with open(snapshot_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        
        print(f"会话已保存到: {snapshot_file}")
    
    @staticmethod
    def _make_serializable(messages: List[Dict]) -> List[Dict]:
        result = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                new_content = []
                for block in msg["content"]:
                    if hasattr(block, "model_dump"):
                        new_content.append(block.model_dump())
                    else:
                        new_content.append(block)
                result.append({"role": msg["role"], "content": new_content})
            else:
                result.append(msg)
        return result


# ============================================
# 权限控制系统
# ============================================
class PermissionManager:
    """权限分级管理"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
    
    def is_protected_source(self, path: str) -> bool:
        try:
            file_path = Path(path).expanduser().resolve(strict=False)
            return (
                file_path.is_relative_to(self.config.project_dir)
                and file_path.suffix.lower() in self.config.protected_extensions
                and file_path.exists()
            )
        except Exception:
            return False
    
    def needs_confirmation(self, tool_name: str, tool_input: Dict) -> bool:
        if tool_name == "write_file":
            return True
        
        if tool_name in ("read_file", "read_file_lines"):
            file_path = Path(tool_input["path"]).resolve()
            return not file_path.is_relative_to(self.config.project_dir)
        
        if tool_name == "calculate":
            return False
        
        return True
    
    def confirm_action(self, tool_name: str, tool_input: Dict) -> bool:
        print(f"\n{'='*50}")
        print(f"⚠️ Agent 请求执行操作:")
        print(f"   工具: {tool_name}")
        print(f"   参数: {json.dumps(tool_input, ensure_ascii=False)}")
        print(f"{'='*50}")
        
        while True:
            choice = input("允许执行吗？(y/n): ").strip().lower()
            if choice == "y":
                return True
            elif choice == "n":
                return False
            print("请输入 y 或 n")


# ============================================
# 文件操作工具
# ============================================
class FileTools:
    """文件操作工具集"""
    
    @staticmethod
    def extract_python_outline(content: str) -> List[str]:
        outline = []
        lines = content.splitlines()
        
        for idx, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith("class "):
                name = stripped[6:].split("(", 1)[0].split(":", 1)[0].strip()
                outline.append(f"Line {idx}: class {name}")
            elif stripped.startswith("def "):
                name = stripped[4:].split("(", 1)[0].strip()
                outline.append(f"Line {idx}: def {name}")
        
        return outline
    
    @classmethod
    def read_file(cls, path: str) -> str:
        try:
            file_path = Path(path)
            if not file_path.exists():
                return f"错误：文件 '{path}' 不存在"
            
            content = file_path.read_text(encoding="utf-8")
            total_lines = len(content.splitlines())
            
            if len(content) <= 10000:
                return content
            
            preview = content[:3000]
            suffix = file_path.suffix.lower()
            
            if suffix == ".py":
                outline = cls.extract_python_outline(content)
                outline_text = "\n".join(outline[:200]) if outline else "(未识别到 class / def 定义)"
            else:
                outline_text = "(非Python文件，不提供目录)"
            
            return (
                f"[文件概览]\n"
                f"路径: {path}\n"
                f"总字符数: {len(content)}\n"
                f"总行数: {total_lines}\n\n"
                f"[开头预览（前 3000 字符）]\n{preview}\n\n"
                f"[文件结构目录]\n{outline_text}\n\n"
                f"[提示] 文件较大，请使用 read_file_lines 读取特定范围"
            )
        except Exception as e:
            return f"读取错误：{e}"
    
    @classmethod
    def read_file_lines(cls, path: str, start_line: int, end_line: int) -> str:
        try:
            file_path = Path(path)
            if not file_path.exists():
                return f"错误：文件 '{path}' 不存在"
            
            if start_line < 1 or end_line < 1:
                return "错误：行号必须 >= 1"
            
            if start_line > end_line:
                return "错误：start_line 不能大于 end_line"
            
            lines = file_path.read_text(encoding="utf-8").splitlines()
            total_lines = len(lines)
            
            if start_line > total_lines:
                return f"错误：start_line={start_line} 超出总行数 {total_lines}"
            
            actual_end = min(end_line, total_lines)
            selected = lines[start_line - 1:actual_end]
            
            numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line))
            
            return (
                f"[按行读取]\n"
                f"路径: {path}\n"
                f"范围: 第 {start_line} 行 - 第 {actual_end} 行\n"
                f"总行数: {total_lines}\n\n{numbered}"
            )
        except Exception as e:
            return f"读取错误：{e}"
    
    @classmethod
    def write_file(cls, path: str, content: str, config: AgentConfig) -> str:
        try:
            file_path = Path(path)
            
            backup_path = None
            if file_path.exists():
                backup_path = file_path.with_suffix(file_path.suffix + ".bak")
                backup_path.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
            
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            
            msg = f"成功写入 '{path}'"
            if backup_path:
                msg += f"（原文件已备份到 '{backup_path}'）"
            return msg
        except Exception as e:
            return f"写入错误：{e}"


# ============================================
# 计算工具
# ============================================
class CalcTools:
    """计算工具集"""
    
    ALLOWED_CHARS = set("0123456789+-*/.() ")
    
    @classmethod
    def calculate(cls, expression: str) -> str:
        try:
            if not all(c in cls.ALLOWED_CHARS for c in expression):
                return "错误：表达式包含不允许的字符"
            result = eval(expression)
            return str(result)
        except Exception as e:
            return f"计算错误：{e}"


# ============================================
# 上下文压缩器
# ============================================
class ContextCompressor:
    """上下文压缩管理"""
    
    def __init__(self, client: anthropic.Anthropic, config: AgentConfig):
        self.client = client
        self.config = config
        self.logger = Logger(config)
    
    def estimate_size(self, messages: List[Dict]) -> int:
        try:
            serializable = Logger._make_serializable(messages)
            return len(json.dumps(serializable, ensure_ascii=False))
        except Exception:
            return 0
    
    def _truncate_tool_results(self, obj: Any, threshold: int = 200, keep: int = 200) -> Any:
        if isinstance(obj, list):
            return [self._truncate_tool_results(item, threshold, keep) for item in obj]
        
        if isinstance(obj, dict):
            new_obj = {}
            is_tool_result = obj.get("type") == "tool_result"
            
            for k, v in obj.items():
                if is_tool_result and k == "content":
                    text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    new_obj[k] = text[:keep] + "...(已截断)" if len(text) > threshold else text
                else:
                    new_obj[k] = self._truncate_tool_results(v, threshold, keep)
            return new_obj
        
        return obj
    
    def compress(self, messages: List[Dict]) -> List[Dict]:
        total_size = self.estimate_size(messages)
        
        if len(messages) <= self.config.max_messages and total_size <= self.config.max_message_chars:
            return messages
        
        print(f"\n[系统] 上下文较长，正在压缩...（{len(messages)} 条, {total_size} 字符）")
        
        recent = messages[-self.config.keep_recent_messages:]
        old = messages[:-self.config.keep_recent_messages]
        
        old_for_summary = self._truncate_tool_results(
            Logger._make_serializable(old), threshold=200, keep=200
        )
        
        try:
            summary_response = self.client.messages.create(
                model=self.config.model_name,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        "请用中文简要总结以下对话历史的关键信息："
                        "完成了什么任务、重要的结论、用户的偏好。"
                        "只输出总结，不要多余的话。\n\n"
                        f"对话历史：\n{json.dumps(old_for_summary, ensure_ascii=False)}"
                    )
                }]
            )
            
            summary_text = ""
            for block in summary_response.content:
                if block.type == "text":
                    summary_text = block.text
                    break
            
            compressed = [
                {"role": "user", "content": f"[之前对话的摘要]\n{summary_text}"},
                {"role": "assistant", "content": "好的，我了解了之前的对话。请继续。"},
            ] + recent
            
            print(f"[系统] 压缩完成：{len(messages)} 条 → {len(compressed)} 条\n")
            return compressed
        
        except Exception as e:
            print(f"[警告] 压缩失败：{e}")
            return messages


# ============================================
# Agent 主类
# ============================================
class FileAgent:
    """文件操作 Agent"""
    
    SYSTEM_PROMPT = """你是一个有用的助手，能够进行数学计算和文件操作。
你可以读取文件来了解信息，也可以创建和编辑文件。
在操作文件时请谨慎，先告诉用户你打算做什么，再执行操作。

重要规则：
- 如果任务涉及创建多个文件，请逐个创建，每次只写一个文件，写完后询问用户是否继续下一个。
- 不要试图在一次回复中完成所有文件的创建。"""
    
    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.logger = Logger(self.config)
        self.permissions = PermissionManager(self.config)
        self.compressor = None  # 延迟初始化
        self.messages: List[Dict] = []
        
        # 初始化 Anthropic 客户端
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )
        self.compressor = ContextCompressor(self.client, self.config)
        
        # 工具注册表
        self.tools = self._build_tools()
        self.tool_handlers = self._build_tool_handlers()
        
        self.logger.log("session_start", {"system_prompt": self.SYSTEM_PROMPT})
    
    def _build_tools(self) -> List[Dict]:
        builder = ToolSchemaBuilder()
        return [
            builder.build_calculate_schema(),
            builder.build_read_file_schema(),
            builder.build_read_file_lines_schema(),
            builder.build_write_file_schema(),
        ]
    
    def _build_tool_handlers(self) -> Dict[str, Callable]:
        return {
            "calculate": lambda inp: CalcTools.calculate(inp["expression"]),
            "read_file": lambda inp: FileTools.read_file(inp["path"]),
            "read_file_lines": lambda inp: FileTools.read_file_lines(
                inp["path"], inp["start_line"], inp["end_line"]
            ),
            "write_file": lambda inp: FileTools.write_file(
                inp["path"], inp["content"], self.config
            ),
        }
    
    def _execute_tool(self, name: str, input_data: Dict) -> str:
        # 检查受保护文件
        if name == "write_file" and self.permissions.is_protected_source(input_data["path"]):
            self.logger.log("tool_blocked_protected", {"tool": name, "path": input_data["path"]})
            return f"拒绝执行：'{input_data['path']}' 是受保护源码文件"
        
        handler = self.tool_handlers.get(name)
        if not handler:
            return f"错误：未知工具 '{name}'"
        
        try:
            return handler(input_data)
        except Exception as e:
            return f"工具执行错误：{e}"
    
    def _handle_tool_result(self, tool_name: str, result: str) -> str:
        # 写入文件后添加系统指令
        if tool_name == "write_file" and not result.startswith(("拒绝", "错误", "写入错误")):
            result += "\n\n[系统指令] 文件已写入。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。"
        return result
    
    def chat(self, user_input: str) -> str:
        # 压缩上下文
        self.messages = self.compressor.compress(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        self.logger.log("user_input", {"content": user_input})
        
        while True:
            self.logger.log("llm_call", {"message_count": len(self.messages)})
            
            # 流式响应
            with self.client.messages.stream(
                model=self.config.model_name,
                max_tokens=self.config.max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=self.messages,
                tools=self.tools,
            ) as stream:
                for event in stream:
                    if hasattr(event, 'type') and event.type == 'content_block_start':
                        if hasattr(event.content_block, 'type') and event.content_block.type == 'tool_use':
                            print(f"\n🔧 正在规划工具调用...", flush=True)
                    if hasattr(event, 'type') and event.type == 'content_block_delta':
                        if hasattr(event.delta, 'text'):
                            print(event.delta.text, end="", flush=True)
            
                response = stream.get_final_message()
            
            print()
            self.logger.log("llm_response", {"stop_reason": response.stop_reason})
            
            # 正常结束
            if response.stop_reason == "end_turn":
                assistant_text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                self.messages.append({"role": "assistant", "content": response.content})
                self.logger.log("agent_reply", {"content": assistant_text})
                return assistant_text
            
            # 工具调用
            if response.stop_reason == "tool_use":
                self.messages.append({"role": "assistant", "content": response.content})
                
                for block in response.content:
                    if block.type == "tool_use":
                        self._process_tool_use(block)
                continue
            
            return f"意外的响应: {response.stop_reason}"
    
    def _process_tool_use(self, block):
        tool_name = block.name
        tool_input = block.input
        tool_use_id = block.id
        
        self.logger.log("tool_requested", {"tool": tool_name, "input": tool_input})
        
        # 受保护文件检查
        if tool_name == "write_file" and self.permissions.is_protected_source(tool_input["path"]):
            result = f"拒绝执行：'{tool_input['path']}' 是受保护源码文件"
            self.logger.log("tool_blocked", {"tool": tool_name, "path": tool_input["path"]})
            self.messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
            })
            return
        
        # 权限确认
        if self.permissions.needs_confirmation(tool_name, tool_input):
            approved = self.permissions.confirm_action(tool_name, tool_input)
        else:
            print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
            approved = True
        
        if approved:
            result = self._execute_tool(tool_name, tool_input)
            result = self._handle_tool_result(tool_name, result)
            self.logger.log("tool_executed", {"tool": tool_name, "result": result[:500]})
        else:
            result = "用户拒绝了此操作"
            self.logger.log("tool_rejected", {"tool": tool_name})
        
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
        })
    
    def run(self):
        """主循环"""
        print("=== Class-based Agent (Method 1) ===")
        print("基于类的重构版本。输入 'quit' 退出\n")
        
        while True:
            try:
                user_input = input("你: ")
                if user_input.strip().lower() == "quit":
                    self.logger.save_snapshot(self.messages)
                    print("再见！")
                    break
                reply = self.chat(user_input)
                print(f"\nAgent: {reply}\n")
            except KeyboardInterrupt:
                print("\n用户中断")
                break
            except Exception as e:
                print(f"错误: {e}")


# ============================================
# 入口
# ============================================
if __name__ == "__main__":
    agent = FileAgent()
    agent.run()
