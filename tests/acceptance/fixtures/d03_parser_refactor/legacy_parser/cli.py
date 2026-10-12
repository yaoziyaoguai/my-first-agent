from __future__ import annotations


def run(argv: list[str]) -> dict[str, str]:
    if len(argv) != 1:
        raise ValueError("exactly one record is required")
    fields: dict[str, str] = {}
    for chunk in argv[0].split(";"):
        if not chunk.strip():
            continue
        key, separator, value = chunk.partition("=")
        if not separator:
            raise ValueError("record fields must use key=value")
        fields[key.strip()] = value.strip()
    return fields
