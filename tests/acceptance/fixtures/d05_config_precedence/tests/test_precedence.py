from config_app import resolve_config


def test_cli_values_have_the_highest_precedence() -> None:
    resolved = resolve_config(
        {"region": "default"},
        {"region": "environment"},
        {"region": "project"},
        {"region": "cli"},
    )

    assert resolved["region"] == "cli"
