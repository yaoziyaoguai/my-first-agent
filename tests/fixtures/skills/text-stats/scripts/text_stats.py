"""text-stats entrypoint：统计文本字符数与词数，返回 observation 结果。

合同（first-agent-skill-result-v1）：只导出 ``run(arguments, inputs)``，
``arguments.text`` 是字符串，返回 kind/payload/artifact 形状。
"""


def run(arguments, inputs):
    text = arguments["text"]
    if not isinstance(text, str):
        raise TypeError("arguments.text must be a string")
    return {
        "kind": "observation",
        "payload": {"characters": len(text), "words": len(text.split())},
        "artifact": None,
    }
