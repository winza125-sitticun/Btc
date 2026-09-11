## Change type

- [ ] Feature
- [ ] Bug fix
- [ ] Documentation / process only

## Spec Kit source of truth

Feature spec path: `specs/...`

Bug evidence path: `.specify/bugs/...`

- [ ] I read `.specify/memory/constitution.md`.
- [ ] Feature work includes `spec.md`, `plan.md`, and `tasks.md`, or this PR is not feature runtime work.
- [ ] Bug runtime work includes `assessment.md`, `fix.md`, and `test.md`, or this PR is not a bug runtime change.

## Implementation status

- [ ] Tasks for this PR are complete.
- [ ] Scope matches the approved spec/assessment.
- [ ] Unrelated refactors were not included.

## Verification

- [ ] `pytest -q`
- [ ] `cd apps/web && npm run build`
- [ ] Spec Governance check
- [ ] `speckit.converge` has no unresolved material gap, or convergence is not applicable to this PR.

Verification notes:

<!-- Record exact commands/results or explain why a check is not applicable. -->

## Trading safety impact

- [ ] No change to live-order capability, credentials, leverage, sizing, risk limits, SL/TP behavior, routing, or execution safety gates.
- [ ] Safety-impacting behavior is explicitly authorized by the active spec and covered by verification.

Safety notes:

<!-- Describe any safety-relevant change. Leave concise evidence even when the impact is none. -->

## Handoff

Next active spec/bug and task, if work continues after this PR:

<!-- Example: specs/012-news-intelligence — continue from T4 -->
