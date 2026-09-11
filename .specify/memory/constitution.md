# BTC Repository Constitution

## Purpose

This constitution governs development in `winza125-sitticun/Btc`. GitHub Spec Kit artifacts are the authoritative description of intended behavior and implementation work.

## I. Spec-first development

Material feature work MUST begin with an active directory under `specs/<NNN>-<feature>/` containing `spec.md`, `plan.md`, and `tasks.md` before runtime source changes are considered complete.

The normal lifecycle is:

`specify -> clarify -> plan -> tasks -> analyze -> implement -> converge -> PR -> CI -> merge`

The active spec defines what and why. The plan defines how. Tasks define executable progress. Source code implements these artifacts.

## II. Bug evidence before patching

Bug fixes MUST use the official Spec Kit bug workflow unless the change is documentation-only or process-only:

`bug.assess -> bug.fix -> bug.test`

Evidence lives under:

```text
.specify/bugs/<slug>/assessment.md
.specify/bugs/<slug>/fix.md
.specify/bugs/<slug>/test.md
```

An agent MUST NOT jump directly from an unassessed bug report to a source patch when the bug workflow applies.

## III. One source of truth for agents

Codex and GitHub Copilot MUST use the same constitution, spec, plan, tasks, and bug artifacts. Agent-specific copies of requirements are prohibited.

Before editing runtime code, an agent MUST read:

1. `.specify/memory/constitution.md`
2. the active `spec.md`
3. the active `plan.md`
4. the active `tasks.md`

For a bug, the agent MUST also read the reports in `.specify/bugs/<slug>/` appropriate to the current stage.

## IV. Verification is part of implementation

Work is not complete because code was written. Changes MUST be verified by tests/builds appropriate to the touched area.

Repository baseline verification includes:

- Backend: `pytest -q`
- Web: `npm run build` from `apps/web`
- Spec governance: `python scripts/check_spec_governance.py <base> <head>` when applicable
- Spec convergence: run `speckit.converge` for feature work and resolve material gaps before declaring completion

Verification results MUST be summarized in the pull request.

## V. Trading safety is non-negotiable

This repository can affect cryptocurrency futures-trading decisions. Any change involving live-order capability, exchange credentials, leverage, position sizing, risk limits, stop-loss/take-profit logic, order routing, or execution safety gates MUST be explicitly authorized by the active spec.

New execution behavior defaults to read-only, dry-run, or paper mode unless the approved spec explicitly requires live execution.

AI analysis, confidence scores, and LONG/SHORT recommendations are advisory unless an approved spec defines a separate execution contract with explicit safeguards.

Safety-relevant behavior changed by a task MUST have corresponding automated tests or a documented, reproducible verification method.

## VI. Scope discipline

Agents MUST implement only the active spec/task or assessed bug remediation. Unrelated refactors, dependency changes, architecture changes, or behavior changes require a separate spec unless necessary to complete the approved work and documented as a deviation.

## VII. Pull-request governance

Runtime changes under `apps/`, `btc_core/`, and production/deployment configuration MUST be accompanied by Spec Kit artifacts.

Feature PRs require a complete active feature directory containing `spec.md`, `plan.md`, and `tasks.md`.

Bug PRs on `fix/*` or `bugfix/*` branches require complete `assessment.md`, `fix.md`, and `test.md` reports under `.specify/bugs/<slug>/`.

CI and Spec governance checks MUST pass before merge unless the repository owner explicitly records an exception in the PR.

## VIII. Legacy SDD material

`.superpowers/sdd/` is retained as historical implementation evidence. New authoritative specs MUST NOT be created there. Historical reports may be referenced by a Spec Kit artifact when useful.

## IX. Reproducible tooling

The repository bootstrap pins GitHub Spec Kit to `v1.0.6`. Upgrades MUST be intentional, documented, and reviewed because generated agent integrations and workflow behavior can change between versions.

## Governance

This constitution is authoritative for repository development unless an explicit owner-approved amendment changes it. Amendments must explain the reason, compatibility impact, and any required updates to agent instructions or CI governance.