"""Tests for the `vitals_heal` self-healing task changes.

These exercise the exact production tasks from
`roles/vitals_heal/tasks/main.yml` -- extracted straight out of the YAML so
the tests run the real Jinja2 expressions rather than a hand-copied
duplicate -- through `ansible-playbook`, with `ansible_facts.services` and
the `systemctl is-enabled` / restart results faked via `set_fact`. This lets
the logic be verified without ever invoking a real `systemctl` command or
restarting anything on the host running the tests.

The post-restart verification (#24) is tested two ways: the outcome
derivation with the `systemctl show` results seeded directly, and the real
polling tasks -- `until`, `retries`, the stability window -- run end to end
against a fake `systemctl` on PATH that plays back a scripted sequence of
unit states.

See CHANGELOG.md ("Self-healing never restarted anything") and
docs/architecture.md for the bug these tasks fix.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from test_templates import PLAYBOOK, REPO_ROOT, _ansible_playbook_bin, _base_env

HEAL_MAIN = REPO_ROOT / "roles" / "vitals_heal" / "tasks" / "main.yml"
HEAL_DEFAULTS = REPO_ROOT / "roles" / "vitals_heal" / "defaults" / "main.yml"
RESULT_TASKS = REPO_ROOT / "roles" / "vitals_scan" / "tasks" / "result.yml"


def _heal_block_tasks() -> list[dict]:
    document = yaml.safe_load(HEAL_MAIN.read_text(encoding="utf-8"))
    # main.yml is a single top-level task with a `block:` of sub-tasks.
    return document[0]["block"]


def _task_named(name: str) -> dict:
    for task in _heal_block_tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {HEAL_MAIN}")


def _run_playbook(
    tmp_path: Path,
    tasks: list[dict],
    play_vars: dict | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    playbook = [
        {
            "name": "Exercise vitals_heal logic in isolation",
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "vars": {
                "output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}",
                **(play_vars or {}),
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
        env={**_base_env(tmp_path), **(env or {})},
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
# "Summarize self-healing outcomes" (#24)
#
# The outcome is derived from two `systemctl show` looks -- one once the unit
# has settled, one after the stability window for a unit that came up -- not
# from service_facts. These tests seed those looks directly.
# ---------------------------------------------------------------------------

def _heal_defaults() -> dict:
    return yaml.safe_load(HEAL_DEFAULTS.read_text(encoding="utf-8"))


def _show(
    unit: str,
    active: str,
    sub: str = "running",
    result: str = "success",
    invocation: str = "inv-1",
    restarts: int = 0,
    rc: int = 0,
    stderr: str = "",
    load: str = "loaded",
) -> dict:
    """A registered loop item from `systemctl show --property=...`."""
    lines = [] if rc else [
        f"LoadState={load}",
        f"ActiveState={active}",
        f"SubState={sub}",
        f"Result={result}",
        f"InvocationID={invocation}",
        f"NRestarts={restarts}",
    ]
    return {
        "item": unit,
        "rc": rc,
        "stdout": "\n".join(lines),
        "stdout_lines": lines,
        "stderr": stderr,
        "changed": False,
        "failed": False,
    }


def _attempt(unit: str, failed: bool = False, msg: str = "") -> dict:
    attempt = {"item": unit, "failed": failed, "changed": not failed}
    if msg:
        attempt["msg"] = msg
    return attempt


def _run_summarize_outcomes(
    tmp_path: Path,
    restart_results: list[dict],
    settle_checks: list[dict] | None = None,
    stability_checks: list[dict] | None = None,
) -> dict:
    tasks = [
        {
            "name": "Seed restart attempts and post-restart checks for the scenario under test",
            "ansible.builtin.set_fact": {
                "linux_vitals_restart_attempts": {"results": restart_results},
                "linux_vitals_heal_settle_checks": {"results": settle_checks or []},
                "linux_vitals_heal_stability_checks": {"results": stability_checks or []},
            },
        },
        _task_named("Summarize self-healing outcomes"),
        _task_named("Finalize healing counters"),
        _dump_task(
            {
                "healing_results": "linux_vitals_healing_results",
                "services_healed": "linux_vitals_services_healed",
                "auto_fixed_count": "linux_vitals_auto_fixed_count | int",
            }
        ),
    ]
    return _run_playbook(tmp_path, tasks, play_vars=_heal_defaults())


def _only(result: dict) -> dict:
    assert len(result["healing_results"]) == 1, result["healing_results"]
    return result["healing_results"][0]


def test_unit_that_stays_up_through_the_window_is_fixed(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("molecule-flaky.service")],
        settle_checks=[_show("molecule-flaky.service", "active")],
        stability_checks=[_show("molecule-flaky.service", "active")],
    )

    outcome = _only(result)
    assert outcome["service"] == "molecule-flaky.service"
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Fixed", "fixed", "stayed_active",
    )
    assert outcome["detail"] == "it stayed active for 5 s after the restart"
    assert result["services_healed"] == ["molecule-flaky.service"]
    assert result["auto_fixed_count"] == 1


def test_unit_that_comes_up_then_dies_in_the_window_is_not_fixed(tmp_path: Path) -> None:
    # The race in #24: active when first looked at, dead a few seconds later.
    # The old single look reported this Fixed.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("dies.service")],
        settle_checks=[_show("dies.service", "active")],
        stability_checks=[_show("dies.service", "failed", sub="failed", result="exit-code")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Failed to Fix", "still_failed", "failed",
    )
    assert outcome["detail"] == "it came up, then failed within 5 s (result: exit-code)"
    assert result["services_healed"] == []
    assert result["auto_fixed_count"] == 0


def test_unit_restarted_by_systemd_during_the_window_is_not_fixed(tmp_path: Path) -> None:
    # Active at both looks, but on a different run: it crashed and Restart=
    # brought it back. That is not a restart that held.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("flapping.service")],
        settle_checks=[_show("flapping.service", "active", invocation="aaa", restarts=0)],
        stability_checks=[_show("flapping.service", "active", invocation="bbb", restarts=1)],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Failed to Fix", "still_failed", "restarted_during_check",
    )


def test_a_new_invocation_alone_counts_as_a_restart(tmp_path: Path) -> None:
    # Either the invocation or the restart counter changing is enough.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("flapping.service")],
        settle_checks=[_show("flapping.service", "active", invocation="aaa", restarts=2)],
        stability_checks=[_show("flapping.service", "active", invocation="bbb", restarts=2)],
    )

    assert _only(result)["reason"] == "restarted_during_check"


def test_service_still_failed_after_restart_is_failed_to_fix(tmp_path: Path) -> None:
    # The fast case molecule-broken.service (/bin/false) covers: already
    # failed at the first look, so there is no second look.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("molecule-broken.service")],
        settle_checks=[_show("molecule-broken.service", "failed", sub="failed", result="exit-code")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Failed to Fix", "still_failed", "failed",
    )
    assert outcome["detail"] == "it failed again after the restart (result: exit-code)"


START_JOB_FAILED = (
    "Unable to start service sssd: Job for sssd.service failed because the "
    "control process exited with error code.\n"
    "See 'systemctl status sssd.service' for details.\n"
)


def test_errored_restart_that_leaves_the_unit_failed_is_failed_to_fix(tmp_path: Path) -> None:
    # The common real case: a Type=notify or forking unit whose start job
    # fails outright (sssd with a broken config). `systemctl start` exits
    # non-zero, and the unit is failed. That has always been Failed to Fix;
    # it must not turn into Manual Intervention Required because the restart
    # command reported the failure.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("sssd.service", failed=True, msg=START_JOB_FAILED)],
        settle_checks=[_show("sssd.service", "failed", sub="failed", result="exit-code")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Failed to Fix", "still_failed", "failed",
    )
    # Says the restart reported an error, and carries the first line of it.
    assert outcome["detail"] == (
        "the restart reported an error and it failed again (result: exit-code): "
        "Unable to start service sssd: Job for sssd.service failed because the "
        "control process exited with error code."
    )
    assert result["auto_fixed_count"] == 0


def test_restart_command_failure_is_manual_intervention_required(tmp_path: Path) -> None:
    # The restart errored and the unit's state could not be read at all.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("unrestartable.service", failed=True, msg=START_JOB_FAILED)],
        settle_checks=[
            _show("unrestartable.service", "", rc=1, stderr="Failed to connect to bus: Permission denied")
        ],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Manual Intervention Required", "still_failed", "restart_error",
    )
    # First line of the module's message only.
    assert outcome["detail"] == (
        "the restart command failed: Unable to start service sssd: Job for "
        "sssd.service failed because the control process exited with error code."
    )


def test_errored_restart_with_no_state_check_is_restart_error(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path, [_attempt("unrestartable.service", failed=True, msg=START_JOB_FAILED)]
    )

    assert _only(result)["reason"] == "restart_error"


def test_errored_restart_of_a_missing_unit_is_restart_error(tmp_path: Path) -> None:
    # The unit was removed between selection and restart. Even a stale
    # `failed` ActiveState does not make that a failed start job.
    for active in ("inactive", "failed"):
        result = _run_summarize_outcomes(
            tmp_path,
            [_attempt("gone.service", failed=True, msg="Could not find the requested service gone: host")],
            settle_checks=[_show("gone.service", active, sub="dead", load="not-found")],
        )

        outcome = _only(result)
        assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
            "Manual Intervention Required", "still_failed", "restart_error",
        ), active
        assert outcome["detail"] == (
            "the restart command failed: Could not find the requested service gone: host"
        )


def test_errored_restart_is_never_fixed_even_if_the_unit_is_active(tmp_path: Path) -> None:
    # e.g. the systemctl client timed out while systemd carried on. The
    # remediation step reported failure, so the answer stays pessimistic.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("late.service", failed=True, msg="Unable to start service late: Connection timed out")],
        settle_checks=[_show("late.service", "active")],
        stability_checks=[_show("late.service", "active")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["reason"]) == ("Manual Intervention Required", "restart_error")
    assert result["services_healed"] == []


def test_unit_still_activating_when_the_budget_runs_out_is_unknown(tmp_path: Path) -> None:
    # The check could not complete, so the answer is unknown -- recorded as
    # such rather than as the optimistic reading.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("slow.service")],
        settle_checks=[_show("slow.service", "activating", sub="start")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Manual Intervention Required", "unknown", "not_settled",
    )
    assert outcome["detail"] == "it was still activating (start) when the 30 s settle budget ran out"


def test_unit_that_ends_inactive_is_manual_intervention_required(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("exits-cleanly.service")],
        settle_checks=[_show("exits-cleanly.service", "inactive", sub="dead")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Manual Intervention Required", "still_failed", "inactive",
    )


def test_a_state_that_cannot_be_read_is_unknown(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("unreadable.service")],
        settle_checks=[
            _show("unreadable.service", "", rc=1, stderr="Failed to connect to bus: No such file or directory")
        ],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Manual Intervention Required", "unknown", "check_failed",
    )
    assert "Failed to connect to bus" in outcome["detail"]


def test_a_unit_that_came_up_with_no_second_look_is_never_fixed(tmp_path: Path) -> None:
    # The first look alone is exactly the optimistic single sample #24 is
    # about. Without the post-window look the answer is unknown.
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("molecule-flaky.service")],
        settle_checks=[_show("molecule-flaky.service", "active")],
    )

    outcome = _only(result)
    assert (outcome["result"], outcome["outcome"], outcome["reason"]) == (
        "Manual Intervention Required", "unknown", "check_failed",
    )


def test_an_attempt_with_no_check_at_all_is_never_fixed(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(tmp_path, [_attempt("unchecked.service")])

    assert _only(result)["outcome"] == "unknown"


def test_multiple_restart_attempts_are_all_summarized(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(
        tmp_path,
        [_attempt("molecule-flaky.service"), _attempt("molecule-broken.service")],
        settle_checks=[
            _show("molecule-flaky.service", "active"),
            _show("molecule-broken.service", "failed", sub="failed", result="exit-code"),
        ],
        stability_checks=[_show("molecule-flaky.service", "active")],
    )

    assert [(r["service"], r["result"]) for r in result["healing_results"]] == [
        ("molecule-flaky.service", "Fixed"),
        ("molecule-broken.service", "Failed to Fix"),
    ]
    assert result["services_healed"] == ["molecule-flaky.service"]
    assert result["auto_fixed_count"] == 1


def test_no_restart_attempts_yields_no_outcomes(tmp_path: Path) -> None:
    result = _run_summarize_outcomes(tmp_path, [])

    assert result["healing_results"] == []
    assert result["auto_fixed_count"] == 0


# ---------------------------------------------------------------------------
# The verification tasks end to end (#24)
#
# Runs every task between the restart and the healing counters exactly as
# shipped, against a fake `systemctl` that plays back a scripted sequence of
# states per unit, one entry per call (the last entry repeats). The restart
# itself is seeded, and service_facts becomes a set_fact of what it would
# have read straight after the restarts -- which is all the pre-#24 code
# looked at. The test is written against behaviour rather than task names,
# so run against that code it fails on the units it misreported.
# ---------------------------------------------------------------------------

FAKE_SYSTEMCTL = """#!{python}
import json, os, sys

