"""CI must keep testing the ansible-core floor this collection declares (#47).

Two 2.16 failures (#45, #49) reached users through a green CI that only ever
ran the newest core. The floor jobs fix that; these tests stop them from
quietly drifting away from what the collection actually promises:

- the floor CI installs must be the minimum `meta/runtime.yml` declares, so
  raising the floor cannot leave CI testing the old one, or vice versa;
- the floor jobs must exist in both the PR (ci.yml) and Molecule matrices;
- the check branch protection requires must keep its exact name, and must
  fail when a leg it stands for fails. A renamed required check never
  reports, and every PR then waits on it forever.

It also pins when each workflow runs (docs/testing.md, "When tests run"):
pull requests only for ci.yml, Molecule before every release, and both
every weekend.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
MOLECULE_WORKFLOW = WORKFLOWS / "molecule.yml"
RELEASE_WORKFLOW = WORKFLOWS / "release.yml"
WEEKLY_WORKFLOW = WORKFLOWS / "weekly.yml"
MOLECULE_ON_LABEL_WORKFLOW = WORKFLOWS / "molecule-on-label.yml"
FLOOR_CONSTRAINTS = REPO_ROOT / ".github" / "constraints" / "ansible-core-floor.txt"

# The contexts branch protection on `main` requires. Changing a job name means
# changing this list and the repository settings together.
REQUIRED_CHECKS = {"validate"}

# Which workflow and job each matrix lives in.
MATRICES = {
    "checks": (CI_WORKFLOW, "checks"),
    "molecule": (MOLECULE_WORKFLOW, "molecule"),
}


def _declared_floor() -> str:
    runtime = yaml.safe_load((REPO_ROOT / "meta" / "runtime.yml").read_text(encoding="utf-8"))
    match = re.fullmatch(r">=\s*(\d+\.\d+)(?:\.\d+)?", runtime["requires_ansible"].strip())
    assert match, f"unexpected requires_ansible form: {runtime['requires_ansible']!r}"
    return match.group(1)


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(path: Path) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    workflow = _workflow(path)
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), f"{path.name}: expected a mapping of triggers"
    return triggers


def _matrix(name: str) -> list[dict]:
    path, job = MATRICES[name]
    return _workflow(path)["jobs"][job]["strategy"]["matrix"]["include"]


def _needs(job: dict) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def test_floor_constraint_matches_meta_runtime() -> None:
    floor = _declared_floor()
    major, minor = (int(part) for part in floor.split("."))
    pins = [
        line.strip()
        for line in FLOOR_CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("ansible-core")
    ]

    assert pins == [f"ansible-core>={floor},<{major}.{minor + 1}"], (
        f"{FLOOR_CONSTRAINTS.relative_to(REPO_ROOT)} must pin exactly the {floor}.x series "
        f"that meta/runtime.yml declares, got {pins}"
    )


def test_both_matrices_include_a_floor_leg() -> None:
    floor = _declared_floor()
    for name in MATRICES:
        floor_legs = [leg for leg in _matrix(name) if leg.get("tooling") == "floor"]

        assert floor_legs, f"the {name} matrix no longer tests the ansible-core floor"
        for leg in floor_legs:
            assert f"ansible-core {floor}" in leg["name"], (
                f"floor leg {leg['name']!r} does not name the floor it tests ({floor})"
            )


def test_both_pr_legs_lint_and_run_pytest() -> None:
    # Three of the floor's pre-merge catches were 2.16-only, one of them an
    # ansible-lint templating error, so the floor leg lints as well as tests.
    steps = _workflow(CI_WORKFLOW)["jobs"]["checks"]["steps"]
    runs = " ".join(step.get("run", "") for step in steps)

    assert "--syntax-check" in runs
    assert "ansible-lint" in runs
    assert "pytest" in runs


def test_required_checks_exist_in_ci() -> None:
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    names = {job.get("name", key) for key, job in jobs.items()}

    missing = REQUIRED_CHECKS - names
    assert not missing, (
        f"required status check(s) {sorted(missing)} no longer exist in ci.yml; every PR "
        f"would wait on them forever. Rename in branch protection at the same time."
    )


def test_the_required_gate_fails_when_a_leg_fails() -> None:
    # A job whose `needs` failed is skipped, and branch protection counts a
    # skipped check as passing. The gate must run regardless and fail itself.
    gate = _workflow(CI_WORKFLOW)["jobs"]["validate"]

    assert _needs(gate) == {"checks"}
    assert "always()" in str(gate.get("if", "")), "the validate gate must run `if: always()`"
    script = " ".join(step.get("run", "") for step in gate["steps"])
    env = " ".join(str(v) for step in gate["steps"] for v in step.get("env", {}).values())
    assert "needs.checks.result" in env
    assert '!= "success"' in script and "exit 1" in script


def test_pr_ci_runs_on_pull_requests_and_not_on_push() -> None:
    triggers = _triggers(CI_WORKFLOW)

    assert "pull_request" in triggers
    assert "push" not in triggers, "ci.yml must not run on push; see docs/testing.md"
    assert "workflow_call" in triggers, "weekly.yml calls ci.yml"


def test_no_molecule_job_left_in_pr_ci() -> None:
    assert "molecule" not in _workflow(CI_WORKFLOW)["jobs"]


def test_molecule_on_a_pull_request_runs_only_for_its_label() -> None:
    triggers = _triggers(MOLECULE_ON_LABEL_WORKFLOW)
    job = _workflow(MOLECULE_ON_LABEL_WORKFLOW)["jobs"]["molecule"]

    assert triggers == {"pull_request": {"types": ["labeled"]}}, (
        "pull_request only: pull_request_target would run fork code with a write token"
    )
    assert job["if"] == "github.event.label.name == 'run-molecule'"
    assert job["uses"] == "./.github/workflows/molecule.yml"
    assert "${{" not in job["name"], "a skipped job shows an expression name unevaluated"
    assert "workflow_call" in _triggers(MOLECULE_WORKFLOW)


def test_no_workflow_uses_pull_request_target() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        assert "pull_request_target" not in _triggers(path), path.name


def test_release_publishes_only_after_molecule_passes() -> None:
    jobs = _workflow(RELEASE_WORKFLOW)["jobs"]

    assert jobs["molecule"]["uses"] == "./.github/workflows/molecule.yml"
    assert "molecule" in _needs(jobs["publish"])


def test_weekly_run_tests_main_with_everything() -> None:
    triggers = _triggers(WEEKLY_WORKFLOW)
    jobs = _workflow(WEEKLY_WORKFLOW)["jobs"]

    assert triggers["schedule"], "weekly.yml has no schedule"
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["molecule"]["uses"] == "./.github/workflows/molecule.yml"
    report = jobs["report-failure"]
    assert _needs(report) == {"ci", "molecule"}
    assert "failure()" in report["if"]


def test_ci_pip_installs_require_binary_only() -> None:
    paths = [
        *(
            REPO_ROOT / ".github" / "workflows"
        ).glob("*.yml"),
        *(
            REPO_ROOT / ".github" / "scripts"
        ).glob("*.sh"),
    ]

    for path in paths:
        content = path.read_text(encoding="utf-8")

        # Join shell commands split with a backslash continuation.
        content = content.replace("\\\n", " ")

        for line in content.splitlines():
            if "pip install" not in line:
                continue

            assert "--only-binary :all:" in line, (
                f"{path.relative_to(REPO_ROOT)} contains a pip install "
                f"without '--only-binary :all:': {line.strip()}"
            )
