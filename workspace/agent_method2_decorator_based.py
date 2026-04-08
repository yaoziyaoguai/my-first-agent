"""
Method 2: 基于装饰器的工具注册 (Decorator-based Agent)

重构思路：
1. 使用装饰器自动注册工具函数
2. 动态生成工具描述，无需手动维护 tools 列表
3. 支持装饰器参数配置工具元数据
4. 中间件装饰器实现权限控制、日志、重试等
5. 更灵活的插件式架构
"""

import os
import json
import datetime
import uuid
import functools
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional, Set
from dataclasses import dataclass, field
from dotenv import load_dotenv
import anthropic

load_dotenv()


# ============================================
# 配置
# ============================================
@dataclass
class Config:
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    base_url: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL"))
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "claude-3-5-sonnet-latest"))
    max_tokens: int = 8192
    log_file: Path = Path("agent_log.jsonl")
    snapshot_dir: Path = Path("sessions")
    project_dir: Path = field(default_factory=lambda: Path.cwd().resolve())
    max_messages: int = 10
    max_message_chars: int = 50000


# ============================================
# 工具注册表（全局）
# ============================================
class ToolRegistry:
    """全局工具注册表 - 单例模式"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.tools: Dict[str, Dict] = {}
            cls._instance.handlers: Dict[str, Callable] = {}
        return cls._instance
    
    def register(self, name: str, schema: Dict, handler: Callable):
        """注册工具"""
        self.tools[name] = schema
        self.handlers[name] = handler
        print(f"[注册] 工具 '{name}' 已加载")
    
    def get_tools(self) -> List[Dict]:
        """获取所有工具描述"""
        return list(self.tools.values())
    
    def get_handler(self, name: str) -> Optional[Callable]:
        """获取工具处理器"""
        return self.handlers.get(name)
    
    def list_tools(self) -> List[str]:
        """列出所有已注册的工具名"""
        return list(self.tools.keys())


# 全局注册表实例
registry = ToolRegistry()


# ============================================
# 装饰器：工具注册
# ============================================
def tool(
    name: Optional[str] = None,
    description: str = "",
    params: Optional[Dict] = None,
    required: Optional[List[str]] = None
):
    """
    工具注册装饰器
    
    用法:
    @tool(
        name="calculate",
        description="计算数学表达式",
        params={"expression": {"type": "string", "description": "数学表达式"}},
        required=["expression"]
    )
    def my_calculator(expression: str) -> str:
        return str(eval(expression))
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        
        # 构建 schema
        schema = {
            "name": tool_name,
            "description": description or func.__doc__ or f"工具: {tool_name}",
            "input_schema": {
                "type": "object",
                "properties": params or {},
                "required": required or []
            }
        }
        
        # 注册到全局注册表
        registry.register(tool_name, schema, func)
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        # 附加元数据供其他装饰器使用
        wrapper._tool_name = tool_name
        wrapper._tool_schema = schema
        
        return wrapper
    return decorator


def protected_tool(config: Config):
    """
    受保护的工具装饰器 - 检查文件保护规则
    
    用法:
    @protected_tool(config)
    @tool(name="write_file", ...)
    def write_file(path: str, content: str) -> str:
        ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 检查是否是写文件操作
            if func._tool_name == "write_file":
                path = kwargs.get("path") or (args[0] if args else None)
                if path and is_protected_source(path, config):
                    return f"拒绝执行：'{path}' 是受保护源码文件"
            return func(*args, **kwargs)
        return wrapper
    return decorator


def confirm_required(permission_checker: Callable, confirmer: Callable):
    """
    需要确认的装饰器
    
    用法:
    @confirm_required(needs_confirmation, confirm_action)
    @tool(name="write_file", ...)
    def write_file(path: str, content: str) -> str:
        ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tool_name = func._tool_name
            tool_input = kwargs or dict(zip(func.__code__.co_varnames, args))
            
            if permission_checker(tool_name, tool_input):
                if not confirmer(tool_name, tool_input):
                    return "用户拒绝了此操作"
            else:
                print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def log_execution(logger: "Logger"):
    """执行日志装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tool_name = func._tool_name
            tool_input = kwargs or dict(zip(func.__code__.co_varnames, args))
            
            logger.log("tool_executing", {"tool": tool_name, "input": tool_input})
            
            try:
                result = func(*args, **kwargs)
                logger.log("tool_executed", {"tool": tool_name, "result": str(result)[:200]})
                return result
            except Exception as e:
                logger.log("tool_error", {"tool": tool_name, "error": str(e)})
                raise
        return wrapper
    return decorator


def result_modifier(modifier: Callable):
    """结果修饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return modifier(func._tool_name, result)
        return wrapper
    return decorator


