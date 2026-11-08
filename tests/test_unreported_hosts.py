"""A host that could not be scanned must be named, counted and scored (#147).

The bug these pin: the report was built from `ansible_play_hosts`, which drops
a host the moment it fails or goes unreachable. Everything downstream counted
from that list, so three unreachable hosts out of ten produced a report
claiming 7 servers checked, a health score of 100 % (Excellent), `overall_status`
PASS and 0 regressed -- with the three hosts whose outcome was least known
absent from every number and every list.

Two layers are covered. The expression tests render `render.yml`'s own Jinja,
so a change to the score's denominator cannot slip past. The playbook test runs
a real four-host play in which one host is genuinely unreachable (ssh to a
closed port), one fails mid-play, and one ends its run before a result exists --
the three ways a targeted host reaches `vitals_report` with nothing to report.
"""
from __future__ import annotations

import copy
import csv
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

from test_templates import (
    PLAYBOOK, REPO_ROOT, _ansible_playbook_bin, _base_env,
)

RENDER_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks" / "render.yml"
GATE_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks" / "gate.yml"
FLEET_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "unreachable_hosts.yml"
FLEET_INVENTORY = REPO_ROOT / "tests" / "fixtures" / "unreachable_hosts.ini"

# The hosts unreachable_hosts.ini targets, and what each is there to prove.
REPORTED = "reported"
UNREPORTED = ["failed_midscan", "no_result", "unreachable"]


def _task(path: Path, name: str) -> dict:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_name = {task.get("name"): task for task in tasks}
    assert name in by_name, f"task missing from {path}: {name}"
    return by_name[name]["ansible.builtin.set_fact"]


def _render(expr: str, **context: object) -> str:
    return Environment().from_string(expr).render(**context).strip()


def _unreported(name: str, baseline: bool = False) -> dict:
    return {
        "inventory_name": name,
        "status": "Unknown",
        "reason": "no health result was produced for this host",
        "baseline_available": baseline,
    }


# ---------------------------------------------------------------------------
# The health score
# ---------------------------------------------------------------------------

def test_the_health_score_does_not_improve_when_a_host_drops_out() -> None:
    # The heart of the bug. Ten hosts baselined, patched and rebooted; three
    # never come back. The score must fall from 100 % to 70 %, not stay at
    # 100 % because the three worst hosts left the denominator.
    expr = _task(RENDER_TASKS, "Compute the fleet pass ratio for the health score")[
        "linux_vitals_pass_ratio_pct"
    ]
    answered = [{"final_status": "Pass", "unknown_count": 0}] * 7
    silent = [_unreported(f"host{index}") for index in range(3)]

    whole_fleet = float(_render(expr, linux_vitals_result_list=answered + [
        {"final_status": "Pass", "unknown_count": 0}] * 3))
    with_dropouts = float(
        _render(expr, linux_vitals_result_list=answered, linux_vitals_unreported_hosts=silent)
    )

    assert whole_fleet == 100.0
    assert with_dropouts == 70.0
    assert with_dropouts < whole_fleet


def test_an_unreported_host_can_never_be_in_the_numerator() -> None:
    # A fleet where nothing answered scores zero, not 100 % of nothing.
    expr = _task(RENDER_TASKS, "Compute the fleet pass ratio for the health score")[
        "linux_vitals_pass_ratio_pct"
    ]

    score = float(_render(
        expr,
        linux_vitals_result_list=[],
        linux_vitals_unreported_hosts=[_unreported("a"), _unreported("b")],
    ))

    assert score == 0.0


def test_the_score_is_unchanged_when_every_host_answered() -> None:
    # The existing contract (#62) still holds: a passing host with an unknown
    # check is not healthy, and nothing else moved.
    expr = _task(RENDER_TASKS, "Compute the fleet pass ratio for the health score")[
        "linux_vitals_pass_ratio_pct"
    ]
    results = [
        {"final_status": "Pass", "unknown_count": 0},
        {"final_status": "Pass", "unknown_count": 1},
        {"final_status": "Fail", "unknown_count": 0},
        {"final_status": "Pass", "unknown_count": "0"},
    ]

    assert float(_render(expr, linux_vitals_result_list=results)) == 50.0


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------

