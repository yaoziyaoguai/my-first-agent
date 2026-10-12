from __future__ import annotations


def resolve_config(
    defaults: dict[str, str],
    environment: dict[str, str],
    project: dict[str, str],
    cli: dict[str, str],
) -> dict[str, str]:
    result = dict(defaults)
    result.update(project)
    result.update(environment)
    result.update(cli)
    return result
