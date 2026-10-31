"""The journal regression must run without utilities absent in minimal images."""
import yaml
from test_templates import REPO_ROOT


def test_journal_regression_uses_the_docker_user_not_su() -> None:
    play = yaml.safe_load((REPO_ROOT / "molecule/resources/verify.yml").read_text())[0]
    block = next(task for task in play["tasks"] if task["name"] == "Check journals as the unprivileged Docker user")
    assert block["vars"]["ansible_user"] == "vitals-journal-reader"
    assert not block.get("become", False)
    identity, scan, verdict, login_verdict = block["block"]
    assert identity["ansible.builtin.command"]["argv"] == ["id", "-un"]
    assert "vitals-journal-reader" in identity["failed_when"]
    assert scan["ansible.builtin.include_role"]["name"].endswith(".vitals_scan")
    assert "apply" not in scan["ansible.builtin.include_role"]
    assert any("length == 2" in rule for rule in verdict["ansible.builtin.assert"]["that"])
    # The same unprivileged scan proves the failed-login check reports
    # unknown rather than clean when btmp cannot be read (#39).
    assert "failed_logins" in login_verdict["vars"]["login_findings"]
    assert any("'unknown'" in rule for rule in login_verdict["ansible.builtin.assert"]["that"])


def test_prepare_does_not_require_logger_to_populate_the_journal() -> None:
    tasks = yaml.safe_load((REPO_ROOT / "molecule/resources/prepare.yml").read_text())[0]["tasks"]
    commands = [task["ansible.builtin.command"]["argv"][0]
                for task in tasks if "ansible.builtin.command" in task]
    assert "logger" not in commands
    assert "systemctl" in commands


def test_fedora_provisions_a_public_system_bus_for_service_discovery() -> None:
    config = yaml.safe_load((REPO_ROOT / "molecule/fedora/molecule.yml").read_text())
    variables = config["provisioner"]["inventory"]["host_vars"]["linux-vitals-fedora"]
    assert "dbus-broker" in variables["vitals_test_packages"]
    assert variables["vitals_test_system_bus_service"] == "dbus-broker.service"
    tasks = yaml.safe_load((REPO_ROOT / "molecule/resources/prepare.yml").read_text())[0]["tasks"]
    task = next(item for item in tasks if item["name"] == "Start the system bus for unprivileged service discovery")
    assert task["ansible.builtin.systemd_service"]["state"] == "started"
    assert task["when"] == "vitals_test_system_bus_service is defined"
