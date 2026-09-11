# GitHub Copilot Instructions

GitHub Spec Kit is the primary development workflow for this repository. Use the same source-of-truth artifacts as Codex; do not create Copilot-specific requirements copies.

## Required context before runtime edits

Read:

1. `.specify/memory/constitution.md`
2. active `specs/<NNN>-<feature>/spec.md`
3. matching `plan.md`
4. matching `tasks.md`

For bugs, use the active `.specify/bugs/<slug>/assessment.md`, `fix.md`, and `test.md` according to the current stage.

## Feature lifecycle

Follow:

`specify -> clarify -> plan -> tasks -> analyze -> implement -> converge`

Implementation is not complete until the code materially matches the approved spec/plan/tasks and convergence has no unresolved material gap.

## Bug lifecycle

Follow:

`bug.assess -> bug.fix -> bug.test`

Do not jump directly from a bug report to a source patch when the bug workflow applies.

## Scope and trading safety

Stay within the active task or assessed remediation. Avoid unrelated refactors.

Any change to live-order capability, exchange credentials, leverage, sizing, risk limits, stop-loss/take-profit behavior, order routing, or execution safety gates requires explicit scope in the active spec.

Default new execution behavior to read-only, dry-run, or paper mode unless the approved spec explicitly requires live execution.

## Verification

Use the repository's existing checks:

- `pytest -q`
- `cd apps/web && npm run build`
- Spec governance check when applicable

Summarize verification in the pull request.

## Legacy material

`.superpowers/sdd/` remains historical evidence. New authoritative specs belong in `specs/`; new bug evidence belongs in `.specify/bugs/`.