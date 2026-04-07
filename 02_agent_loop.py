import os
from dotenv import load_dotenv
import anthropic

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

# ============================================
# 这个列表就是模型的"记忆"
# 它是 Context Engineering 的核心对象
# 每一轮对话都会往里追加内容
# ============================================
messages = []

def chat(user_input):
    """一次完整的对话轮次"""
    
    # 1. 把用户输入追加到消息历史
    messages.append({"role": "user", "content": user_input})
    
    # 2. 把完整的消息历史发送给模型
    response = client.messages.create(
        model=os.getenv("MODEL_NAME"),
        max_tokens=1024,
        messages=messages,
    )
    
    # 3. 提取模型的文本回复
    assistant_text = ""
    for block in response.content:
        if block.type == "text":
            assistant_text = block.text
            break
    
    # 4. 把模型的回复也追加到消息历史
    #    这样下一轮对话时，模型能"记住"之前说过什么
    messages.append({"role": "assistant", "content": assistant_text})
    
    return assistant_text

# ============================================
# 这就是 Agent Loop
# 不断循环：用户输入 → 模型回复 → 用户输入 → ...
# ============================================
print("=== My First Agent ===")
print("输入 'quit' 退出\n")

while True:
    user_input = input("你: ")
    
    if user_input.strip().lower() == "quit":
        print("再见！")
        break
    
    reply = chat(user_input)
    print(f"\nAgent: {reply}\n")
