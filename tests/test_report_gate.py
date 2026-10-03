"""Contract tests for the optional final fleet health gate."""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment

ROLE_DIR = Path(__file__).resolve().parent.parent / "roles" / "vitals_report"


def _gate_tasks():
    return yaml.safe_load((ROLE_DIR / "tasks" / "gate.yml").read_text(encoding="utf-8"))


def _render(expr: str, **context: object) -> str:
    return Environment().from_string(expr).render(**context).strip()


def test_gate_is_disabled_by_default_and_has_zero_threshold() -> None:
    defaults = yaml.safe_load((ROLE_DIR / "defaults" / "main.yml").read_text(encoding="utf-8"))

    assert defaults["linux_vitals_fail_on_status"] == ""
    assert defaults["linux_vitals_fail_threshold_count"] == 0


def test_gate_runs_after_notifications() -> None:
    tasks = yaml.safe_load((ROLE_DIR / "tasks" / "main.yml").read_text(encoding="utf-8"))

    included = [task["ansible.builtin.include_tasks"]["file"] for task in tasks]
    assert included[-2:] == ["notify.yml", "gate.yml"]


def test_any_fail_mode_counts_failed_hosts() -> None:
    expr = _gate_tasks()[1]["ansible.builtin.set_fact"]["linux_vitals_gate_failure_count"]

    rendered = _render(
        expr,
        linux_vitals_summary={"critical_error_count": 3, "regressed_count": 1},
        linux_vitals_fail_on_status="any_fail",
        linux_vitals_phase="adhoc",
    )

    assert int(rendered) == 3


def test_regression_mode_counts_only_postcheck_regressions() -> None:
    expr = _gate_tasks()[1]["ansible.builtin.set_fact"]["linux_vitals_gate_failure_count"]
    summary = {"critical_error_count": 5, "regressed_count": 2}

    postcheck = _render(
        expr,
        linux_vitals_summary=summary,
        linux_vitals_fail_on_status="regression",
        linux_vitals_phase="postcheck",
    )
    adhoc = _render(
        expr,
        linux_vitals_summary=summary,
        linux_vitals_fail_on_status="regression",
        linux_vitals_phase="adhoc",
    )

    assert int(postcheck) == 2
    assert int(adhoc) == 0


def test_threshold_allows_count_at_threshold_and_fails_above_it() -> None:
    expr = _gate_tasks()[2]["ansible.builtin.set_fact"]["linux_vitals_gate_should_fail"]

    at_threshold = _render(
        expr,
        linux_vitals_fail_on_status="any_fail",
        linux_vitals_gate_failure_count=2,
        linux_vitals_fail_threshold_count=2,
    )
    above_threshold = _render(
        expr,
        linux_vitals_fail_on_status="any_fail",
        linux_vitals_gate_failure_count=3,
        linux_vitals_fail_threshold_count=2,
    )

    assert at_threshold == "False"
    assert above_threshold == "True"


def test_threshold_must_be_a_non_negative_whole_number() -> None:
    expr = _gate_tasks()[0]["ansible.builtin.assert"]["that"][1]
    env = Environment()
    # Ansible's `match` test, which plain Jinja lacks.
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None

    def accepts(threshold: object) -> bool:
        rendered = env.from_string("{{ " + expr + " }}").render(
            linux_vitals_fail_threshold_count=threshold
        )
        return rendered.strip() == "True"

    for valid in (0, 2, "3"):
        assert accepts(valid), valid
    for invalid in ("two", "", 2.5, "2.5", -1, "-1"):
        assert not accepts(invalid), invalid
