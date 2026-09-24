"""The scan and heal paths must use the same service-status task."""

from __future__ import annotations

import yaml

from test_self_healing import _dump_task, _run_playbook
from test_templates import REPO_ROOT

SCAN_TASKS = REPO_ROOT / "roles" / "vitals_scan" / "tasks"
HEAL_MAIN = REPO_ROOT / "roles" / "vitals_heal" / "tasks" / "main.yml"


def _named(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def test_scan_and_heal_share_the_service_status_task(tmp_path):
    scan = yaml.safe_load((SCAN_TASKS / "discovery.yml").read_text(encoding="utf-8"))
    heal = yaml.safe_load(HEAL_MAIN.read_text(encoding="utf-8"))[0]["block"]
    shared = yaml.safe_load((SCAN_TASKS / "services.yml").read_text(encoding="utf-8"))

    assert (
        _named(scan, "Build required service status map")[
            "ansible.builtin.include_tasks"
        ]
        == "services.yml"
    )
    assert (
        _named(heal, "Refresh required service status after healing")[
            "ansible.builtin.include_role"
        ]["tasks_from"]
        == "services.yml"
    )
    assert len(shared) == 1
    assert "linux_vitals_service_status" in shared[0]["ansible.builtin.set_fact"]
    assert (
        sum(
            "linux_vitals_service_status"
            in str(task.get("ansible.builtin.set_fact", {}))
            for task in scan + heal
        )
        == 0
    )

    result = _run_playbook(
        tmp_path,
        [
            {
                "name": "Seed current service facts",
                "ansible.builtin.set_fact": {
                    "ansible_facts": {
                        "services": {
                            "sssd.service": {"state": "running"},
                            "systemd-journald": {"state": "active"},
                            "chronyd.service": {"state": "stopped"},
                        }
                    },
                    "linux_vitals_time_sync_service": "chronyd.service",
                },
            },
            _named(heal, "Refresh required service status after healing"),
            _dump_task({"service_status": "linux_vitals_service_status"}),
        ],
    )
    assert result["service_status"] == {
        "sssd": {"service_name": "sssd.service", "state": "running"},
        "systemd_journald": {"service_name": "systemd-journald", "state": "active"},
        "time_sync": {"service_name": "chronyd.service", "state": "stopped"},
    }


def test_service_status_handles_absent_units(tmp_path):
    shared = yaml.safe_load((SCAN_TASKS / "services.yml").read_text(encoding="utf-8"))
    result = _run_playbook(
        tmp_path,
        [
            {
                "name": "Seed empty service facts",
                "ansible.builtin.set_fact": {
                    "ansible_facts": {"services": {}},
                    "linux_vitals_time_sync_service": "absent",
                },
            },
            shared[0],
            _dump_task({"service_status": "linux_vitals_service_status"}),
        ],
    )
    assert result["service_status"] == {
        "sssd": {"service_name": "absent", "state": "missing"},
        "systemd_journald": {"service_name": "absent", "state": "missing"},
        "time_sync": {"service_name": "absent", "state": "missing"},
    }
