# Spec Kit Primary Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Spec Kit the mandatory source-of-truth workflow for features, bugs, Codex handoffs, GitHub Copilot handoffs, and pull-request governance in the BTC repository.

**Architecture:** Keep runtime code untouched. Add repository-level Spec Kit artifacts, agent instructions, a pinned bootstrap script, a structural PR governance checker with tests, and GitHub workflow/template integration. Preserve `.superpowers/sdd/` as legacy evidence while routing all new work to `specs/` or `.specify/bugs/`.

**Tech Stack:** GitHub Spec Kit v1.0.6, Bash, Python 3.12, pytest, GitHub Actions, Markdown.

**Spec:** `docs/superpowers/specs/2026-09-11-spec-kit-primary-workflow-design.md`

## Global Constraints

- Do not modify trading runtime behavior as part of this migration.
- Keep existing CI backend tests and web build intact.
- New feature requirements live under `specs/`; bug evidence lives under `.specify/bugs/`.
- `.superpowers/sdd/` is retained and explicitly marked legacy for new work.
- Spec Kit is pinned to v1.0.6 for reproducible bootstrap behavior.
- Runtime safety changes require explicit spec coverage.

---

### Task 1: Bootstrap authoritative Spec Kit artifacts

**Files:**
- Create: `.specify/memory/constitution.md`
- Create: `specs/001-spec-kit-primary-workflow/spec.md`
- Create: `specs/001-spec-kit-primary-workflow/plan.md`
- Create: `specs/001-spec-kit-primary-workflow/tasks.md`

**Interfaces:**
- Consumes: approved workflow design.
- Produces: the repository constitution and the first canonical feature artifact set.

- [ ] **Step 1:** Write the BTC constitution with source-of-truth, testing, safety, branch/PR, and agent-handoff rules.
- [ ] **Step 2:** Create the bootstrap feature `spec.md` with acceptance criteria for feature, bug, and handoff workflows.
- [ ] **Step 3:** Create `plan.md` describing repository-only changes and structural governance.
- [ ] **Step 4:** Create `tasks.md` that maps one-to-one to this migration and marks tasks only after verification.
- [ ] **Step 5:** Commit with `docs: establish Spec Kit source of truth`.

### Task 2: Add Codex/Copilot entry points and reproducible bootstrap

**Files:**
- Create: `AGENTS.md`
- Create: `.github/copilot-instructions.md`
- Create: `scripts/bootstrap-speckit.sh`
- Create: `docs/SPEC_KIT_WORKFLOW.md`

**Interfaces:**
- Consumes: `.specify/memory/constitution.md` and active feature/bug artifacts.
- Produces: identical workflow instructions for Codex and GitHub Copilot plus a reproducible setup command.

- [ ] **Step 1:** In `AGENTS.md`, require reading the constitution and active artifacts before source edits.
- [ ] **Step 2:** Mirror the same authoritative paths and safety rules in Copilot instructions.
- [ ] **Step 3:** Add an executable bootstrap script containing:

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v1.0.6
specify init --here --force --non-interactive --integration codex --integration-options "--skills"
specify integration install copilot
specify extension add bug
```

- [ ] **Step 4:** Document feature, bug, handoff, upgrade, and legacy-SDD flows in `docs/SPEC_KIT_WORKFLOW.md`.
- [ ] **Step 5:** Commit with `docs: add Spec Kit agent workflow`.

### Task 3: Enforce Spec artifacts for runtime pull requests

**Files:**
- Create: `scripts/check_spec_governance.py`
- Create: `tests/test_spec_governance.py`
- Create: `.github/workflows/spec-governance.yml`

**Interfaces:**
- Consumes: two git refs supplied by GitHub Actions.
- Produces: exit code 0 for compliant PRs; non-zero with actionable errors for missing artifacts.

- [ ] **Step 1: Write failing tests** covering documentation-only changes, compliant feature changes, feature changes missing artifacts, compliant bug changes, and bug changes missing reports.

```python
from scripts.check_spec_governance import validate_changes


def test_feature_runtime_change_requires_complete_spec(tmp_path):
    errors = validate_changes(
        changed_files={"btc_core/service.py", "specs/012-example/spec.md"},
        branch="codex/example",
        root=tmp_path,
    )
    assert errors
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest -q tests/test_spec_governance.py
```

Expected: import or assertion failure because the checker does not exist yet.

- [ ] **Step 3: Implement minimal checker** with `validate_changes(changed_files: set[str], branch: str, root: Path) -> list[str]` and a CLI that derives changed files from `git diff --name-only <base>...<head>`.
- [ ] **Step 4: Run checker tests**

```bash
pytest -q tests/test_spec_governance.py
```

Expected: all governance tests pass.

- [ ] **Step 5:** Add `spec-governance.yml` on `pull_request`, `fetch-depth: 0`, Python 3.12, and run `python scripts/check_spec_governance.py "${{ github.event.pull_request.base.sha }}" "${{ github.event.pull_request.head.sha }}"`.
- [ ] **Step 6:** Commit with `ci: enforce Spec Kit governance`.

### Task 4: Make pull requests and README expose the workflow

**Files:**
- Create: `.github/pull_request_template.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: workflow documentation.
- Produces: visible contributor entry points and review checklist.

- [ ] **Step 1:** Add PR fields for change type, spec/bug path, completed tests, convergence result, and safety impact.
- [ ] **Step 2:** Append a concise `Development workflow` section to README linking `docs/SPEC_KIT_WORKFLOW.md` and identifying Spec Kit as authoritative.
- [ ] **Step 3:** Commit with `docs: expose Spec Kit workflow in pull requests`.

### Task 5: Verify and prepare PR

**Files:**
- Modify: `specs/001-spec-kit-primary-workflow/tasks.md` only to mark verified items complete.

**Interfaces:**
- Consumes: all migration files.
- Produces: reviewable PR with evidence from CI.

- [ ] **Step 1:** Run `pytest -q` and confirm existing backend plus governance tests pass.
- [ ] **Step 2:** Run `npm run build` in `apps/web` and confirm success.
- [ ] **Step 3:** Run governance checker against `main...HEAD` and confirm this process-only migration passes.
- [ ] **Step 4:** Create a pull request from `codex/spec-kit-primary-workflow` to `main`.
- [ ] **Step 5:** Inspect GitHub Actions results; do not report completion unless required jobs pass.
- [ ] **Step 6:** Update `tasks.md` verification checkboxes and commit only after evidence is available.