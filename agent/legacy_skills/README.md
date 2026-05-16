# Legacy Skills Quarantine

This package contains the historical `agent.skills` prototype.

It is not the formal Skill System, not a supported import path for new code, and
not a default tool lifecycle path. Formal Skill work must use
`agent/skill_system/`.

Quarantine rules:

- do not import this package from `agent/skill_system/`
- do not register its lifecycle tools by default
- do not use `install_from_github` as a formal install path
- do not treat the module-level registry as a session/runtime-scoped design
- migration from this package requires an explicit approved migration phase