# ============================================
# 权限函数
# ============================================
def is_protected_source(path: str, config: Config) -> bool:
    try:
        file_path = Path(path).expanduser().resolve(strict=False)
        return (
            file_path.is_relative_to(config.project_dir)
            and file_path.suffix.lower() == ".py"
            and file_path.exists()
        )
    except Exception:
        return False


def needs_confirmation(tool_name: str, tool_input: Dict, config: Config) -> bool:
    if tool_name == "write_file":
        return True
    if tool_name in ("read_file", "read_file_lines"):
        file_path = Path(tool_input.get("path", "")).resolve()
        return not file_path.is_relative_to(config.project_dir)
    if tool_name == "calculate":
        return False
    return True


def confirm_action(tool_name: str, tool_input: Dict) -> bool:
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
# 日志
# ============================================
class Logger:
    def __init__(self, config: Config):
        self.config = config
        self.session_id = str(uuid.uuid4())
        config.snapshot_dir.mkdir(exist_ok=True)
    
    def log(self, event_type: str, data: Dict):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "session_id": self.session_id,
            "event": event_type,
            "data": data,
        }
        with open(self.config.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
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
    
    @staticmethod
    def _make_serializable(messages: List[Dict]) -> List[Dict]:
        result = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                new_content = [
                    block.model_dump() if hasattr(block, "model_dump") else block
                    for block in msg["content"]
                ]
                result.append({"role": msg["role"], "content": new_content})
            else:
                result.append(msg)
        return result


# ============================================
# 上下文管理
# ============================================
class ContextManager:
    def __init__(self, client: anthropic.Anthropic, config: Config, logger: Logger):
        self.client = client
        self.config = config
        self.logger = logger
    
    def estimate_size(self, messages: List[Dict]) -> int:
        try:
            serializable = Logger._make_serializable(messages)
            return len(json.dumps(serializable, ensure_ascii=False))
        except Exception:
            return 0
    
    def compress(self, messages: List[Dict]) -> List[Dict]:
        total_size = self.estimate_size(messages)
        
        if len(messages) <= self.config.max_messages and total_size <= self.config.max_message_chars:
            return messages
        
        print(f"\n[系统] 压缩上下文中...（{len(messages)} 条）")
        
        recent = messages[-6:]
        old = messages[:-6]
        
        # 简化旧消息用于总结
        old_simplified = self._simplify_for_summary(old)
        
        try:
            response = self.client.messages.create(
                model=self.config.model_name,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        "请简要总结以下对话的关键信息："
                        f"\n{json.dumps(old_simplified, ensure_ascii=False)}"
                    )
                }]
            )
            
            summary = ""
            for block in response.content:
                if block.type == "text":
                    summary = block.text
                    break
            
            return [
                {"role": "user", "content": f"[历史摘要]\n{summary}"},
                {"role": "assistant", "content": "了解了，请继续。"},
            ] + recent
        
        except Exception as e:
            print(f"[警告] 压缩失败: {e}")
            return messages
    
    def _simplify_for_summary(self, messages: List[Dict]) -> List[Dict]:
        simplified = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                content = []
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        text = block.get("content", "")
                        content.append({"type": "tool_result", "content": text[:100] + "..." if len(text) > 100 else text})
                    else:
                        content.append(str(block)[:100])
                simplified.append({"role": msg["role"], "content": content})
            else:
                simplified.append(msg)
        return simplified


