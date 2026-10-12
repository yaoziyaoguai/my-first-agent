from __future__ import annotations


def load_line(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for chunk in text.split(";"):
        if not chunk.strip():
            continue
        key, separator, value = chunk.partition("=")
        if not separator:
            raise ValueError("record fields must use key=value")
        fields[key.strip()] = value.strip()
    return fields
