"""Tests for finding severity classification and the host severity rollup.

Like `test_self_healing.py`, these pull the real tasks straight out of
`roles/vitals_scan/tasks/result.yml` and run them through `ansible-playbook`
with the findings faked via vars, so the assertions exercise the production
Jinja rather than a hand-copied duplicate.

The shipped severity map is read from `roles/vitals_scan/defaults/main.yml`
for the same reason: a test that hard-codes its own map would keep passing
after someone retuned a severity in the role.

See issue #8.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

RESULT_TASKS = REPO_ROOT / "roles" / "vitals_scan" / "tasks" / "result.yml"
SCAN_DEFAULTS = REPO_ROOT / "roles" / "vitals_scan" / "defaults" / "main.yml"

SEVERITY_TASK_NAMES = [
    "Attach a severity to every finding",
    "Roll the findings up into one host severity",
    "Decide whether the host passes at the configured severity threshold",
]


def _defaults() -> dict:
    return yaml.safe_load(SCAN_DEFAULTS.read_text(encoding="utf-8"))


def _severity_tasks() -> list[dict]:
    document = yaml.safe_load(RESULT_TASKS.read_text(encoding="utf-8"))
    by_name = {task.get("name"): task for task in document}
    missing = [name for name in SEVERITY_TASK_NAMES if name not in by_name]
    assert not missing, f"tasks missing from {RESULT_TASKS}: {missing}"
    return [by_name[name] for name in SEVERITY_TASK_NAMES]


def _run(tmp_path: Path, raw_findings: list[dict], **overrides) -> dict:
    defaults = _defaults()
    play_vars = {
        "output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}",
        "linux_vitals_raw_findings": raw_findings,
        "linux_vitals_severity_order": defaults["linux_vitals_severity_order"],
        "linux_vitals_finding_severities": defaults["linux_vitals_finding_severities"],
        "linux_vitals_finding_severity_overrides": defaults[
            "linux_vitals_finding_severity_overrides"
        ],
        "linux_vitals_fail_on_severity": defaults["linux_vitals_fail_on_severity"],
    }
    play_vars.update(overrides)

    dump = {
        "name": "Write results for assertion",
        "ansible.builtin.copy": {
            "content": (
                "{{ {"
                "'findings': linux_vitals_findings, "
                "'severity': linux_vitals_host_severity, "
                "'counts': linux_vitals_severity_counts, "
                "'status': linux_vitals_final_status"
                "} | to_nice_json }}\n"
            ),
            "dest": "{{ output_dir }}/severity.json",
            "mode": "0644",
        },
    }

    playbook = [
        {
            "name": "Exercise finding severity logic in isolation",
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "vars": play_vars,
            "tasks": [*_severity_tasks(), dump],
        }
    ]
    path = tmp_path / "severity_case.yml"
    path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(path)],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )
    return json.loads((tmp_path / "severity.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_findings_are_classified_from_the_shipped_map(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {"id": "ram_critical", "message": "RAM usage is critical"},
            {"id": "reboot_required", "message": "System reboot is required"},
            {"id": "log_errors", "message": "Recent logs contain errors"},
        ],
    )

    by_id = {finding["id"]: finding["severity"] for finding in result["findings"]}
    assert by_id == {
        "ram_critical": "critical",
        "reboot_required": "warning",
        "log_errors": "info",
    }


def test_an_unknown_finding_id_falls_back_to_warning(tmp_path: Path) -> None:
    # A finding added to result.yml but not to the severity map must not vanish
    # or crash the run; warning is the safe middle.
    result = _run(tmp_path, [{"id": "not_in_the_map", "message": "Something new"}])

    assert result["findings"][0]["severity"] == "warning"


def test_overrides_are_merged_over_the_map_not_substituted_for_it(
    tmp_path: Path,
) -> None:
    # The finding that is overridden changes; the one that is not keeps its
    # shipped severity. This is what stops an operator's one-line override
    # silently defaulting every other finding to warning.
    result = _run(
        tmp_path,
        [
            {"id": "apparmor_disabled", "message": "AppArmor is disabled"},
            {"id": "ram_critical", "message": "RAM usage is critical"},
        ],
        linux_vitals_finding_severity_overrides={"apparmor_disabled": "info"},
    )

    by_id = {finding["id"]: finding["severity"] for finding in result["findings"]}
    assert by_id["apparmor_disabled"] == "info"
    assert by_id["ram_critical"] == "critical"


def test_the_finding_message_survives_classification(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {
                "id": "service_manual_followup",
                "message": "demo.service requires manual follow-up",
                "subject": "demo.service",
            }
        ],
    )

    finding = result["findings"][0]
    assert finding["message"] == "demo.service requires manual follow-up"
    assert finding["subject"] == "demo.service"
    assert finding["severity"] == "critical"


# ---------------------------------------------------------------------------
# Host rollup
# ---------------------------------------------------------------------------

def test_host_severity_is_the_highest_not_the_alphabetical_maximum(
    tmp_path: Path,
) -> None:
    # The regression this guards: as strings, "critical" < "info" < "warning",
    # so any alphabetical max/sort returns "warning" for a host that has a
    # critical finding -- under-reporting the worst thing on the host.
    result = _run(
        tmp_path,
        [
            {"id": "log_errors", "message": "info-level"},
            {"id": "reboot_required", "message": "warning-level"},
            {"id": "ram_critical", "message": "critical-level"},
        ],
    )

    assert result["severity"] == "critical"


def test_a_warning_only_host_rolls_up_to_warning(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        [
            {"id": "log_errors", "message": "info-level"},
            {"id": "reboot_required", "message": "warning-level"},
        ],
    )

    assert result["severity"] == "warning"


def test_a_host_with_no_findings_has_severity_none(tmp_path: Path) -> None:
    result = _run(tmp_path, [])

    assert result["severity"] == "none"
    assert result["status"] == "Pass"


def test_severity_counts_are_integers_not_strings(tmp_path: Path) -> None:
    # ansible-core 2.16 stores a scalar template result as a string, so the
    # counts are built as one dict-valued template. If that is ever split back
    # into three scalar entries these become "1"/"2" and every numeric
    # comparison downstream silently changes meaning.
    result = _run(
        tmp_path,
        [
            {"id": "ram_critical", "message": "critical-level"},
            {"id": "reboot_required", "message": "warning-level"},
            {"id": "kernel_not_latest", "message": "warning-level"},
        ],
    )

    assert result["counts"] == {"info": 0, "warning": 2, "critical": 1}
    for value in result["counts"].values():
        assert isinstance(value, int)


# ---------------------------------------------------------------------------
# The pass/fail threshold
# ---------------------------------------------------------------------------

def test_the_default_threshold_fails_a_host_on_any_finding(tmp_path: Path) -> None:
    # Backward compatibility: every release before severity existed failed a
    # host that had any finding at all, and the shipped default must keep
    # behaving that way.
    assert _defaults()["linux_vitals_fail_on_severity"] == "info"

    result = _run(tmp_path, [{"id": "log_errors", "message": "info-level"}])

    assert result["status"] == "Fail"


def test_raising_the_threshold_passes_a_host_whose_findings_are_below_it(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        [
            {"id": "log_errors", "message": "info-level"},
            {"id": "reboot_required", "message": "warning-level"},
        ],
        linux_vitals_fail_on_severity="critical",
    )

    assert result["status"] == "Pass"
    # The findings are still reported -- the host is triaged down, not silenced.
    assert len(result["findings"]) == 2
    assert result["severity"] == "warning"


def test_a_raised_threshold_still_fails_a_host_that_reaches_it(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        [
            {"id": "log_errors", "message": "info-level"},
            {"id": "ram_critical", "message": "critical-level"},
        ],
        linux_vitals_fail_on_severity="critical",
    )

    assert result["status"] == "Fail"


def test_the_threshold_is_inclusive_at_its_own_level(tmp_path: Path) -> None:
    # "at or above", not "above": a warning must fail a warning threshold.
    result = _run(
        tmp_path,
        [{"id": "reboot_required", "message": "warning-level"}],
        linux_vitals_fail_on_severity="warning",
    )

    assert result["status"] == "Fail"


def test_an_unrecognised_threshold_falls_back_to_failing_on_anything(
    tmp_path: Path,
) -> None:
    # A typo in group_vars must not silently pass a broken fleet.
    result = _run(
        tmp_path,
        [{"id": "log_errors", "message": "info-level"}],
        linux_vitals_fail_on_severity="moderate",
    )

    assert result["status"] == "Fail"
