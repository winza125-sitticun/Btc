# Codex Instructions

GitHub Spec Kit is the primary development workflow for this repository.

## Before editing runtime code

Read, in order:

1. `.specify/memory/constitution.md`
2. the active `specs/<NNN>-<feature>/spec.md`
3. the matching `plan.md`
4. the matching `tasks.md`

For bug work, follow the official Spec Kit bug flow and read the active `.specify/bugs/<slug>/` reports.

Do not create a second requirements document specifically for Codex. The Spec Kit artifacts are the source of truth shared with GitHub Copilot.

## Feature workflow

Use:

`specify -> clarify -> plan -> tasks -> analyze -> implement -> converge`

Do not declare a feature complete while material gaps remain between implementation and the active spec/plan/tasks.

## Bug workflow

Use:

`bug.assess -> bug.fix -> bug.test`

Required evidence:

```text
.specify/bugs/<slug>/assessment.md
.specify/bugs/<slug>/fix.md
.specify/bugs/<slug>/test.md
```

Do not patch an applicable runtime bug before assessment.

## Scope and safety

Implement only the active task or assessed remediation. Avoid unrelated refactors.

Changes involving live-order capability, exchange credentials, leverage, position sizing, risk limits, stop-loss/take-profit logic, order routing, or execution safety gates require explicit authorization in the active spec.

Default new execution behavior to read-only, dry-run, or paper mode unless the approved spec explicitly requires otherwise.

## Verification

Run tests/builds appropriate to the changed area. Repository baseline checks are:

- `pytest -q`
- `cd apps/web && npm run build`
- Spec governance check when applicable

Record evidence in the pull request.

## Handoff

A handoff should identify the active spec or bug slug and the next incomplete task. Example:

`Continue specs/012-news-intelligence from the first incomplete task. Read the constitution, spec, plan, and tasks before editing code.`

Historical `.superpowers/sdd/` files are legacy evidence only for new work.