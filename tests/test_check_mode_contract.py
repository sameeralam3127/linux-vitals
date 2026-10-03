from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_TASKS = REPO_ROOT / "roles" / "vitals_scan" / "tasks" / "main.yml"
TROUBLESHOOTING = REPO_ROOT / "docs" / "troubleshooting.md"


def test_vitals_scan_refuses_check_mode_before_discovery():
    tasks = yaml.safe_load(SCAN_TASKS.read_text(encoding="utf-8"))

    gate = tasks[0]
    assert gate["name"] == "Explain unsupported Ansible check mode"
    assert gate["ansible.builtin.assert"]["that"] == ["not ansible_check_mode"]
    assert "--check" in gate["ansible.builtin.assert"]["fail_msg"]
    assert "always" in gate["tags"]
    assert tasks[1]["ansible.builtin.include_tasks"]["file"] == "discovery.yml"


def test_troubleshooting_documents_check_mode_contract():
    text = TROUBLESHOOTING.read_text(encoding="utf-8")

    assert "does not currently support Ansible check mode" in text
    assert "vitals_heal" in text
    assert "disabled by default" in text
