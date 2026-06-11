"""Conftest for Golden E2E suite.

Re-uses ``FakeProvider`` and the existing ``chat()`` entry point directly from
``tests/conftest.py``. No new shared helper module — per Plan U1, the conftest
just imports what it needs.
"""

from __future__ import annotations

# Tests import FakeProvider from tests.conftest (it is not re-exported here to
# avoid a second fake client). Golden E2E scenarios drive ``chat()`` directly
# with FakeProvider; the dispatcher action log is then read off the
# ``runtime_action_dispatcher`` injected by ``chat()`` (Phase A) — but for U1
# characterization we only need the user-visible reply and display events.
