"""Exercise optional exporters through Ansible with synthetic report data."""
from __future__ import annotations

import copy
import csv
import json
import math
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml
from prometheus_client.parser import text_string_to_metric_families

from test_templates import (
    ARCHIVE_PLAYBOOK, PLAYBOOK, REPO_ROOT, _ansible_playbook_bin, _base_env,
)

EXPORT_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "render_exports.yml"


def _host(**changes: object) -> dict:
    data = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    result = copy.deepcopy(data[0]["vars"]["fixture_linux_vitals_result"])
    result.update(unknown_count=0, findings=[])
    result.update(changes)
    return result


def _render(tmp_path: Path, results: list[dict], tags: str | None = None,
            **changes: object) -> subprocess.CompletedProcess:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = {
        "fixture_results": results,
        "fixture_metrics_path": str(tmp_path / "metrics" / "report.prom"),
        "fixture_csv_path": str(tmp_path / "csv" / "report.csv"),
        **changes,
    }
    data_path = tmp_path / "fixture.json"
    data_path.write_text(json.dumps(fixture), encoding="utf-8")
    env = _base_env(tmp_path)
    env["EXPORT_FIXTURE_DATA"] = str(data_path)
    command = [_ansible_playbook_bin(), str(EXPORT_PLAYBOOK)]
    if tags:
        command += ["--tags", tags]
    return subprocess.run(
        command,
        env=env, cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )


def _samples(tmp_path: Path) -> tuple[dict, dict]:
    text = (tmp_path / "metrics" / "report.prom").read_text(encoding="utf-8")
    assert text.endswith("\n")
    families = list(text_string_to_metric_families(text))
    samples = {}
    for family in families:
        assert family.type == "gauge"
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            assert key not in samples, f"duplicate series: {key}"
            assert sample.timestamp is None
            samples[key] = sample.value
    return {family.name: family for family in families}, samples


def _value(samples: dict, name: str, **labels: str) -> float:
    return samples[("linux_vitals_" + name, tuple(sorted(labels.items())))]


