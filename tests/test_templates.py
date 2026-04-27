from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "render_templates.yml"


def test_templates_render_with_representative_health_data(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["TEST_OUTPUT_DIR"] = str(tmp_path)
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    env["ANSIBLE_LOCAL_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_REMOTE_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_HOME"] = str(REPO_ROOT / ".ansible")
    ansible_playbook = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or which("ansible-playbook")

    assert ansible_playbook, "ansible-playbook must be installed and available on PATH"

    subprocess.run(
        [
            ansible_playbook,
            str(PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    slack = (tmp_path / "slack.txt").read_text(encoding="utf-8")

    assert "Smart OS Health Check Test Dashboard" in report
    assert "localhost" in report
    assert "Bootloader Check: Default boot entry selects the latest installed kernel" in report
    assert "chronyd.service: Fixed" in report
    assert "Standard Maintenance Summary" in slack
    assert "Overall Status: PASS" in slack
    assert "Bootloader: 6.8.0-test (latest selected)" in slack
    assert "Host Breakdown:" in slack