scenario = json.load(open(os.environ["FAKE_SYSTEMCTL_SCENARIO"]))
calls_path = os.environ["FAKE_SYSTEMCTL_CALLS"]
calls = json.load(open(calls_path)) if os.path.exists(calls_path) else {{}}
args = sys.argv[1:]
if not args or args[0] != "show":
    sys.exit(1)
unit = args[-1]
calls[unit] = calls.get(unit, 0) + 1
json.dump(calls, open(calls_path, "w"))
steps = scenario[unit]
step = steps[min(calls[unit], len(steps)) - 1]
if step.get("rc", 0):
    sys.stderr.write(step.get("stderr", "") + "\\n")
    sys.exit(step["rc"])
print(f"LoadState={{step.get('LoadState', 'loaded')}}")
for key in ("ActiveState", "SubState", "Result", "InvocationID", "NRestarts"):
    print(f"{{key}}={{step.get(key, '')}}")
"""


def _state(active: str, sub: str = "running", result: str = "success",
           invocation: str = "inv-1", restarts: int = 0) -> dict:
    return {
        "ActiveState": active,
        "SubState": sub,
        "Result": result,
        "InvocationID": invocation,
        "NRestarts": restarts,
    }


SETTLE_RETRIES = 3

# unit -> (restart failed?, `systemctl show` sequence, what service_facts
# would have read right after the restarts)
E2E_UNITS = {
    # Active when first looked at, dead after the window: the race in #24.
    "crash.service": (
        False,
        [_state("active", invocation="a"), _state("failed", sub="failed", result="exit-code", invocation="a")],
        {"state": "running", "status": "active"},
    ),
    # Still activating straight after the restart, active from the third look.
    "slow.service": (
        False,
        [_state("activating", sub="start", invocation="b")] * 2 + [_state("active", invocation="b")],
        {"state": "stopped", "status": "activating"},
    ),
    # Active at both looks, but systemd restarted it in between.
    "flap.service": (
        False,
        [_state("active", invocation="c", restarts=0), _state("active", invocation="d", restarts=1)],
        {"state": "running", "status": "active"},
    ),
    # Never settles inside the budget.
    "stuck.service": (
        False,
        [_state("activating", sub="start", invocation="e")],
        {"state": "stopped", "status": "activating"},
    ),
    # Fails at once, like molecule-broken.service.
    "broken.service": (
        False,
        [_state("failed", sub="failed", result="exit-code", invocation="f")],
        {"state": "stopped", "status": "failed"},
    ),
    # Healthy throughout, like molecule-flaky.service.
    "healthy.service": (
        False,
        [_state("active", invocation="g")],
        {"state": "running", "status": "active"},
    ),
    # Goes down through deactivating after the window.
    "dying.service": (
        False,
        [
            _state("active", invocation="h"),
            _state("deactivating", sub="stop-sigterm", invocation="h"),
            _state("failed", sub="failed", result="signal", invocation="h"),
        ],
        {"state": "running", "status": "active"},
    ),
    # `systemctl show` itself fails.
    "unreadable.service": (
        False,
        [{"rc": 1, "stderr": "Failed to connect to bus: No such file or directory"}],
        {"state": "stopped", "status": "failed"},
    ),
    # The restart command errored because the start job failed, leaving a
    # failed unit -- a Type=notify unit that cannot start.
    "errored.service": (
        True,
        [_state("failed", sub="failed", result="exit-code", invocation="i")],
        {"state": "stopped", "status": "failed"},
    ),
    # The restart command errored and the unit is gone.
    "missing.service": (
        True,
        [dict(_state("inactive", sub="dead", invocation=""), LoadState="not-found")],
        {"state": "stopped", "status": "not-found"},
    ),
    # The restart command errored but the unit is up anyway; it must not be
    # sent through the stability window or reported Fixed.
    "errored-up.service": (
        True,
        [_state("active", invocation="j")],
        {"state": "running", "status": "active"},
    ),
}


def _verification_tasks(services: dict) -> list[dict]:
    block = _heal_block_tasks()
    names = [task.get("name") for task in block]
    start = names.index("Attempt one restart for enabled failed services") + 1
    end = names.index("Finalize healing counters") + 1
    tasks = []
    for task in block[start:end]:
        if "ansible.builtin.service_facts" in task:
            tasks.append(
                {
                    "name": "Seed what service_facts reads right after the restarts",
                    "ansible.builtin.set_fact": {"ansible_facts": {"services": services}},
                }
            )
        else:
            tasks.append(task)
    return tasks


def _run_verification_end_to_end(tmp_path: Path) -> tuple[dict, dict]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text(FAKE_SYSTEMCTL.format(python=sys.executable), encoding="utf-8")
    fake.chmod(0o755)

    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps({unit: steps for unit, (_, steps, _) in E2E_UNITS.items()}), encoding="utf-8"
    )
    calls = tmp_path / "calls.json"

    restart_results = [
        _attempt(unit, failed=failed, msg="Unable to start service errored: Job failed." if failed else "")
        for unit, (failed, _, _) in E2E_UNITS.items()
    ]
    services = {unit: facts for unit, (_, _, facts) in E2E_UNITS.items()}

    play_vars = {
        **_heal_defaults(),
        # Fast and deterministic: the fake advances per call, not per second.
        "linux_vitals_heal_settle_retries": SETTLE_RETRIES,
        "linux_vitals_heal_settle_delay": 0,
        "linux_vitals_heal_stability_seconds": 0,
    }
    tasks = [
        {
            "name": "Seed the restart attempts",
            "ansible.builtin.set_fact": {
                "linux_vitals_restart_attempts": {"results": restart_results},
            },
        },
        *_verification_tasks(services),
        _dump_task(
            {
                "healing_results": "linux_vitals_healing_results",
                "services_healed": "linux_vitals_services_healed",
                "auto_fixed_count": "linux_vitals_auto_fixed_count | int",
            }
        ),
    ]
    result = _run_playbook(
        tmp_path,
        tasks,
        play_vars=play_vars,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_SYSTEMCTL_SCENARIO": str(scenario),
            "FAKE_SYSTEMCTL_CALLS": str(calls),
        },
    )
    call_counts = json.loads(calls.read_text(encoding="utf-8")) if calls.exists() else {}
    return result, call_counts


def test_verification_tasks_judge_each_unit_by_its_settled_state(tmp_path: Path) -> None:
    result, _ = _run_verification_end_to_end(tmp_path)
    by_unit = {
        r["service"]: (r["result"], r.get("outcome"), r.get("reason"))
        for r in result["healing_results"]
    }

    assert by_unit == {
        # (a) in #24: up at first, dead a few seconds later -- not fixed.
        "crash.service": ("Failed to Fix", "still_failed", "failed"),
        # (b) in #24: slow to reach active -- fixed once it settles.
        "slow.service": ("Fixed", "fixed", "stayed_active"),
        "flap.service": ("Failed to Fix", "still_failed", "restarted_during_check"),
        "stuck.service": ("Manual Intervention Required", "unknown", "not_settled"),
        "broken.service": ("Failed to Fix", "still_failed", "failed"),
        "healthy.service": ("Fixed", "fixed", "stayed_active"),
        "dying.service": ("Failed to Fix", "still_failed", "failed"),
        "unreadable.service": ("Manual Intervention Required", "unknown", "check_failed"),
        # The start job failed: Failed to Fix, exactly as before #24.
        "errored.service": ("Failed to Fix", "still_failed", "failed"),
        "missing.service": ("Manual Intervention Required", "still_failed", "restart_error"),
        "errored-up.service": ("Manual Intervention Required", "still_failed", "restart_error"),
    }
    assert result["services_healed"] == ["slow.service", "healthy.service"]
    assert result["auto_fixed_count"] == 2


def test_verification_polls_only_as_long_as_it_needs_to(tmp_path: Path) -> None:
    _, calls = _run_verification_end_to_end(tmp_path)

    # Settled at the first look and not up: one look, no second.
    assert calls["broken.service"] == 1
    assert calls["unreadable.service"] == 1
    # Up at the first look: one more look after the window.
    assert calls["healthy.service"] == 2
    assert calls["crash.service"] == 2
    assert calls["flap.service"] == 2
    # Settles on the third look, then the post-window look.
    assert calls["slow.service"] == 4
    # Deactivating at the post-window look, so polled until it settled.
    assert calls["dying.service"] == 3
    # Never settles: the first attempt plus every retry, and then it stops
    # without failing the play.
    assert calls["stuck.service"] == SETTLE_RETRIES + 1
    # A restart that errored gets the first look only -- even one whose unit
    # is up never goes through the stability window.
    assert calls["errored.service"] == 1
    assert calls["missing.service"] == 1
    assert calls["errored-up.service"] == 1


# ---------------------------------------------------------------------------
# From healing outcome to finding (vitals_scan/tasks/result.yml)
# ---------------------------------------------------------------------------

def test_an_unverified_restart_becomes_an_unknown_finding(tmp_path: Path) -> None:
    from test_finding_severity import _defaults as _scan_defaults
    from test_finding_severity import _severity_tasks

    result_tasks = yaml.safe_load(RESULT_TASKS.read_text(encoding="utf-8"))
    build_findings = next(t for t in result_tasks if t.get("name") == "Build host health findings")
    healthy_host = {
        "linux_vitals_ram_status": "OK",
        "linux_vitals_journal_checks": {},
        "linux_vitals_log_errors": 0,
        "linux_vitals_service_status": {
            "sssd": {"service_name": "sssd.service", "state": "running"},
            "systemd_journald": {"service_name": "systemd-journald.service", "state": "running"},
            "time_sync": {"service_name": "chronyd.service", "state": "running"},
        },
        "linux_vitals_reboot_required": False,
        "linux_vitals_latest_kernel_selected": True,
        "linux_vitals_bootloader_default_status": "resolved",
        "linux_vitals_bootloader_default_matches_latest": True,
        "linux_vitals_boot_space_status": "Healthy",
        "linux_vitals_kernel_install_failures": 0,
        "linux_vitals_failed_login_attempts": [],
        "linux_vitals_selinux_status": "Enforcing",
        "linux_vitals_apparmor_status": "enabled",
    }
    scan_defaults = _scan_defaults()
    healing_results = [
        {"service": "ok.service", "result": "Fixed", "outcome": "fixed",
         "reason": "stayed_active", "detail": "it stayed active for 5 s after the restart"},
        {"service": "dead.service", "result": "Failed to Fix", "outcome": "still_failed",
         "reason": "failed", "detail": "it came up, then failed within 5 s (result: exit-code)"},
        {"service": "slow.service", "result": "Manual Intervention Required", "outcome": "unknown",
         "reason": "not_settled",
         "detail": "it was still activating (start) when the 30 s settle budget ran out"},
        # A result from before 2.2.0 has no outcome; it reads as before.
        {"service": "legacy.service", "result": "Manual Intervention Required"},
    ]
    tasks = [
        {
            "name": "Seed a healthy host that ran self-healing",
            "ansible.builtin.set_fact": {
                **healthy_host,
                "ansible_facts": {"os_family": "RedHat"},
                "linux_vitals_healing_results": healing_results,
            },
        },
        build_findings,
        *_severity_tasks(),
        _dump_task(
            {
                "findings": "linux_vitals_findings",
                "unknown_count": "linux_vitals_unknown_count | int",
                "status": "linux_vitals_final_status",
            }
        ),
    ]
    result = _run_playbook(
        tmp_path,
        tasks,
        play_vars={
            key: scan_defaults[key]
            for key in (
                "linux_vitals_severity_order",
                "linux_vitals_finding_severities",
                "linux_vitals_finding_severity_overrides",
                "linux_vitals_fail_on_severity",
            )
        },
    )

    followups = {f["subject"]: f for f in result["findings"] if f["id"] == "service_manual_followup"}
    assert set(followups) == {"dead.service", "slow.service", "legacy.service"}
    assert followups["dead.service"]["status"] == "fail"
    assert "reason" not in followups["dead.service"]
    assert followups["legacy.service"]["status"] == "fail"
    assert followups["slow.service"]["status"] == "unknown"
    assert followups["slow.service"]["reason"] == (
        "it was still activating (start) when the 30 s settle budget ran out"
    )
    assert followups["slow.service"]["message"] == "slow.service requires manual follow-up"
    # Counted like any unknown finding, and it still fails the host.
    assert result["unknown_count"] == 1
    assert result["status"] == "Fail"


# ---------------------------------------------------------------------------
# Rendering (dashboard and JSON)
# ---------------------------------------------------------------------------

def test_dashboard_and_json_say_why_a_restart_was_not_fixed(tmp_path: Path) -> None:
    fixture_vars = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]["vars"]
    result = dict(fixture_vars["fixture_linux_vitals_result"])
    result["healing_results"] = [
        {"service": "chronyd.service", "result": "Fixed", "outcome": "fixed",
         "reason": "stayed_active", "detail": "it stayed active for 5 s after the restart"},
        {"service": "app.service", "result": "Failed to Fix", "outcome": "still_failed",
         "reason": "failed", "detail": "it came up, then failed within 5 s (result: exit-code)"},
        {"service": "sssd.service", "result": "Manual Intervention Required", "outcome": "unknown",
         "reason": "not_settled", "detail": "it was still activating (start) when the <30 s> budget ran out"},
        # Pre-2.2.0 shape: no outcome or detail.
        {"service": "legacy.service", "result": "Manual Intervention Required"},
    ]
    extra_vars = tmp_path / "healing_case.json"
    extra_vars.write_text(json.dumps({"fixture_linux_vitals_result": result}), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(PLAYBOOK), "-e", f"@{extra_vars}"],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    # A fix renders exactly as before; a failure says why; an unverified
    # restart is marked unknown with its detail, escaped.
    assert "<li>chronyd.service: Fixed</li>" in html
    assert (
        "app.service: Failed to Fix <span class=\"muted\">"
        "&mdash; it came up, then failed within 5 s (result: exit-code)</span>"
    ) in html
    assert "sssd.service: Manual Intervention Required <span class=\"pill pill--serious\">" in html
    assert "Could not verify: it was still activating (start) when the &lt;30 s&gt; budget ran out" in html
    assert "<30 s>" not in html
    assert "<li>legacy.service: Manual Intervention Required</li>" in html
    assert html.count("Could not verify:") == 1

    # JSON carries every field through unchanged, and the schema stays 2.1.
    assert report["schema_version"] == "2.1"
    assert report["hosts"][0]["self_healing"]["healing_results"] == result["healing_results"]