def _rows(tmp_path: Path) -> list[dict]:
    with (tmp_path / "csv" / "report.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_exports_keep_unknown_checks_and_current_finding_counts(tmp_path: Path) -> None:
    hosts = [
        _host(hostname="known", ram_used_pct=0.0),
        _host(hostname="unchecked", unknown_count=2, findings=[
            {"id": "failed_logins", "severity": "info", "status": "unknown", "reason": "unreadable"},
            {"id": "log_errors", "severity": "info", "status": "unknown", "reason": "unreadable"},
            {"id": "service", "subject": "one", "severity": "warning"},
            {"id": "service", "subject": "two", "severity": "warning", "status": "fail"},
        ]),
        _host(hostname="failed", final_status="Fail", reboot_required=True,
              findings=[{"id": "ram_critical", "severity": "critical", "status": "fail"}]),
    ]
    completed = _render(tmp_path, hosts, fixture_phase="postcheck")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    families, samples = _samples(tmp_path)
    assert len(families) == 6
    common = {"ip_address": "127.0.0.1", "os_family": "Debian", "phase": "postcheck"}
    assert _value(samples, "host_status", host="known", **common) == 1
    assert _value(samples, "host_status", host="unchecked", **common) == 0
    assert _value(samples, "host_status", host="failed", **common) == 0
    assert _value(samples, "unknown_count", host="unchecked", **common) == 2
    assert _value(samples, "findings_total", host="unchecked", severity="info", status="unknown", **common) == 2
    assert _value(samples, "findings_total", host="unchecked", severity="warning", status="fail", **common) == 2
    assert _value(samples, "findings_total", host="known", severity="critical", status="unknown", **common) == 0
    assert _value(samples, "ram_used_pct", host="known", **common) == 0
    assert _value(samples, "reboot_required", host="failed", **common) == 1
    assert _value(samples, "health_score_pct", phase="postcheck") == 33.3
    rows = _rows(tmp_path)
    assert len(rows) == 3
    assert rows[1]["status"] == "Pass" and rows[1]["unknown_count"] == "2"
    assert rows[0]["ram_used_pct"] == "0.0"
    assert all(row["change"] == "New" for row in rows)
    for path in (tmp_path / "metrics" / "report.prom", tmp_path / "csv" / "report.csv"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_export_labels_and_csv_fields_round_trip_special_characters(tmp_path: Path) -> None:
    name = 'node,"quoted"\\branch\nnext-雪'
    os_family = 'OS\\family"\nnext'
    hosts = [_host(hostname=name, os_family=os_family, os='Example,"OS"\r\nline')]
    completed = _render(tmp_path, hosts)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _, samples = _samples(tmp_path)
    assert _value(samples, "host_status", host=name, ip_address="127.0.0.1", os_family=os_family, phase="adhoc") == 1
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["hostname"] == name
    assert rows[0]["os"] == hosts[0]["os"]
    assert rows[0]["change"] == ""


def test_csv_protects_formula_text_and_keeps_absent_pressure_blank(tmp_path: Path) -> None:
    hosts = [_host(hostname='=1+1', os='+example', platform_type='@example', pressure={})]
    completed = _render(tmp_path, hosts, fixture_metrics_path="")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = _rows(tmp_path)[0]
    assert row["hostname"] == "'=1+1"
    assert row["os"] == "'+example"
    assert row["platform_type"] == "'@example"
    assert row["load_per_cpu_5m"] == row["psi_some_max_pct"] == row["swap_rate_per_sec"] == ""
    assert not (tmp_path / "metrics").exists()


def test_reboot_unknown_does_not_confuse_unsupported_distro_fallback(tmp_path: Path) -> None:
    hosts = [
        _host(hostname="fallback", reboot_detection_supported=False, reboot_required=False,
              ram_used_pct="43.2"),
        _host(hostname="unknown", unknown_count=1, ram_used_pct=None, findings=[
            {"id": "reboot_required", "severity": "warning", "status": "unknown", "reason": "unavailable"},
        ]),
    ]
    completed = _render(tmp_path, hosts)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _, samples = _samples(tmp_path)
    common = {"ip_address": "127.0.0.1", "os_family": "Debian", "phase": "adhoc"}
    assert _value(samples, "reboot_required", host="fallback", **common) == 0
    assert _value(samples, "ram_used_pct", host="fallback", **common) == 43.2
    assert math.isnan(_value(samples, "reboot_required", host="unknown", **common))
    assert math.isnan(_value(samples, "ram_used_pct", host="unknown", **common))
    rows = _rows(tmp_path)
    assert rows[0]["reboot_required"] == "No" and rows[0]["reboot_detection_supported"] == "false"
    assert rows[1]["reboot_required"] == "Unknown" and rows[1]["ram_used_pct"] == ""


def test_empty_results_have_a_csv_header_and_zero_fleet_score(tmp_path: Path) -> None:
    completed = _render(tmp_path, [])
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _, samples = _samples(tmp_path)
    assert len(samples) == 1
    assert _value(samples, "health_score_pct", phase="adhoc") == 0
    assert _rows(tmp_path) == []
    assert (tmp_path / "csv" / "report.csv").read_text().startswith('"status","unknown_count"')


def test_duplicate_metric_identity_fails_before_writing_but_csv_keeps_both(tmp_path: Path) -> None:
    hosts = [_host(), _host()]
    completed = _render(tmp_path, hosts)
    assert completed.returncode != 0
    assert "unique (hostname, ip_address, os_family)" in completed.stdout
    assert not (tmp_path / "metrics").exists()
    assert not (tmp_path / "csv").exists()
    completed = _render(tmp_path, hosts, fixture_metrics_path="")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(_rows(tmp_path)) == 2


@pytest.mark.parametrize("destination", ["report.html", "report.json", "csv/report.csv"])
def test_export_destinations_cannot_overwrite_other_reports(tmp_path: Path, destination: str) -> None:
    completed = _render(tmp_path, [_host()], fixture_metrics_path=str(tmp_path / destination))
    assert completed.returncode != 0
    assert "output paths must differ" in completed.stdout
    assert not (tmp_path / destination).exists()


def test_disabled_exports_create_no_files(tmp_path: Path) -> None:
    completed = _render(tmp_path, [_host()], fixture_metrics_path="  ", fixture_csv_path="")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not (tmp_path / "metrics").exists()
    assert not (tmp_path / "csv").exists()


def test_reporting_tag_reaches_nested_export_tasks(tmp_path: Path) -> None:
    completed = _render(tmp_path, [_host()], tags="reporting", fixture_full_report=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (tmp_path / "report.html").exists() and (tmp_path / "report.json").exists()
    assert len(_rows(tmp_path)) == 1
    _samples(tmp_path)


def test_enabling_exports_preserves_html_json_and_archives(tmp_path: Path) -> None:
    def report_bytes(path: Path) -> bytes:
        content = path.read_bytes()
        if path.suffix == ".html":
            # The existing dashboard intentionally renders wall-clock time,
            # independently of the pinned archive timestamp. Compare every
            # other byte; do not change production HTML to make a test stable.
            content = re.sub(
                rb'(<p class="meta">Generated )\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC',
                rb'\1<render-time>', content,
            )
        return content

    env = _base_env(tmp_path)
    command = [_ansible_playbook_bin(), str(ARCHIVE_PLAYBOOK)]
    subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    outputs = sorted((tmp_path / "latest").glob("*")) + sorted((tmp_path / "archive").glob("*"))
    before = {str(path): report_bytes(path) for path in outputs}
    assert not (tmp_path / "metrics").exists() and not (tmp_path / "csv").exists()
    command += ["-e", json.dumps({
        "linux_vitals_metrics_output_path": str(tmp_path / "metrics" / "report.prom"),
        "linux_vitals_csv_output_path": str(tmp_path / "csv" / "report.csv"),
    })]
    subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)
    after = {str(path): report_bytes(path) for path in outputs}
    assert before == after
    assert len(_rows(tmp_path)) == 1
    _samples(tmp_path)
