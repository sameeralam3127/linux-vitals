"""CI must keep testing the ansible-core floor this collection declares (#47).

Two 2.16 failures (#45, #49) reached users through a green CI that only ever
ran the newest core. The floor jobs fix that; these tests stop them from
quietly drifting away from what the collection actually promises:

- the floor CI installs must be the minimum `meta/runtime.yml` declares, so
  raising the floor cannot leave CI testing the old one, or vice versa;
- the floor jobs must exist in both the validate and molecule matrices;
- the latest-core jobs must keep the exact names branch protection requires.
  A renamed required check never reports, and every PR then waits on it
  forever.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FLOOR_CONSTRAINTS = REPO_ROOT / ".github" / "constraints" / "ansible-core-floor.txt"

# The contexts branch protection on `main` requires. Changing a job name means
# changing this list and the repository settings together.
REQUIRED_CHECKS = {
    "validate",
    "molecule (ubuntu)",
    "molecule (rocky)",
    "molecule (fedora)",
    "molecule (opensuse)",
}


def _declared_floor() -> str:
    runtime = yaml.safe_load((REPO_ROOT / "meta" / "runtime.yml").read_text(encoding="utf-8"))
    match = re.fullmatch(r">=\s*(\d+\.\d+)(?:\.\d+)?", runtime["requires_ansible"].strip())
    assert match, f"unexpected requires_ansible form: {runtime['requires_ansible']!r}"
    return match.group(1)


def _matrix(job: str) -> list[dict]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"][job]["strategy"]["matrix"]["include"]


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
    for job in ("validate", "molecule"):
        floor_legs = [leg for leg in _matrix(job) if leg.get("tooling") == "floor"]

        assert floor_legs, f"the {job} matrix no longer tests the ansible-core floor"
        for leg in floor_legs:
            assert f"ansible-core {floor}" in leg["name"], (
                f"floor leg {leg['name']!r} does not name the floor it tests ({floor})"
            )


def test_latest_core_jobs_keep_their_required_check_names() -> None:
    names = {leg["name"] for job in ("validate", "molecule") for leg in _matrix(job)}

    missing = REQUIRED_CHECKS - names
    assert not missing, (
        f"required status check(s) {sorted(missing)} no longer exist in ci.yml; every PR "
        f"would wait on them forever. Rename in branch protection at the same time."
    )


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
