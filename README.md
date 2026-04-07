# 项目名称

基于 Anthropic Claude API 的 Python 项目

## 项目简介

这是一个使用 Anthropic Claude API 的 Python 应用程序，利用 Pydantic 进行数据验证和类型检查。

## 功能特性

- 🤖 集成 Anthropic Claude API
- ✅ 使用 Pydantic 进行数据验证
- 🔧 支持环境变量配置
- 📝 完整的类型注解支持

## 技术栈

- Python
- Anthropic API (anthropic >= 0.89.0)
- Pydantic (pydantic >= 2.12.5)
- python-dotenv (用于环境变量管理)

## 安装

1. 克隆项目到本地：
```bash
git clone <repository-url>
cd <project-name>
```

2. 创建虚拟环境（推荐）：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

## 配置

1. 在项目根目录创建 `.env` 文件：
```env
ANTHROPIC_API_KEY=your_api_key_here
```

2. 确保 `.env` 文件已添加到 `.gitignore` 中，避免泄露敏感信息。

## 使用方法

```python
import anthropic
from dotenv import load_dotenv
import os

# 加载环境变量
load_dotenv()

# 初始化客户端
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# 使用示例
# TODO: 添加具体使用代码
```

## 项目结构

```
.
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
└── src/
    └── main.py
```

## 依赖列表

主要依赖项：

| 包名 | 版本 | 用途 |
|------|------|------|
| anthropic | 0.89.0 | Anthropic Claude API 客户端 |
| pydantic | 2.12.5 | 数据验证和序列化 |
| python-dotenv | 1.2.2 | 环境变量管理 |
| httpx | 0.28.1 | HTTP 客户端 |

完整依赖列表请查看 `requirements.txt`

## 开发

### 代码规范

- 使用类型注解
- 遵循 PEP 8 编码规范
- 使用 Pydantic 模型进行数据验证

## 许可证

[添加许可证信息]

## 作者

[添加作者信息]

## 联系方式

[添加联系方式]

---

> ⚠️ **注意**: 请确保妥善保管 API 密钥，不要在代码中硬编码敏感信息。
