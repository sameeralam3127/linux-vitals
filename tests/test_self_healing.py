"""Tests for the `vitals_heal` self-healing task changes.

These exercise the exact production tasks from
`roles/vitals_heal/tasks/main.yml` -- extracted straight out of the YAML so
the tests run the real Jinja2 expressions rather than a hand-copied
duplicate -- through `ansible-playbook`, with `ansible_facts.services` and
the `systemctl is-enabled` / restart results faked via `set_fact`. This lets
the logic be verified without ever invoking a real `systemctl` command or
restarting anything on the host running the tests.

See CHANGELOG.md ("Self-healing never restarted anything") and
docs/architecture.md for the bug these tasks fix.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

HEAL_MAIN = REPO_ROOT / "roles" / "vitals_heal" / "tasks" / "main.yml"


def _heal_block_tasks() -> list[dict]:
    document = yaml.safe_load(HEAL_MAIN.read_text(encoding="utf-8"))
    # main.yml is a single top-level task with a `block:` of sub-tasks.
    return document[0]["block"]


def _task_named(name: str) -> dict:
    for task in _heal_block_tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {HEAL_MAIN}")


def _run_playbook(tmp_path: Path, tasks: list[dict]) -> dict:
    playbook = [
        {
            "name": "Exercise vitals_heal logic in isolation",
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "vars": {
                "output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}",
            },
            "tasks": tasks,
        }
    ]
    playbook_path = tmp_path / "self_healing_case.yml"
    playbook_path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(playbook_path)],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    return json.loads((tmp_path / "self_healing.json").read_text(encoding="utf-8"))


def _dump_task(dest_vars: dict[str, str]) -> dict:
    return {
        "name": "Write results for assertion",
        "ansible.builtin.copy": {
            "content": (
                "{{ "
                + "{"
                + ", ".join(f"'{key}': {expr}" for key, expr in dest_vars.items())
                + "}"
                + " | to_nice_json }}\n"
            ),
            "dest": "{{ output_dir }}/self_healing.json",
            "mode": "0644",
        },
    }


# ---------------------------------------------------------------------------
# "Identify failed services" + "Keep only the failed services that are
# enabled at boot"
# ---------------------------------------------------------------------------

def _run_failed_service_selection(
    tmp_path: Path,
    services: dict,
    enabled_stdouts: dict[str, str],
) -> dict:
    identify_task = _task_named("Identify failed services")
    keep_enabled_task = _task_named("Keep only the failed services that are enabled at boot")

    tasks = [
        {
            "name": "Seed service_facts for the scenario under test",
            "ansible.builtin.set_fact": {
                "ansible_facts": {
                    "services": services,
                    "service_mgr": "systemd",
                },
            },
        },
        identify_task,
        {
            "name": "Fake the systemctl is-enabled results for the scenario under test",
            "ansible.builtin.set_fact": {
                "linux_vitals_enabled_checks": {
                    "results": [
                        {"item": name, "stdout": stdout}
                        for name, stdout in enabled_stdouts.items()
                    ],
                },
            },
        },
        keep_enabled_task,
        _dump_task(
            {
                "failed_services": "linux_vitals_failed_services",
                "failed_enabled_services": "linux_vitals_failed_enabled_services",
            }
        ),
    ]
    return _run_playbook(tmp_path, tasks)


def test_new_service_facts_schema_identifies_and_heals_the_enabled_service(
    tmp_path: Path,
) -> None:
    # service_facts now reports a failed unit as state "stopped" with
    # status "failed" -- this is the exact shape that used to make no unit
    # match both the old state=="failed" AND status search('enabled') checks.
    result = _run_failed_service_selection(
        tmp_path,
        services={"molecule-flaky.service": {"state": "stopped", "status": "failed"}},
        enabled_stdouts={"molecule-flaky.service": "enabled\n"},
    )

    assert result["failed_services"] == ["molecule-flaky.service"]
    assert result["failed_enabled_services"] == ["molecule-flaky.service"]


def test_failed_but_disabled_service_is_excluded_from_healing(tmp_path: Path) -> None:
    result = _run_failed_service_selection(
        tmp_path,
        services={"foo.service": {"state": "stopped", "status": "failed"}},
        enabled_stdouts={"foo.service": "disabled\n"},
    )

    assert result["failed_services"] == ["foo.service"]
    assert result["failed_enabled_services"] == []


def test_legacy_state_failed_schema_is_still_recognised(tmp_path: Path) -> None:
    # Older ansible-core reported the unit-file state as "failed" directly;
    # both schemas must keep working.
    result = _run_failed_service_selection(
        tmp_path,
        services={"legacy.service": {"state": "failed"}},
        enabled_stdouts={"legacy.service": "enabled\n"},
    )

    assert result["failed_services"] == ["legacy.service"]
    assert result["failed_enabled_services"] == ["legacy.service"]


def test_service_matching_both_conditions_is_not_duplicated(tmp_path: Path) -> None:
    # A unit that happens to satisfy both the state=="failed" and the
    # status=="failed" branches must appear once, not twice (the `| unique`
    # filter).
    result = _run_failed_service_selection(
        tmp_path,
        services={"both.service": {"state": "failed", "status": "failed"}},
        enabled_stdouts={"both.service": "enabled\n"},
    )

    assert result["failed_services"] == ["both.service"]


def test_static_units_are_not_treated_as_enabled(tmp_path: Path) -> None:
    # `systemctl is-enabled` exits 0 for static/indirect/masked units too, so
    # the filter only accepts stdout that actually starts with "enabled".
    result = _run_failed_service_selection(
        tmp_path,
        services={"static.service": {"state": "stopped", "status": "failed"}},
        enabled_stdouts={"static.service": "static\n"},
    )

    assert result["failed_services"] == ["static.service"]
    assert result["failed_enabled_services"] == []


def test_enabled_runtime_units_are_treated_as_enabled(tmp_path: Path) -> None:
    # "enabled-runtime" still starts with "enabled" and should count.
    result = _run_failed_service_selection(
        tmp_path,
        services={"runtime.service": {"state": "stopped", "status": "failed"}},
        enabled_stdouts={"runtime.service": "enabled-runtime\n"},
    )

    assert result["failed_enabled_services"] == ["runtime.service"]


def test_unfixable_service_alongside_a_healable_one_only_the_enabled_one_is_kept(
    tmp_path: Path,
) -> None:
    result = _run_failed_service_selection(
        tmp_path,
        services={
            "molecule-flaky.service": {"state": "stopped", "status": "failed"},
            "molecule-broken.service": {"state": "stopped", "status": "failed"},
        },
        enabled_stdouts={
            "molecule-flaky.service": "enabled\n",
            "molecule-broken.service": "enabled\n",
        },
    )

    assert sorted(result["failed_services"]) == [
        "molecule-broken.service",
        "molecule-flaky.service",
    ]
    assert sorted(result["failed_enabled_services"]) == [
        "molecule-broken.service",
        "molecule-flaky.service",
    ]


def test_no_failed_services_yields_empty_lists(tmp_path: Path) -> None:
    result = _run_failed_service_selection(
        tmp_path,
        services={"healthy.service": {"state": "running", "status": "enabled"}},
        enabled_stdouts={},
    )

    assert result["failed_services"] == []
    assert result["failed_enabled_services"] == []


# ---------------------------------------------------------------------------
# "Summarize self-healing outcomes"
# ---------------------------------------------------------------------------

def _run_summarize_outcomes(
    tmp_path: Path,
    services: dict,
    restart_results: list[dict],
) -> dict:
    summarize_task = _task_named("Summarize self-healing outcomes")

    tasks = [
        {
            "name": "Seed refreshed service_facts for the scenario under test",
            "ansible.builtin.set_fact": {
                "ansible_facts": {"services": services},
            },
        },
        {
            "name": "Seed restart attempts for the scenario under test",
            "ansible.builtin.set_fact": {
                "linux_vitals_restart_attempts": {"results": restart_results},
            },
        },
        summarize_task,
        _dump_task({"healing_results": "linux_vitals_healing_results"}),
    ]
    return _run_playbook(tmp_path, tasks)


def test_service_reported_active_after_restart_is_fixed(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        services={"molecule-flaky.service": {"state": "running"}},
        restart_results=[{"item": "molecule-flaky.service", "failed": False}],
    )

    assert result["healing_results"] == [
        {"service": "molecule-flaky.service", "result": "Fixed"}
    ]


def test_service_still_reporting_failed_status_is_failed_to_fix(tmp_path: Path) -> None:
    # Regression for the diff's added `or current.status == 'failed'` branch:
    # a unit that could not be restarted now shows state "stopped" with
    # status "failed", not state "failed" -- the old elif alone would have
    # fallen through to "Manual Intervention Required" instead.
    result = _run_summarize_outcomes(
        tmp_path,
        services={"molecule-broken.service": {"state": "stopped", "status": "failed"}},
        restart_results=[{"item": "molecule-broken.service", "failed": False}],
    )

    assert result["healing_results"] == [
        {"service": "molecule-broken.service", "result": "Failed to Fix"}
    ]


def test_restart_command_failure_is_manual_intervention_required(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        services={},
        restart_results=[{"item": "unrestartable.service", "failed": True}],
    )

    assert result["healing_results"] == [
        {"service": "unrestartable.service", "result": "Manual Intervention Required"}
    ]


def test_unknown_post_restart_state_is_manual_intervention_required(tmp_path: Path) -> None:
    # Neither active/running nor failed -- e.g. still "activating" -- falls
    # into the catch-all branch rather than being reported as fixed.
    result = _run_summarize_outcomes(
        tmp_path,
        services={"slow.service": {"state": "activating"}},
        restart_results=[{"item": "slow.service", "failed": False}],
    )

    assert result["healing_results"] == [
        {"service": "slow.service", "result": "Manual Intervention Required"}
    ]


def test_multiple_restart_attempts_are_all_summarized(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        services={
            "molecule-flaky.service": {"state": "running"},
            "molecule-broken.service": {"state": "stopped", "status": "failed"},
        },
        restart_results=[
            {"item": "molecule-flaky.service", "failed": False},
            {"item": "molecule-broken.service", "failed": False},
        ],
    )

    assert result["healing_results"] == [
        {"service": "molecule-flaky.service", "result": "Fixed"},
        {"service": "molecule-broken.service", "result": "Failed to Fix"},
    ]
