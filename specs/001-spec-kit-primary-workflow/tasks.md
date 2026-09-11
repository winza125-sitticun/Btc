# Tasks: Spec Kit Primary Workflow

## T1 — Establish authoritative artifacts

- [x] Add approved workflow design document.
- [x] Add implementation plan document.
- [x] Add `.specify/memory/constitution.md`.
- [x] Add `spec.md` for this bootstrap feature.
- [x] Add `plan.md` for this bootstrap feature.
- [x] Add this `tasks.md`.

## T2 — Add shared agent workflow

- [x] Add `AGENTS.md` for Codex.
- [x] Add `.github/copilot-instructions.md` for GitHub Copilot.
- [x] Add `scripts/bootstrap-speckit.sh` pinned to Spec Kit v1.0.6.
- [x] Add `docs/SPEC_KIT_WORKFLOW.md`.

## T3 — Add PR governance

- [x] Add `scripts/check_spec_governance.py`.
- [x] Add governance unit tests.
- [x] Add `.github/workflows/spec-governance.yml`.
- [x] Verify governance tests pass in GitHub Actions.

## T4 — Expose workflow to reviewers/contributors

- [x] Add `.github/pull_request_template.md`.
- [x] Add README development-workflow entry point.

## T5 — Final verification

- [x] Confirm repository backend CI passes.
- [x] Confirm web build CI passes.
- [x] Confirm Spec governance CI passes.
- [x] Confirm PR diff contains no runtime trading behavior changes.
- [x] Record convergence/review result and native-bootstrap caveat in PR #30.
