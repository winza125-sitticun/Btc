# Spec Kit Primary Workflow Design

## Status

Approved on 2026-09-11 for `winza125-sitticun/Btc`.

## Goal

Make GitHub Spec Kit the authoritative software-development workflow for this repository from idea/feature intake through implementation, bug fixing, verification, and handoff to Codex or GitHub Copilot.

## Source of truth

1. `.specify/memory/constitution.md` governs repository-wide engineering rules.
2. `specs/<NNN>-<feature>/spec.md` defines what and why.
3. `specs/<NNN>-<feature>/plan.md` defines architecture and implementation approach.
4. `specs/<NNN>-<feature>/tasks.md` defines executable work and completion state.
5. `.specify/bugs/<slug>/` is authoritative for bug assessment, fix record, and verification.
6. Production code is an implementation of those artifacts, not a replacement for them.
7. `.superpowers/sdd/` remains historical evidence for work created before this migration and must not be used as the primary location for new specs.

## Feature workflow

All material feature work follows:

`specify -> clarify -> plan -> tasks -> analyze -> implement -> converge -> PR -> CI -> merge`

The normal agent commands are:

- `speckit.constitution` for project principles.
- `speckit.specify` for feature requirements.
- `speckit.clarify` when requirements are ambiguous.
- `speckit.plan` for the implementation plan.
- `speckit.tasks` for executable tasks.
- `speckit.analyze` before implementation when cross-artifact consistency needs checking.
- `speckit.implement` for task execution.
- `speckit.converge` after implementation; work is not complete until convergence reports no material gap.

A change that modifies runtime behavior under `apps/` or `btc_core/`, or production/deployment configuration, must travel with a feature spec unless it is handled by the bug workflow.

## Bug workflow

Use the official Spec Kit `bug` extension. Each bug has:

```text
.specify/bugs/<slug>/
├── assessment.md
├── fix.md
└── test.md
```

The required order is `bug.assess -> bug.fix -> bug.test`. Assessment and test stages do not modify source code; the fix stage implements the assessed remediation and records deviations. A bug PR is incomplete until all three reports exist.

## Codex and GitHub Copilot

Both agents use the same repository artifacts. They must not create agent-specific copies of requirements.

- `AGENTS.md` is the Codex-facing entry point.
- `.github/copilot-instructions.md` is the GitHub Copilot entry point.
- Both documents point to the same constitution, spec, plan, tasks, and bug artifacts.
- `scripts/bootstrap-speckit.sh` pins Spec Kit to v1.0.6, initializes Codex skills, installs the Copilot integration, and enables the official bug extension.

A handoff should name only the active spec or bug slug and current task. Example: `Continue specs/012-news-intelligence from the first incomplete task; read constitution, spec, plan, and tasks before editing code.`

## Governance and CI

A dedicated Spec governance job examines pull-request changes.

- Documentation-only/process-only changes pass without a feature artifact.
- Runtime feature changes require a changed `specs/<feature>/` directory containing `spec.md`, `plan.md`, and `tasks.md`.
- Runtime bug changes on `fix/*` or `bugfix/*` branches require `.specify/bugs/<slug>/assessment.md`, `fix.md`, and `test.md`.
- Existing backend tests and web build remain required.
- PR templates expose the artifact paths, verification performed, and convergence result.

The governance check is intentionally structural. It ensures the workflow was followed without trying to judge whether a requirement is semantically good.

## Trading-system guardrails

The BTC repository can influence futures-trading decisions, so these are non-negotiable:

- Never silently broaden order-execution permissions.
- Any change to live-order capability, risk limits, leverage handling, sizing, stop-loss/take-profit behavior, exchange credentials, or safety gates requires explicit requirements in the active spec.
- Default new execution behavior to read-only, dry-run, or paper mode unless the approved spec explicitly requires otherwise.
- Tests must cover safety-relevant behavior changed by the work.
- AI-generated confidence or direction is advisory unless an approved spec explicitly defines an execution contract.

## Migration

No historical `.superpowers/sdd/` material is deleted. New work starts in `specs/` or `.specify/bugs/`. Existing reports remain available as implementation evidence and may be referenced from a new spec when useful.

## Rollout

This migration is delivered on `codex/spec-kit-primary-workflow` and merged by pull request. The first feature spec is `001-spec-kit-primary-workflow`, which bootstraps the workflow itself. After merge, future runtime PRs are subject to the Spec governance check.