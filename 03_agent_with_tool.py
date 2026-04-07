import os
import json
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

# ============================================
# 第一部分：定义工具
# 这是告诉模型"你有什么能力"
# 模型自己不会算数，但它可以请求调用这个工具
# ============================================

# 工具的实际实现（Python 函数）
def calculate(expression):
    """安全地计算一个数学表达式"""
    try:
        # 只允许数字和基本运算符，防止执行危险代码
        allowed = set("0123456789+-*/.() ")
        if not all(c in allowed for c in expression):
            return f"错误：表达式包含不允许的字符"
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误：{e}"

# 工具的描述（告诉模型这个工具是干什么的、怎么调用）
# 这个描述本身就是 Context Engineering —— 你在塑造模型对工具的理解
tools = [
    {
        "name": "calculate",
        "description": "计算一个数学表达式。当用户需要进行数学计算时使用此工具。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，例如 '2 + 3 * 4'"
                }
            },
            "required": ["expression"]
        }
    }
]

# ============================================
# 第二部分：Agent Loop
# 跟上一版最大的区别：模型的回复不一定是文字
# 它可能是一个"我想调用工具"的请求
# ============================================

messages = []

def chat(user_input):
    messages.append({"role": "user", "content": user_input})
    
    while True:  # 内层循环：处理工具调用
        print(f"[DEBUG] 消息历史: {len(messages)} 条，发送请求中...")
        
        response = client.messages.create(
            model=os.getenv("MODEL_NAME"),
            max_tokens=1024,
            system="你是一个数学辅导老师。你的风格是耐心、鼓励性的。当用户问数学题时，你不要直接给答案，而是先引导他们思考解题思路，然后再用计算器验证结果。",
            messages=messages,
            tools=tools,
        )
        
        # 检查模型返回了什么
        # stop_reason 告诉我们模型是"说完了"还是"想用工具"
        print(f"[DEBUG] stop_reason: {response.stop_reason}")
        
        # 如果模型说完了，提取文字返回
        if response.stop_reason == "end_turn":
            assistant_text = ""
            for block in response.content:
                if block.type == "text":
                    assistant_text = block.text
            messages.append({"role": "assistant", "content": response.content})
            return assistant_text
        
        # 如果模型想用工具
        if response.stop_reason == "tool_use":
            # 先把模型的回复（包含工具调用请求）存入历史
            messages.append({"role": "assistant", "content": response.content})
            
            # 遍历所有 content block，找到工具调用
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_use_id = block.id
                    
                    print(f"[DEBUG] 模型请求调用工具: {tool_name}({tool_input})")
                    
                    # 执行工具
                    if tool_name == "calculate":
                        result = calculate(tool_input["expression"])
                    else:
                        result = f"未知工具: {tool_name}"
                    
                    print(f"[DEBUG] 工具返回结果: {result}")
                    
                    # 把工具结果送回模型
                    # 注意这里的 role 是 "user"，但 type 是 "tool_result"
                    # 这就是 Context Engineering —— 把外部世界的信息注入上下文
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result,
                            }
                        ],
                    })
            
            # 工具结果已经加入消息历史
            # 循环继续，再次调用模型，让它根据工具结果生成最终回复
            continue
        
        # 其他情况（不应该发生）
        return "意外的响应"

# ============================================
# 第三部分：主循环
# ============================================
print("=== My First Agent (with Tools) ===")
print("试试问我数学题！输入 'quit' 退出\n")

while True:
    user_input = input("你: ")
    if user_input.strip().lower() == "quit":
        print("再见！")
        break
    reply = chat(user_input)
    print(f"\nAgent: {reply}\n")
