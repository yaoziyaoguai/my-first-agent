"""严格 packaged-Skill Seatbelt policy 的公共合同。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agent.runtime.contracts import canonical_json_digest
from agent.sandbox.contracts import (
    PackagedSkillResourceLimitsV1,
    PackagedSkillSandboxPolicyV1,
    SandboxMode,
    SandboxNetworkMode,
)
from agent.sandbox.packaged_policy import (
    build_packaged_skill_policy,
    compile_packaged_skill_profile,
)


class Roots:
    def __init__(self, root: Path) -> None:
        self.product = root / "product"
        self.runtime = root / "runtime"
        self.package = root / "package"
        self.temp = root / "temp"
        self.system = root / "system"
        self.workspace = root / "workspace"
        self.home = root / "home"
        self.state = root / "state"
        self.private = root / "private"
        for path in (
            self.product,
            self.runtime,
            self.package,
            self.temp,
            self.system,
            self.workspace,
            self.home,
            self.state,
            self.private,
        ):
            path.mkdir()
        for path in (self.product, self.runtime, self.package):
            path.chmod(0o555)
        self.interpreter = self.system / "python"
        self.interpreter.write_text("fixture", encoding="utf-8")
        self.interpreter.chmod(0o555)


def _roots(tmp_path: Path) -> Roots:
    return Roots(tmp_path)


def _policy(roots: Roots):
    return build_packaged_skill_policy(
        interpreter_path=roots.interpreter,
        runtime_roots=(roots.runtime,),
        package_root=roots.package,
        temp_root=roots.temp,
        system_runtime_roots=(roots.system,),
        workspace_root=roots.workspace,
        home_root=roots.home,
        state_root=roots.state,
        private_roots=(roots.private,),
        runtime_closure_digest="a" * 64,
        system_runtime_digest="b" * 64,
        resource_limits=PackagedSkillResourceLimitsV1.for_profile(
            "skill-standard-v1"
        ),
    )


def _direct_policy(roots: Roots, **overrides: object) -> PackagedSkillSandboxPolicyV1:
    values: dict[str, object] = {
        "interpreter_path": str(roots.interpreter),
        "runtime_roots": (str(roots.runtime),),
        "package_root": str(roots.package),
        "temp_root": str(roots.temp),
        "system_runtime_roots": (str(roots.system),),
        "workspace_root": str(roots.workspace),
        "home_root": str(roots.home),
        "state_root": str(roots.state),
        "private_roots": (str(roots.private),),
        "runtime_closure_digest": "a" * 64,
        "system_runtime_digest": "b" * 64,
        "resource_limits": PackagedSkillResourceLimitsV1.for_profile(
            "skill-standard-v1"
        ),
    }
    values.update(overrides)
    return PackagedSkillSandboxPolicyV1(**values)  # type: ignore[arg-type]


def test_packaged_profile_is_deny_default_and_exact_allowlist(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    policy = _policy(roots)
    session = roots.temp / "session"
    session.mkdir()

    profile = compile_packaged_skill_profile(policy, {"TMPDIR": str(session)})

    lines = profile.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"]
    assert "(allow default)" not in profile
    assert policy.workspace_root not in profile
    assert policy.home_root not in profile
    assert policy.state_root not in profile
    assert policy.private_roots[0] not in profile
    assert '(deny network*)' in profile
    assert '(deny process-fork)' in profile
    assert '(allow file-read-data (literal "/"))' in profile
    assert '(allow file-read* (subpath "/"))' not in profile
    assert f'(allow file-write-data (literal "{session}/result.json"))' in profile
    assert f'(allow file-write-data (literal "{session}/artifact.bin"))' in profile
    assert f'(allow file-write* (subpath "{session}"))' not in profile
    assert f'(allow process-exec (literal "{policy.interpreter_path}"))' in profile
    assert "(allow process-exec*)" not in profile


def test_policy_rejects_overlapping_runtime_package_or_denied_roots(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)

    with pytest.raises(ValueError, match="overlap"):
        build_packaged_skill_policy(
            interpreter_path=roots.interpreter,
            runtime_roots=(roots.package,),
            package_root=roots.package,
            temp_root=roots.temp,
            system_runtime_roots=(roots.system,),
            workspace_root=roots.workspace,
            home_root=roots.home,
            state_root=roots.state,
            private_roots=(),
            runtime_closure_digest="a" * 64,
            system_runtime_digest="b" * 64,
            resource_limits=PackagedSkillResourceLimitsV1.for_profile(
                "skill-standard-v1"
            ),
        )


@pytest.mark.parametrize("profile", ["skill-standard-v1", "artifact-standard-v1"])
def test_resource_limit_profiles_are_named_exact_and_not_numerically_mutable(
    profile: str,
) -> None:
    limits = PackagedSkillResourceLimitsV1.for_profile(profile)

    with pytest.raises(ValueError, match="closed profile"):
        replace(limits, cpu_seconds=limits.cpu_seconds + 1)
    with pytest.raises(ValueError, match="not closed"):
        PackagedSkillResourceLimitsV1.for_profile("future-profile")


def test_limit_digest_binds_the_exact_named_limit_row() -> None:
    limits = PackagedSkillResourceLimitsV1.for_profile("artifact-standard-v1")

    assert limits.limits_digest == canonical_json_digest(
        {
            "profile": "artifact-standard-v1",
            "cpu_seconds": 120,
            "address_space_bytes": 2 * 1024 * 1024 * 1024,
            "file_size_bytes": 64 * 1024 * 1024,
            "open_files": 128,
            "core_bytes": 0,
        }
    )


def test_policy_identity_is_closed_to_read_only_network_off(tmp_path: Path) -> None:
    policy = _policy(_roots(tmp_path))

    assert policy.mode is SandboxMode.READ_ONLY
    assert policy.network is SandboxNetworkMode.OFF
    assert policy.policy_digest == canonical_json_digest(policy.identity_values())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda roots: roots.runtime.chmod(0o755), "writable"),
        (lambda roots: roots.package.chmod(0o755), "writable"),
        (lambda roots: roots.runtime.mkdir(exist_ok=True), "product tree"),
    ],
)
def test_policy_rejects_writable_or_product_tree_roots(
    tmp_path: Path, mutate, message: str
) -> None:
    roots = _roots(tmp_path)
    if message == "product tree":
        roots.runtime = Path(__file__).resolve().parents[2] / "agent"
    else:
        mutate(roots)

    with pytest.raises(ValueError, match=message):
        _policy(roots)


def test_policy_rejects_noncanonical_and_symlink_roots(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    alias = tmp_path / "runtime-alias"
    alias.symlink_to(roots.runtime)

    with pytest.raises(ValueError, match="canonical"):
        build_packaged_skill_policy(
            interpreter_path=roots.interpreter,
            runtime_roots=(alias,),
            package_root=roots.package,
            temp_root=roots.temp,
            system_runtime_roots=(roots.system,),
            workspace_root=roots.workspace,
            home_root=roots.home,
            state_root=roots.state,
            private_roots=(roots.private,),
            runtime_closure_digest="a" * 64,
            system_runtime_digest="b" * 64,
            resource_limits=PackagedSkillResourceLimitsV1.for_profile(
                "skill-standard-v1"
            ),
        )


def test_policy_rejects_interpreter_outside_qualified_read_roots(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    outside_interpreter = tmp_path / "outside-python"
    outside_interpreter.write_text("fixture", encoding="utf-8")
    outside_interpreter.chmod(0o555)

    with pytest.raises(ValueError, match="qualified runtime/system root"):
        build_packaged_skill_policy(
            interpreter_path=outside_interpreter,
            runtime_roots=(roots.runtime,),
            package_root=roots.package,
            temp_root=roots.temp,
            system_runtime_roots=(roots.system,),
            workspace_root=roots.workspace,
            home_root=roots.home,
            state_root=roots.state,
            private_roots=(roots.private,),
            runtime_closure_digest="a" * 64,
            system_runtime_digest="b" * 64,
            resource_limits=PackagedSkillResourceLimitsV1.for_profile(
                "skill-standard-v1"
            ),
        )


def test_profile_requires_existing_canonical_direct_temp_child(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    policy = _policy(roots)
    nested = roots.temp / "outer" / "session"
    nested.parent.mkdir()
    nested.mkdir()

    with pytest.raises(ValueError, match="direct child"):
        compile_packaged_skill_profile(policy, {"TMPDIR": str(nested)})


def test_builder_sorts_legal_runtime_roots_before_policy_identity(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    first = tmp_path / "a-runtime"
    second = tmp_path / "z-runtime"
    for root in (first, second):
        root.mkdir()
        root.chmod(0o555)

    policy = build_packaged_skill_policy(
        interpreter_path=roots.interpreter,
        runtime_roots=(second, first),
        package_root=roots.package,
        temp_root=roots.temp,
        system_runtime_roots=(roots.system,),
        workspace_root=roots.workspace,
        home_root=roots.home,
        state_root=roots.state,
        private_roots=(roots.private,),
        runtime_closure_digest="a" * 64,
        system_runtime_digest="b" * 64,
        resource_limits=PackagedSkillResourceLimitsV1.for_profile(
            "skill-standard-v1"
        ),
    )

    assert policy.runtime_roots == (str(first), str(second))


def test_direct_policy_validator_rejects_unsorted_runtime_roots(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    first = tmp_path / "a-runtime"
    second = tmp_path / "z-runtime"
    for root in (first, second):
        root.mkdir()
        root.chmod(0o555)
    session = roots.temp / "session"
    session.mkdir()
    policy = _direct_policy(
        roots,
        runtime_roots=(str(second), str(first)),
    )

    with pytest.raises(ValueError, match="sorted canonical roots"):
        compile_packaged_skill_profile(policy, {"TMPDIR": str(session)})


@pytest.mark.parametrize(
    ("forgery", "message"),
    [
        ("root_runtime", "runtime_roots"),
        ("workspace_runtime", "overlap"),
        ("noncanonical_runtime", "canonical"),
        ("symlink_runtime", "canonical"),
        ("writable_runtime", "writable"),
        ("interpreter_outside_roots", "qualified runtime/system root"),
    ],
)
def test_directly_constructed_forged_policy_cannot_emit_profile(
    tmp_path: Path, forgery: str, message: str
) -> None:
    roots = _roots(tmp_path)
    session = roots.temp / "session"
    session.mkdir()
    overrides: dict[str, object] = {}
    if forgery == "root_runtime":
        overrides["runtime_roots"] = ("/",)
    elif forgery == "workspace_runtime":
        overrides["runtime_roots"] = (str(roots.workspace),)
    elif forgery == "noncanonical_runtime":
        overrides["runtime_roots"] = (f"{roots.runtime}/../runtime",)
    elif forgery == "symlink_runtime":
        alias = tmp_path / "runtime-alias"
        alias.symlink_to(roots.runtime)
        overrides["runtime_roots"] = (str(alias),)
    elif forgery == "writable_runtime":
        roots.runtime.chmod(0o755)
    else:
        outside = tmp_path / "outside-python"
        outside.write_text("fixture", encoding="utf-8")
        outside.chmod(0o555)
        overrides["interpreter_path"] = str(outside)
    policy = _direct_policy(roots, **overrides)

    with pytest.raises(ValueError, match=message):
        compile_packaged_skill_profile(policy, {"TMPDIR": str(session)})