# ============================================
# 工具实现 - 使用装饰器注册
# ============================================
# 注意：工具函数将在 Agent 初始化后被装饰

class ToolImplementations:
    """工具实现类 - 方法将被装饰器注册"""
    
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self._register_all()
    
    def _register_all(self):
        """注册所有工具"""
        # 计算工具
        self._register_calculate()
        
        # 文件工具
        self._register_read_file()
        self._register_read_file_lines()
        self._register_write_file()
    
    def _register_calculate(self):
        @tool(
            name="calculate",
            description="计算数学表达式，支持 + - * / ( )",
            params={"expression": {"type": "string", "description": "数学表达式，如 '2 + 3'"}},
            required=["expression"]
        )
        @log_execution(self.logger)
        def calculate(expression: str) -> str:
            allowed = set("0123456789+-*/.() ")
            if not all(c in allowed for c in expression):
                return "错误：表达式包含不允许的字符"
            try:
                return str(eval(expression))
            except Exception as e:
                return f"计算错误：{e}"
    
    def _register_read_file(self):
        @tool(
            name="read_file",
            description="读取文件内容，大文件返回概览",
            params={"path": {"type": "string", "description": "文件路径"}},
            required=["path"]
        )
        @log_execution(self.logger)
        def read_file(path: str) -> str:
            try:
                file_path = Path(path)
                if not file_path.exists():
                    return f"错误：文件 '{path}' 不存在"
                
                content = file_path.read_text(encoding="utf-8")
                
                if len(content) <= 10000:
                    return content
                
                preview = content[:3000]
                outline = self._extract_outline(content) if file_path.suffix == ".py" else []
                outline_text = "\n".join(outline[:50]) if outline else "(无目录)"
                
                return (
                    f"[概览] 路径: {path} | 字符: {len(content)}\n\n"
                    f"[预览]\n{preview}\n\n"
                    f"[目录]\n{outline_text}\n\n"
                    f"[提示] 使用 read_file_lines 读取特定范围"
                )
            except Exception as e:
                return f"读取错误：{e}"
    
    def _register_read_file_lines(self):
        @tool(
            name="read_file_lines",
            description="按行号范围读取文件",
            params={
                "path": {"type": "string", "description": "文件路径"},
                "start_line": {"type": "integer", "description": "起始行号(>=1)"},
                "end_line": {"type": "integer", "description": "结束行号(>=start_line)"}
            },
            required=["path", "start_line", "end_line"]
        )
        @log_execution(self.logger)
        def read_file_lines(path: str, start_line: int, end_line: int) -> str:
            try:
                file_path = Path(path)
                if not file_path.exists():
                    return f"错误：文件 '{path}' 不存在"
                
                if start_line < 1 or end_line < 1 or start_line > end_line:
                    return "错误：行号参数无效"
                
                lines = file_path.read_text(encoding="utf-8").splitlines()
                actual_end = min(end_line, len(lines))
                
                if start_line > len(lines):
                    return f"错误：start_line 超出范围"
                
                selected = lines[start_line - 1:actual_end]
                numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start_line))
                
                return f"[读取] {path} 第 {start_line}-{actual_end} 行（共 {len(lines)} 行）\n\n{numbered}"
            except Exception as e:
                return f"读取错误：{e}"
    
    def _register_write_file(self):
        def add_post_instruction(tool_name: str, result: str) -> str:
            if not result.startswith(("拒绝", "错误", "写入错误")):
                result += "\n\n[系统指令] 文件已写入。请报告结果并询问用户是否继续。"
            return result
        
        @tool(
            name="write_file",
            description="写入文件（自动备份，自动创建目录）",
            params={
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"}
            },
            required=["path", "content"]
        )
        @protected_tool(self.config)
        @confirm_required(
            lambda name, inp: needs_confirmation(name, inp, self.config),
            confirm_action
        )
        @log_execution(self.logger)
        @result_modifier(add_post_instruction)
        def write_file(path: str, content: str) -> str:
            try:
                file_path = Path(path)
                
                # 备份
                backup_info = ""
                if file_path.exists():
                    backup = file_path.with_suffix(file_path.suffix + ".bak")
                    backup.write_text(file_path.read_text(encoding="utf-8"), encoding="utf-8")
                    backup_info = f"（原文件已备份到 '{backup}'）"
                
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                
                return f"成功写入 '{path}'{backup_info}"
            except Exception as e:
                return f"写入错误：{e}"
    
    def _extract_outline(self, content: str) -> List[str]:
        outline = []
        for idx, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("class "):
                name = stripped[6:].split("(", 1)[0].split(":", 1)[0].strip()
                outline.append(f"Line {idx}: class {name}")
            elif stripped.startswith("def "):
                name = stripped[4:].split("(", 1)[0].strip()
                outline.append(f"Line {idx}: def {name}")
        return outline


