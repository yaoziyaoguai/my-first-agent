from retry_app import RetryService


def test_successful_operation_runs_once() -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        return "done"

    assert RetryService().run(operation) == "done"
    assert calls == 1
