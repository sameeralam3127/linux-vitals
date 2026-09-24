# Working on sameeralam3127.linux_vitals

You are helping the maintainer move this Ansible collection from "well-engineered solo project" to "safe for org-wide adoption".

## Ground truth
- `docs/roadmap.md` is the plan of record. Read it before any phase. Its ordering principle is:
  correctness -> scalability -> detection coverage -> integrations -> compliance -> contributors.
  Never trade correctness for features.
- `docs/architecture.md`, `docs/threat-model.md`, `docs/runbook.md`, `CHANGELOG.md`, and each role's README must stay accurate. The roadmap's own rule applies: a change that adds a role, finding field, variable, or schema version updates the architecture doc **in the same change**.
- Declared floor: ansible-core 2.16 (`meta/runtime.yml`). Python 3.10+.

## Rules
1. One GitHub issue = one branch = one PR. Branch name: `fix/<issue>-<slug>` or `feat/<issue>-<slug>`. Use `gh` to read the issue first: `gh issue view <n> --comments`.
2. Before writing code, restate the issue's acceptance criteria and list the files you will touch. Stop and ask if the issue is ambiguous.
3. Every behaviour change needs a test in `tests/` (pytest fixtures pattern already used there) and, where it touches hosts, a Molecule verify assertion.
4. Run the full validation before declaring done:
   pre-commit run --all-files
   ANSIBLE_LOCAL_TEMP=.ansible/tmp ANSIBLE_REMOTE_TEMP=.ansible/tmp ansible-lint roles/ playbooks/ molecule/ demo/
   ansible-playbook playbooks/healthcheck.yml --syntax-check
   pytest -q
   If Docker is available, also run the Molecule scenario(s) for the distros you touched.
5. Update `CHANGELOG.md` under `[Unreleased]` (Keep a Changelog), move the issue to **Shipped** in `docs/roadmap.md` when closed.
6. Never: push tags, publish to Galaxy, merge PRs, close issues, or change repo settings. Prepare them and tell me the exact command to run.
7. A check that cannot run must report `unknown`, never a pass. A wrong check is worse than a missing one.
8. Variable names in docs must match `defaults/main.yml` and `meta/argument_specs.yml` exactly — Ansible silently accepts undefined variables.
9. Keep `no_log` on anything that can carry credentials; don't weaken existing redaction tests.
10. Don't refactor outside the issue's scope. Note unrelated problems at the end of your summary instead.

## End-of-task summary format
- What changed (files), why, how it was tested
- Anything verified vs. assumed
- Follow-ups or new issues worth filing (draft `gh issue create` commands, don't run them)
