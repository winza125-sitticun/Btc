# Feature Specification: Spec Kit Primary Workflow

## Problem

The repository already uses AI-assisted development, pull requests, CI, and historical SDD reports, but there is no single authoritative workflow shared by Codex and GitHub Copilot. Feature work and bug fixes can therefore bypass a structured requirements/verification trail or duplicate context across agents.

## Goal

Make GitHub Spec Kit the repository's primary development workflow without changing trading runtime behavior.

## User stories

### US1 — Feature work is spec-driven

As the repository owner, I want every material feature to have one canonical Spec Kit artifact set so Codex, Copilot, and reviewers work from the same requirements.

**Acceptance criteria**
- New feature work uses `specs/<NNN>-<feature>/spec.md`, `plan.md`, and `tasks.md`.
- Agent instructions require reading the constitution and active artifacts before runtime edits.
- Feature work reaches `speckit.converge` before being declared complete.

### US2 — Bug fixes are evidence-driven

As the repository owner, I want bugs assessed and verified before closure so AI agents do not jump directly from symptom to patch.

**Acceptance criteria**
- The repository documents and bootstraps the official Spec Kit bug extension.
- A bug uses `.specify/bugs/<slug>/assessment.md`, `fix.md`, and `test.md`.
- Pull-request governance rejects runtime bug branches missing one or more required reports.

### US3 — Codex and Copilot share one source of truth

As the repository owner, I want to hand work between Codex and GitHub Copilot without rewriting project context.

**Acceptance criteria**
- `AGENTS.md` and `.github/copilot-instructions.md` point to the same authoritative artifacts.
- No agent-specific requirements copies are required.
- A documented handoff can identify an active spec/bug and first incomplete task instead of restating requirements.

### US4 — Pull requests prove workflow compliance

As a reviewer, I want CI to catch runtime PRs that bypass the required Spec Kit artifacts.

**Acceptance criteria**
- Documentation/process-only PRs can pass without a feature spec.
- Runtime feature PRs require a changed complete `specs/<feature>/` artifact set.
- Runtime bug PRs on `fix/*` or `bugfix/*` require complete bug reports.
- Existing backend test and web-build jobs remain unchanged.

### US5 — Historical work remains available

As the repository owner, I want existing `.superpowers/sdd/` reports preserved for traceability while preventing new specs from being split between two systems.

**Acceptance criteria**
- No historical `.superpowers/sdd/` content is deleted.
- Documentation explicitly marks `.superpowers/sdd/` as legacy evidence for new work.
- New authoritative work begins in `specs/` or `.specify/bugs/`.

## Non-functional requirements

- Pin Spec Kit to `v1.0.6` in the bootstrap script.
- Use repository-native Python 3.12/pytest for governance tests.
- Keep governance structural and deterministic; it must not attempt semantic scoring of requirement quality.
- Do not modify trading logic, APIs, database schemas, workers, or frontend runtime behavior in this migration.

## Safety requirements

Any future work that changes live order execution, credentials, leverage, sizing, risk limits, SL/TP behavior, routing, or safety gates must explicitly state that scope in the active spec. New execution behavior defaults to read-only/dry-run/paper mode unless explicitly approved.

## Out of scope

- Implementing a new trading strategy.
- Changing market/news workers.
- Changing current deploy targets.
- Rewriting historical SDD reports into Spec Kit format.
- Automatically merging PRs.