def test_the_summary_counts_and_carries_the_unreported_hosts() -> None:
    summary = _task(RENDER_TASKS, "Build consolidated maintenance summary")[
        "linux_vitals_summary"
    ]
    silent = [_unreported("db03", baseline=True), _unreported("web07")]

    count = _render(summary["unreported_host_count"], linux_vitals_unreported_hosts=silent)
    missing = _render(summary["missing_postcheck_count"], linux_vitals_unreported_hosts=silent)

    assert int(count) == 2
    # Only the host that had a baseline under this maintenance id is "missing"
    # from the comparison; a host with no baseline cannot have regressed.
    assert int(missing) == 1


def test_overall_status_fails_when_a_targeted_host_produced_nothing() -> None:
    expr = _task(RENDER_TASKS, "Build consolidated maintenance summary")[
        "linux_vitals_summary"
    ]["overall_status"]

    assert _render(expr, linux_vitals_failing_host_count=0,
                   linux_vitals_unreported_hosts=[]) == "PASS"
    # Nothing failed, because nothing on that host was looked at.
    assert _render(expr, linux_vitals_failing_host_count=0,
                   linux_vitals_unreported_hosts=[_unreported("db03")]) == "FAIL"
    assert _render(expr, linux_vitals_failing_host_count=2,
                   linux_vitals_unreported_hosts=[]) == "FAIL"


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------

def test_both_gates_count_hosts_that_produced_no_result() -> None:
    expr = _task(GATE_TASKS, "Compute fleet health gate failure count")[
        "linux_vitals_gate_failure_count"
    ]
    summary = {
        "critical_error_count": 0,
        "regressed_count": 0,
        "unreported_host_count": 3,
        "missing_postcheck_count": 2,
    }

    any_fail = _render(expr, linux_vitals_summary=summary,
                       linux_vitals_fail_on_status="any_fail",
                       linux_vitals_phase="postcheck")
    regression = _render(expr, linux_vitals_summary=summary,
                         linux_vitals_fail_on_status="regression",
                         linux_vitals_phase="postcheck")

    # Both used to be zero on exactly the run that most needed stopping.
    assert int(any_fail) == 3
    assert int(regression) == 2


def test_the_gates_are_unchanged_for_a_summary_without_the_new_fields() -> None:
    expr = _task(GATE_TASKS, "Compute fleet health gate failure count")[
        "linux_vitals_gate_failure_count"
    ]
    summary = {"critical_error_count": 3, "regressed_count": 1}

    assert int(_render(expr, linux_vitals_summary=summary,
                       linux_vitals_fail_on_status="any_fail",
                       linux_vitals_phase="adhoc")) == 3
    assert int(_render(expr, linux_vitals_summary=summary,
                       linux_vitals_fail_on_status="regression",
                       linux_vitals_phase="postcheck")) == 1


# ---------------------------------------------------------------------------
# A real play with hosts that never answer
# ---------------------------------------------------------------------------

