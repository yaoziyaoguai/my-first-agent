import hashlib
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from agent.tool_registry import register_tool

FETCH_TIMEOUT = 15
FETCH_MAX_CHARS = 10000


@register_tool(
    name="fetch_url",
    description="读取一个网页的文本内容。仅在用户明确提供 URL 或要求访问网页时使用。不要主动搜索或猜测 URL。",
    parameters={
        "url": {
            "type": "string",
            "description": "要读取的网页 URL，必须以 http:// 或 https:// 开头"
        },
    },
    confirmation="always",
    capability="network_fetch",
    risk_level="high",
    output_policy="artifact_text",
)
def fetch_url(url):
    if not url.startswith(("http://", "https://")):
        return "错误：URL 必须以 http:// 或 https:// 开头"
    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AgentBot/1.0)"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        total_chars = len(text)
        if total_chars == 0:
            return f"[读取成功] URL: {url}\n\n页面没有可提取的文本内容。"
        if total_chars > FETCH_MAX_CHARS:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            save_path = Path("workspace") / f"fetched_{url_hash}.txt"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(text, encoding="utf-8")
            preview = text[:3000]
            total_lines = len(text.splitlines())
            return (
                f"[读取成功 - 内容较长，已保存到本地]\n"
                f"URL: {url}\n"
                f"总字符数: {total_chars}\n"
                f"总行数: {total_lines}\n"
                f"本地文件: {save_path}\n\n"
                f"[开头预览（前 3000 字符）]\n"
                f"{preview}\n\n"
                f"[说明] 完整内容已保存到 {save_path}。如需查看具体部分，请使用 read_file_lines 工具读取该文件。"
            )
        return (
            f"[读取成功]\n"
            f"URL: {url}\n"
            f"总字符数: {total_chars}\n\n"
            f"{text}"
        )
    except httpx.TimeoutException:
        return f"读取超时：{url} 在 {FETCH_TIMEOUT} 秒内未响应。"
    except httpx.HTTPStatusError as e:
        return f"HTTP 错误：{url} 返回状态码 {e.response.status_code}"
    except Exception as e:
        return f"读取失败：{e}"
