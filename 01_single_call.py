import os
from dotenv import load_dotenv
import anthropic

# 第一步：加载环境变量
load_dotenv()

# 第二步：创建客户端
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

# 第三步：发送一条消息
response = client.messages.create(
    model=os.getenv("MODEL_NAME"),
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "你好，请用一句话介绍你自己"}
    ],
)

# 第四步：打印结果
# 跳过 thinking block，只取文本
for block in response.content:
    if block.type == "text":
        print(block.text)
        break