def _fleet_run(tmp_path: Path, **fixture: object) -> dict:
    env = _base_env(tmp_path)
    template_vars = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]["vars"]
    result = copy.deepcopy(template_vars["fixture_linux_vitals_result"])
    result.update(unknown_count=0, findings=[], final_status="Pass", severity="none",
                  severity_counts={"info": 0, "warning": 0, "critical": 0})
    extra = tmp_path / "fleet.json"
    extra.write_text(json.dumps({"fixture_result": result, **fixture}), encoding="utf-8")

    subprocess.run(
        [
            _ansible_playbook_bin(),
            "-i", str(FLEET_INVENTORY),
            str(FLEET_PLAYBOOK),
            "-e", f"@{extra}",
        ],
        # Three of the four hosts cannot finish, so the play exits non-zero.
        # That has always worked; what is being tested is the report it leaves.
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    report_path = tmp_path / "report.json"
    assert report_path.exists(), "no JSON report was rendered"
    return json.loads(report_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def adhoc_fleet(tmp_path_factory) -> tuple[Path, dict]:
    tmp_path = tmp_path_factory.mktemp("adhoc_fleet")
    return tmp_path, _fleet_run(tmp_path)


def test_every_targeted_host_that_did_not_answer_is_named(adhoc_fleet) -> None:
    _, report = adhoc_fleet
    summary = report["summary"]

    # The one host that answered is the only host row -- hosts[].status keeps
    # its two values, so a consumer branching on Pass/Fail is unaffected.
    assert [host["inventory_name"] for host in report["hosts"]] == [REPORTED]
    assert {host["status"] for host in report["hosts"]} == {"Pass"}

    named = [entry["inventory_name"] for entry in summary["unreported_hosts"]]
    assert sorted(named) == sorted(UNREPORTED)
    assert summary["unreported_host_count"] == 3
    # Every one of them says "nobody looked", with a reason -- the same shape
    # a check that could not run uses (#62), never a clean or failing status.
    for entry in summary["unreported_hosts"]:
        assert entry["status"] == "Unknown"
        assert entry["reason"].strip()
        assert entry["baseline_available"] is False


def test_the_fleet_verdict_and_score_account_for_them(adhoc_fleet) -> None:
    _, report = adhoc_fleet
    summary = report["summary"]

    # One host of four passed cleanly. Before the fix this was 1/1 = 100.0
    # (Excellent) and PASS, because the other three were not in the report.
    assert summary["servers_checked"] == 1
    assert summary["health_score_pct"] == 25.0
    assert summary["health_score_band"] == "Poor"
    assert summary["failing_host_count"] == 0
    assert summary["overall_status"] == "FAIL"
    assert "3 Not Checked" in summary["snippet"]
    assert report["schema_version"] == "2.4"


def test_the_dashboard_names_them_outside_the_filterable_table(adhoc_fleet) -> None:
    tmp_path, _ = adhoc_fleet
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    # A tile, and a panel above the host table: a host nobody reached cannot
    # be found by filtering a table it is not in.
    assert "Not checked" in html
    assert 'id="not-checked"' in html
    for host in UNREPORTED:
        assert f"<strong>{host}</strong>" in html


def test_the_exports_name_them_too(adhoc_fleet) -> None:
    tmp_path, _ = adhoc_fleet

    with (tmp_path / "report.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    by_host = {row["hostname"]: row for row in rows}
    assert sorted(by_host) == sorted([REPORTED, *UNREPORTED])
    for host in UNREPORTED:
        assert by_host[host]["status"] == "Unknown"
        # Nothing was measured, so nothing is reported as zero.
        assert by_host[host]["ram_used_pct"] == ""
        assert by_host[host]["failed_login_count"] == ""

    metrics = (tmp_path / "report.prom").read_text(encoding="utf-8")
    assert 'linux_vitals_unreported_hosts{phase="adhoc"} 3' in metrics
    # The exporter recomputes the score, so it has to use the same denominator
    # as the report's summary or the two disagree.
    assert 'linux_vitals_health_score_pct{phase="adhoc"} 25.0' in metrics


def test_slack_and_the_webhook_name_them_in_every_message(tmp_path: Path) -> None:
    # The fleet playbook above renders the reports and the exports; Slack and
    # the webhook payload are rendered by the template fixture, so they get
    # their own pass over the same summary shape.
    fixture_vars = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]["vars"]
    summary = dict(
        fixture_vars["linux_vitals_summary"],
        overall_status="FAIL",
        unreported_host_count=2,
        missing_postcheck_count=1,
        unreported_hosts=[_unreported("db03", baseline=True), _unreported("web07")],
        snippet="1 Servers Checked, 1 Auto-Fixed, 0 Failing Hosts, 2 Not Checked",
    )
    extra_vars = tmp_path / "unreported.json"
    extra_vars.write_text(json.dumps({"linux_vitals_summary": summary}), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(PLAYBOOK), "-e", f"@{extra_vars}"],
        check=True, cwd=REPO_ROOT, env=_base_env(tmp_path),
    )

    slack = (tmp_path / "slack.txt").read_text(encoding="utf-8")
    blocks = json.loads((tmp_path / "slack.json").read_text(encoding="utf-8"))
    webhook = json.loads((tmp_path / "generic_webhook.json").read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    # Plain text, which is also the email body and the webhook's `message`.
    assert "Overall Status: FAIL" in slack
    assert "Not Checked: 2" in slack
    assert "- db03:" in slack
    assert "- web07:" in slack

    # Block Kit: the verdict, a counter, and a block naming each host. The
    # colour bar must go red -- a fleet with a silent host is not green.
    attachment = blocks["attachments"][0]
    assert attachment["color"] == "#e01e5a"
    assert "2 NOT CHECKED" in blocks["text"]
    counters = {
        field["text"].split("\n")[0]: field["text"].split("\n")[1]
        for block in attachment["blocks"]
        if block["type"] == "section" and "fields" in block
        for field in block["fields"]
    }
    assert counters["*Not checked*"] == "2"
    card = json.dumps(attachment["blocks"])
    assert "Not checked" in card
    assert "db03" in card and "web07" in card
    assert len(attachment["blocks"]) <= 50

    # The webhook payload's `hosts` is a deliberate per-host subset, so the
    # hosts that produced nothing are carried in its summary instead.
    assert webhook["summary"]["overall_status"] == "FAIL"
    assert webhook["summary"]["unreported_host_count"] == 2
    assert webhook["summary"]["missing_postcheck_count"] == 1
    assert [entry["inventory_name"] for entry in
            webhook["summary"]["unreported_hosts"]] == ["db03", "web07"]
    assert report["summary"]["overall_status"] == "FAIL"


def test_a_summary_without_the_new_fields_still_renders(tmp_path: Path) -> None:
    # A summary built by an older release, or by a downstream playbook that
    # assembles its own, has none of these fields. The templates must fall
    # back rather than fail the whole report.
    fixture_vars = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))[0]["vars"]
    summary = {
        key: value
        for key, value in fixture_vars["linux_vitals_summary"].items()
        if key not in {"unreported_host_count", "unreported_hosts", "overall_status"}
    }
    extra_vars = tmp_path / "legacy_summary.json"
    extra_vars.write_text(json.dumps({"linux_vitals_summary": summary}), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(PLAYBOOK), "-e", f"@{extra_vars}"],
        check=True, cwd=REPO_ROOT, env=_base_env(tmp_path),
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert report["summary"]["unreported_host_count"] == 0
    assert report["summary"]["unreported_hosts"] == []
    assert report["summary"]["overall_status"] == "PASS"
    # The tile renders as a zero; the panel is only there when it is not.
    assert "Not checked" in html
    assert 'id="not-checked"' not in html


def test_a_postcheck_host_with_a_baseline_and_no_result_is_counted_missing(
    tmp_path: Path,
) -> None:
    maintenance_id = "2026-04-29-patch-window"
    baseline_dir = tmp_path / "snapshots" / maintenance_id / "baseline"
    baseline_dir.mkdir(parents=True)
    # Baselined before the window, silent after it: the case baseline/postcheck
    # exists for, and the one the comparison used to drop entirely.
    (baseline_dir / "unreachable.json").write_text(
        json.dumps({"final_status": "Pass", "captured_at": "2026-04-28T12:00:00Z"}),
        encoding="utf-8",
    )

    report = _fleet_run(
        tmp_path, fixture_phase="postcheck", fixture_maintenance_id=maintenance_id
    )
    summary = report["summary"]
    by_name = {entry["inventory_name"]: entry for entry in summary["unreported_hosts"]}

    assert summary["unreported_host_count"] == 3
    assert summary["missing_postcheck_count"] == 1
    assert by_name["unreachable"]["baseline_available"] is True
    assert by_name["failed_midscan"]["baseline_available"] is False
    # regressed_count still counts only hosts that reported; the missing host
    # is counted separately rather than being guessed at.
    assert summary["regressed_count"] == 0