# ============================================
# Agent 主类
# ============================================
class DecoratorAgent:
    """基于装饰器的 Agent"""
    
    SYSTEM_PROMPT = """你是一个有用的助手，能够进行数学计算和文件操作。
你可以读取文件来了解信息，也可以创建和编辑文件。
在操作文件时请谨慎，先告诉用户你打算做什么，再执行操作。

重要规则：
- 如果任务涉及创建多个文件，请逐个创建，每次只写一个文件，写完后询问用户是否继续下一个。
- 不要试图在一次回复中完成所有文件的创建。"""
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.logger = Logger(self.config)
        self.messages: List[Dict] = []
        
        self.client = anthropic.Anthropic(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )
        
        self.context_manager = ContextManager(self.client, self.config, self.logger)
        
        # 初始化工具（触发装饰器注册）
        self.tools_impl = ToolImplementations(self.config, self.logger)
        
        self.logger.log("session_start", {"system_prompt": self.SYSTEM_PROMPT})
        print(f"[初始化] 已注册工具: {registry.list_tools()}")
    
    def _execute_tool(self, name: str, input_data: Dict) -> str:
        handler = registry.get_handler(name)
        if not handler:
            return f"错误：未知工具 '{name}'"
        return handler(**input_data)
    
    def chat(self, user_input: str) -> str:
        # 压缩上下文
        self.messages = self.context_manager.compress(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        self.logger.log("user_input", {"content": user_input})
        
        while True:
            self.logger.log("llm_call", {"message_count": len(self.messages)})
            
            with self.client.messages.stream(
                model=self.config.model_name,
                max_tokens=self.config.max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=self.messages,
                tools=registry.get_tools(),
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
            
            if response.stop_reason == "end_turn":
                text = "".join(block.text for block in response.content if block.type == "text")
                self.messages.append({"role": "assistant", "content": response.content})
                self.logger.log("agent_reply", {"content": text})
                return text
            
            if response.stop_reason == "tool_use":
                self.messages.append({"role": "assistant", "content": response.content})
                
                for block in response.content:
                    if block.type == "tool_use":
                        self._process_tool(block)
                continue
            
            return f"意外响应: {response.stop_reason}"
    
    def _process_tool(self, block):
        tool_name = block.name
        tool_input = block.input
        tool_use_id = block.id
        
        self.logger.log("tool_requested", {"tool": tool_name, "input": tool_input})
        
        # 执行工具
        result = self._execute_tool(tool_name, tool_input)
        
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
        })
    
    def run(self):
        print("=== Decorator-based Agent (Method 2) ===")
        print("基于装饰器的工具注册版本。输入 'quit' 退出\n")
        
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
    agent = DecoratorAgent()
    agent.run()
