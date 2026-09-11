# Implementation Plan: Spec Kit Primary Workflow

## Summary

This feature changes repository development governance only. Runtime application code remains untouched. The implementation introduces a Spec Kit constitution, a canonical workflow guide, Codex/Copilot instructions, reproducible Spec Kit bootstrap, structural PR governance, tests, and PR-review metadata.

## Technical context

- Repository: Python backend/core plus web application.
- Existing CI: Python 3.12 + pytest; Node 22 + web build.
- Spec Kit version: v1.0.6.
- Governance implementation: Python 3.12 script invoked from GitHub Actions.
- Bug workflow: official Spec Kit `bug` extension.

## Architecture

### Authoritative artifacts

- `.specify/memory/constitution.md` — repository-wide development rules.
- `specs/<NNN>-<feature>/` — feature specification, plan, and tasks.
- `.specify/bugs/<slug>/` — bug assessment, fix, and test evidence.

### Agent integration

- `AGENTS.md` provides Codex instructions.
- `.github/copilot-instructions.md` provides GitHub Copilot instructions.
- Both reference the same authoritative artifacts.
- `scripts/bootstrap-speckit.sh` installs pinned Spec Kit, initializes Codex skills, installs Copilot integration, and adds the bug extension.

### Pull-request governance

`scripts/check_spec_governance.py` receives base/head git refs and determines changed files.

Runtime-sensitive paths are:
- `apps/`
- `btc_core/`
- root `Dockerfile*`
- root `railway*.toml`
- `pyproject.toml`

For runtime changes:
- branches beginning `fix/` or `bugfix/` require one changed `.specify/bugs/<slug>/` directory with `assessment.md`, `fix.md`, and `test.md` present;
- all other branches require one changed `specs/<feature>/` directory with `spec.md`, `plan.md`, and `tasks.md` present.

Process/documentation-only changes pass without a feature/bug artifact requirement.

### Verification

- Unit-test the governance decision function without invoking git.
- GitHub Actions runs the checker against PR base/head SHAs.
- Existing CI remains responsible for complete backend tests and web build.

## Rollout

1. Land workflow artifacts and agent instructions.
2. Land governance checker/tests/action.
3. Add PR template and README entry point.
4. Open PR and let existing CI plus governance action verify the migration.
5. Merge only after required checks pass.

## Risks and mitigations

- **False positive for small runtime change:** the workflow intentionally requires a spec or bug record for runtime behavior; keep process-only paths exempt.
- **Agent integration drift:** pin Spec Kit v1.0.6 and make upgrades explicit.
- **Duplicate SDD systems:** mark `.superpowers/sdd/` legacy for new work and do not delete history.
- **Safety regression:** no runtime source changes are included in this migration; the constitution adds explicit future safety gates.
