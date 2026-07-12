from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from shutil import which


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "render_templates.yml"
ARCHIVE_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "report_archiving.yml"
COMPARE_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "maintenance_compare.yml"


def _ensure_dev_collection_symlink() -> None:
    # FQCN roles (sameeralam3127.linux_vitals.*) resolve via
    # ansible.cfg's collections_path, which points at this repo-local
    # symlink -- create it on demand so a fresh clone/CI needs no manual
    # setup step.
    link = REPO_ROOT / ".dev-collections" / "ansible_collections" / "sameeralam3127" / "linux_vitals"
    if link.is_symlink() or link.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(REPO_ROOT, target_is_directory=True)


def _ansible_playbook_bin() -> str:
    ansible_playbook = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or which("ansible-playbook")
    assert ansible_playbook, "ansible-playbook must be installed and available on PATH"
    return ansible_playbook


def _base_env(tmp_path: Path) -> dict[str, str]:
    _ensure_dev_collection_symlink()
    env = os.environ.copy()
    env["TEST_OUTPUT_DIR"] = str(tmp_path)
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    env["ANSIBLE_LOCAL_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_REMOTE_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_HOME"] = str(REPO_ROOT / ".ansible")
    return env


def test_templates_render_with_representative_health_data(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    slack = (tmp_path / "slack.txt").read_text(encoding="utf-8")
    generic_webhook = json.loads((tmp_path / "generic_webhook.json").read_text(encoding="utf-8"))
    json_report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert "LinuxVitals Test Dashboard" in report
    assert "localhost" in report
    assert "Default boot entry selects the latest installed kernel" in report
    assert "chronyd.service: Fixed" in report
    assert "Standard Maintenance Summary" in slack
    assert "Overall Status: PASS" in slack
    assert "Bootloader: 6.8.0-test (latest selected)" in slack
    assert "Host Breakdown:" in slack
    assert generic_webhook["summary"]["overall_status"] == "PASS"
    assert generic_webhook["hosts"][0]["hostname"] == "localhost"
    assert "Standard Maintenance Summary" in generic_webhook["message"]
    assert json_report["schema_version"] == "1.1"
    assert json_report["summary"]["health_score_pct"] == 100.0
    assert json_report["hosts"][0]["asset_serial"] == "TEST-SERIAL-0001"
    assert json_report["hosts"][0]["comparison"]["baseline_available"] is False
    assert json_report["generated_at"] == "20260429T120000Z"
    assert json_report["summary"]["overall_status"] == "PASS"
    assert json_report["hosts"][0]["kernel"]["running"] == "6.8.0-test"
    assert json_report["hosts"][0]["reboot"]["required"] is False
    assert json_report["hosts"][0]["security"]["apparmor_status"] == "enabled"


def test_reporting_archives_timestamped_outputs_and_prunes_old_reports(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(ARCHIVE_PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    latest_report = tmp_path / "latest" / "linux_vitals_report.html"
    latest_json_report = tmp_path / "latest" / "linux_vitals_report.json"
    archived_html = sorted((tmp_path / "archive").glob("linux_vitals_report-*.html"))
    archived_json = sorted((tmp_path / "archive").glob("linux_vitals_report-*.json"))

    assert latest_report.exists()
    assert latest_json_report.exists()
    assert json.loads(latest_json_report.read_text(encoding="utf-8"))["summary"]["overall_status"] == "PASS"
    assert [path.name for path in archived_html] == [
        "linux_vitals_report-20260428T120000Z.html",
        "linux_vitals_report-20260429T120000Z.html",
    ]
    assert [path.name for path in archived_json] == [
        "linux_vitals_report-20260428T120000Z.json",
        "linux_vitals_report-20260429T120000Z.json",
    ]


def test_baseline_postcheck_comparison_detects_improvement_and_regression(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(COMPARE_PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    comparisons = json.loads((tmp_path / "comparisons.json").read_text(encoding="utf-8"))

    assert comparisons["host-a"]["baseline_available"] is True
    assert comparisons["host-a"]["status_improved"] is True
    assert comparisons["host-a"]["status_regressed"] is False
    assert comparisons["host-a"]["kernel_changed"] is True
    assert comparisons["host-a"]["ram_used_pct_delta"] == -36.0
    assert "RAM usage is critical" in comparisons["host-a"]["resolved_findings"]

    assert comparisons["host-b"]["baseline_available"] is True
    assert comparisons["host-b"]["status_regressed"] is True
    assert comparisons["host-b"]["status_improved"] is False
    assert "RAM usage is critical" in comparisons["host-b"]["new_findings"]

    assert comparisons["host-c"]["baseline_available"] is False
