# Spec Kit Development Workflow

GitHub Spec Kit is the primary software-development workflow for this repository.

## Bootstrap

This repository pins Spec Kit to `v1.0.6`.

```bash
bash scripts/bootstrap-speckit.sh
```

The bootstrap script:

1. installs `specify-cli` v1.0.6;
2. initializes Codex skills in the current repository;
3. installs the GitHub Copilot integration;
4. installs the official `bug` extension.

## Feature workflow

Use this sequence for material feature work:

```text
specify
  -> clarify
  -> plan
  -> tasks
  -> analyze
  -> implement
  -> converge
  -> pull request
  -> CI
  -> merge
```

Authoritative artifacts live in:

```text
specs/<NNN>-<feature>/
├── spec.md
├── plan.md
└── tasks.md
```

The feature workflow is complete only when implementation materially matches the approved artifacts and `speckit.converge` reports no unresolved material gap.

## Bug workflow

Use the official Spec Kit bug extension:

```text
bug.assess -> bug.fix -> bug.test
```

Each bug lives under:

```text
.specify/bugs/<slug>/
├── assessment.md
├── fix.md
└── test.md
```

`assessment.md` records diagnosis and expected remediation. `fix.md` records the actual change and deviations. `test.md` records verification. Runtime bug PRs on `fix/*` or `bugfix/*` are expected to contain all three reports.

## Codex handoff

Codex reads `AGENTS.md`, then the project constitution and active Spec Kit artifacts.

Preferred handoff wording:

```text
Continue specs/012-news-intelligence from the first incomplete task.
Read .specify/memory/constitution.md, spec.md, plan.md, and tasks.md before editing code.
```

For bugs:

```text
Continue bug slug login-timeout from the current Spec Kit bug stage.
Read the constitution and all existing reports under .specify/bugs/login-timeout/ first.
```

## GitHub Copilot handoff

GitHub Copilot reads `.github/copilot-instructions.md` and uses the same Spec Kit artifacts as Codex. Do not duplicate requirements into Copilot-specific documents.

## Pull-request rules

Runtime-sensitive changes are changes under `apps/`, `btc_core/`, root `Dockerfile*`, root `railway*.toml`, or `pyproject.toml`.

- Feature runtime PR: include a changed `specs/<feature>/` directory with `spec.md`, `plan.md`, and `tasks.md`.
- Bug runtime PR on `fix/*` or `bugfix/*`: include a complete `.specify/bugs/<slug>/` directory with `assessment.md`, `fix.md`, and `test.md`.
- Documentation/process-only PRs do not require a feature spec.

The `Spec Governance` GitHub Action performs this structural check. Existing backend tests and web build remain separate required evidence.

## Trading-system safety

Changes involving live-order capability, exchange credentials, leverage, position sizing, risk limits, SL/TP behavior, order routing, or execution safety gates must be explicitly authorized by the active spec.

Default new execution behavior to read-only, dry-run, or paper mode unless the approved spec explicitly requires live execution.

## Legacy SDD material

`.superpowers/sdd/` remains available as historical evidence for work created before this migration. Do not create new authoritative specs there. New work belongs in `specs/` or `.specify/bugs/`.

## Upgrading Spec Kit

Do not silently float to a newer release. Update `SPEC_KIT_VERSION` in `scripts/bootstrap-speckit.sh`, review upstream release notes, refresh integrations intentionally, run repository verification, and document the upgrade in a PR.
