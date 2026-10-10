"""The finding contract (#62) at fleet level, and the rule that keeps it.

`test_finding_severity.py` covers the per-host half: `status`, `reason` and
`unknown_count` as `severity.yml` produces them. This file covers what the
report does with them -- the health score, the summary count, and how the
HTML and JSON show a check that could not run -- plus the ratchet on scan
probes that ignore their own failure, which is what stops a new check
quietly reintroducing the false-clean report #62 exists to prevent.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment

from test_templates import PLAYBOOK, REPO_ROOT, _ansible_playbook_bin, _base_env

RENDER_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks" / "render.yml"
SCAN_TASKS_DIR = REPO_ROOT / "roles" / "vitals_scan" / "tasks"

UNKNOWN_FINDING = {
    "id": "failed_logins",
    "message": "Failed-login history could not be read",
    "severity": "info",
    "status": "unknown",
    "reason": "lastb exited 1: <permission denied>",
}


def _render_task(name: str) -> dict:
    tasks = yaml.safe_load(RENDER_TASKS.read_text(encoding="utf-8"))
    by_name = {task.get("name"): task for task in tasks}
    assert name in by_name, f"task missing from {RENDER_TASKS}: {name}"
    return by_name[name]["ansible.builtin.set_fact"]


def _render(expr: str, **context: object) -> str:
    return Environment().from_string(expr).render(**context).strip()


# ---------------------------------------------------------------------------
# Fleet rollup
# ---------------------------------------------------------------------------

def test_a_passing_host_with_an_unknown_check_does_not_count_as_healthy() -> None:
    expr = _render_task("Compute the fleet pass ratio for the health score")[
        "linux_vitals_pass_ratio_pct"
    ]
    results = [
        {"final_status": "Pass", "unknown_count": 0},
        # Passes under a raised threshold, but a check on it could not run.
        {"final_status": "Pass", "unknown_count": 1},
        {"final_status": "Fail", "unknown_count": 0},
        # ansible-core 2.16 stores the count as a string.
        {"final_status": "Pass", "unknown_count": "0"},
    ]

    assert float(_render(expr, linux_vitals_result_list=results)) == 50.0


def test_a_result_without_an_unknown_count_still_scores() -> None:
    # A result built by an older role, or by a test fixture, has no
    # unknown_count; it is scored as before rather than breaking the report.
    expr = _render_task("Compute the fleet pass ratio for the health score")[
        "linux_vitals_pass_ratio_pct"
    ]

    assert float(_render(expr, linux_vitals_result_list=[{"final_status": "Pass"}])) == 100.0
    assert float(_render(expr, linux_vitals_result_list=[])) == 0.0


def test_unknown_host_count_counts_hosts_not_findings() -> None:
    expr = _render_task("Build consolidated maintenance summary")["linux_vitals_summary"][
        "unknown_host_count"
    ]
    results = [
        {"final_status": "Fail", "unknown_count": 2},
        {"final_status": "Pass", "unknown_count": "1"},
        {"final_status": "Pass", "unknown_count": 0},
        {"final_status": "Pass"},
    ]

    assert int(_render(expr, linux_vitals_result_list=results)) == 2


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_html_and_json_show_an_unknown_check_distinctly(tmp_path: Path) -> None:
    fixture_vars = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]["vars"]
    result = dict(fixture_vars["fixture_linux_vitals_result"])
    result["findings"] = [*result["findings"], UNKNOWN_FINDING]
    result["unknown_count"] = 1
    summary = dict(
        fixture_vars["linux_vitals_summary"],
        unknown_host_count=1,
        health_score_pct=0.0,
        health_score_band="Poor",
    )
    extra_vars = tmp_path / "unknown_case.json"
    extra_vars.write_text(
        json.dumps({"fixture_linux_vitals_result": result, "linux_vitals_summary": summary}),
        encoding="utf-8",
    )

    subprocess.run(
        [_ansible_playbook_bin(), str(PLAYBOOK), "-e", f"@{extra_vars}"],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    webhook = json.loads((tmp_path / "generic_webhook.json").read_text(encoding="utf-8"))

    # HTML: a fleet tile, a per-host pill beside Pass/Fail, and the finding
    # marked with its reason -- escaped, since the reason can quote a probe.
    assert "Hosts with unknown checks" in html
    assert "<span class=\"dot\"></span>1 unknown</span>" in html
    assert "Could not check: lastb exited 1: &lt;permission denied&gt;" in html
    assert "<permission denied>" not in html
    # Only the unknown finding is marked; the two ordinary ones are not.
    assert html.count("Could not check:") == 1

    # JSON: the counts, and the finding with its status and reason.
    assert report["schema_version"] == "2.1"
    assert report["summary"]["unknown_host_count"] == 1
    host = report["hosts"][0]
    assert host["unknown_count"] == 1
    unknown = [f for f in host["findings"] if f.get("status") == "unknown"]
    assert unknown == [UNKNOWN_FINDING]

    assert webhook["summary"]["unknown_host_count"] == 1
    assert webhook["hosts"][0]["unknown_count"] == 1


# ---------------------------------------------------------------------------
# The rule for new checks
# ---------------------------------------------------------------------------

# Scan probes that set `failed_when: false`, recorded when the contract landed
# (#62). Ignoring a probe's failure is how a check that could not run ends up
# reading as clean, so each of these is to be audited against the contract --
# the failed-login probe first (#39). None has an unknown path yet.
#
# Adding a name here is a review decision, not a way to make this test pass:
# the probe must tell "ran and found nothing" from "could not run", and raise
# an `unknown` finding with a reason for the second (docs/architecture.md).
REVIEWED_PROBES_THAT_IGNORE_FAILURE = {
    "Collect recent systemd log errors",
    "Collect recent failed login attempts",
    "Collect last reboot information",
    "Collect latest installed kernel version",
    "Collect bootloader default kernel information",
    "Check if reboot is required on Debian family",
    "Check if reboot is recommended on RedHat family",
    "Check if reboot is recommended on SUSE family",
    "Collect SELinux mode",
    "Collect AppArmor status",
    "Collect rescue image presence",
    "Collect kernel install failures from logs",
}


def _tasks_ignoring_failure(tasks: list) -> set[str]:
    found: set[str] = set()
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        for key in ("block", "rescue", "always"):
            found |= _tasks_ignoring_failure(task.get(key))
        if task.get("failed_when") is False:
            found.add(task.get("name", "<unnamed task>"))
    return found


def test_a_new_probe_that_ignores_its_own_failure_is_reviewed() -> None:
    found: set[str] = set()
    for path in sorted(SCAN_TASKS_DIR.glob("*.yml")):
        found |= _tasks_ignoring_failure(yaml.safe_load(path.read_text(encoding="utf-8")))

    unreviewed = sorted(found - REVIEWED_PROBES_THAT_IGNORE_FAILURE)
    assert not unreviewed, (
        f"{unreviewed} set failed_when: false. A probe whose failure is "
        "ignored must still tell 'ran and found nothing' from 'could not run' "
        "and raise an unknown finding for the second -- see the finding "
        "contract in docs/architecture.md. Once it does, add it to "
        "REVIEWED_PROBES_THAT_IGNORE_FAILURE."
    )
    gone = sorted(REVIEWED_PROBES_THAT_IGNORE_FAILURE - found)
    assert not gone, f"{gone} no longer set failed_when: false; remove them from the list."
