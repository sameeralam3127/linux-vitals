"""Tests for the discovery-fact bug fixes in `vitals_scan`'s discovery tasks.

Each test extracts the exact Jinja2 expression for the fact under test out
of the real task YAML (rather than duplicating it by hand) and renders it
through `ansible-playbook` with a fresh, minimal `set_fact` task, seeded
with just the input facts that expression depends on. This keeps the tests
tied to the production template text without requiring the rest of
discovery's many prerequisite command results. Tasks are found by name
(`scan_tasks.scan_task`), whichever file under `roles/vitals_scan/tasks/`
holds them.

See CHANGELOG.md for the bugs these facts fix:
- `selinux_status` was reported as an empty string on Debian hosts (no
  `getenforce`) instead of "not-installed".
- The scan crashed on any host without a separate `/boot` mount.
- `last_reboot` was empty when `who -b` returned no boot record.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from scan_tasks import scan_task
from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env


def _extract_set_fact_value(task_name: str, fact_name: str) -> str:
    return scan_task(task_name)["ansible.builtin.set_fact"][fact_name]


def _run_playbook(tmp_path: Path, tasks: list[dict]) -> dict:
    playbook = [
        {
            "name": "Exercise a discovery fact expression in isolation",
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "vars": {
                "output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}",
            },
            "tasks": tasks,
        }
    ]
    playbook_path = tmp_path / "discovery_fact_case.yml"
    playbook_path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")

    subprocess.run(
        [_ansible_playbook_bin(), str(playbook_path)],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    return json.loads((tmp_path / "discovery_fact.json").read_text(encoding="utf-8"))


def _dump_task(fact_name: str) -> dict:
    return {
        "name": "Write the result for assertion",
        "ansible.builtin.copy": {
            "content": "{{ {'value': " + fact_name + "} | to_nice_json }}\n",
            "dest": "{{ output_dir }}/discovery_fact.json",
            "mode": "0644",
        },
    }


# ---------------------------------------------------------------------------
# linux_vitals_selinux_status
# ---------------------------------------------------------------------------

def _run_selinux_status(tmp_path: Path, selinux_cmd: dict) -> str:
    expr = _extract_set_fact_value("Finalize extended discovery facts", "linux_vitals_selinux_status")
    tasks = [
        {
            "name": "Seed the getenforce command result for the scenario under test",
            "ansible.builtin.set_fact": {"linux_vitals_selinux_cmd": selinux_cmd},
        },
        {
            "name": "Evaluate linux_vitals_selinux_status",
            "ansible.builtin.set_fact": {"linux_vitals_selinux_status": expr},
        },
        _dump_task("linux_vitals_selinux_status"),
    ]
    return _run_playbook(tmp_path, tasks)["value"]


def test_selinux_status_defaults_to_not_installed_on_empty_stdout(tmp_path: Path) -> None:
    # getenforce is absent on Debian hosts: the command still runs (rc != 0)
    # but stdout is empty. `default('not-installed')` alone only replaces
    # Undefined, not an empty string, which is the bug this fixes.
    status = _run_selinux_status(tmp_path, {"stdout": "", "rc": 127})

    assert status == "not-installed"


def test_selinux_status_defaults_to_not_installed_when_stdout_missing_entirely(
    tmp_path: Path,
) -> None:
    status = _run_selinux_status(tmp_path, {"rc": 127})

    assert status == "not-installed"


def test_selinux_status_reports_enforcing_mode(tmp_path: Path) -> None:
    status = _run_selinux_status(tmp_path, {"stdout": "Enforcing\n", "rc": 0})

    assert status == "Enforcing"


def test_selinux_status_trims_whitespace(tmp_path: Path) -> None:
    status = _run_selinux_status(tmp_path, {"stdout": "  Permissive  \n", "rc": 0})

    assert status == "Permissive"


def test_selinux_status_treats_whitespace_only_stdout_as_not_installed(tmp_path: Path) -> None:
    status = _run_selinux_status(tmp_path, {"stdout": "   \n", "rc": 0})

    assert status == "not-installed"


# ---------------------------------------------------------------------------
# linux_vitals_last_reboot
# ---------------------------------------------------------------------------

def _run_last_reboot(tmp_path: Path, last_reboot_cmd: dict) -> str:
    expr = _extract_set_fact_value("Finalize extended discovery facts", "linux_vitals_last_reboot")
    tasks = [
        {
            "name": "Seed the who -b command result for the scenario under test",
            "ansible.builtin.set_fact": {"linux_vitals_last_reboot_cmd": last_reboot_cmd},
        },
        {
            "name": "Evaluate linux_vitals_last_reboot",
            "ansible.builtin.set_fact": {"linux_vitals_last_reboot": expr},
        },
        _dump_task("linux_vitals_last_reboot"),
    ]
    return _run_playbook(tmp_path, tasks)["value"]


def test_last_reboot_defaults_to_unknown_on_empty_stdout(tmp_path: Path) -> None:
    assert _run_last_reboot(tmp_path, {"stdout": "", "rc": 0}) == "Unknown"


def test_last_reboot_defaults_to_unknown_on_whitespace_only_stdout(tmp_path: Path) -> None:
    assert _run_last_reboot(tmp_path, {"stdout": "   \n", "rc": 0}) == "Unknown"


def test_last_reboot_defaults_to_unknown_when_stdout_missing(tmp_path: Path) -> None:
    assert _run_last_reboot(tmp_path, {"rc": 1}) == "Unknown"


def test_last_reboot_reports_timestamp(tmp_path: Path) -> None:
    result = _run_last_reboot(
        tmp_path, {"stdout": "         system boot  2026-09-24 10:55\n", "rc": 0}
    )

    assert result == "2026-09-24 10:55"


# ---------------------------------------------------------------------------
# linux_vitals_boot_mount
# ---------------------------------------------------------------------------

def _run_boot_mount(tmp_path: Path, mounts: list[dict]) -> dict:
    expr = _extract_set_fact_value("Build boot partition facts", "linux_vitals_boot_mount")
    tasks = [
        {
            "name": "Seed ansible_facts.mounts for the scenario under test",
            "ansible.builtin.set_fact": {"ansible_facts": {"mounts": mounts}},
        },
        {
            "name": "Evaluate linux_vitals_boot_mount",
            "ansible.builtin.set_fact": {"linux_vitals_boot_mount": expr},
        },
        _dump_task("linux_vitals_boot_mount"),
    ]
    return _run_playbook(tmp_path, tasks)["value"]


def test_boot_mount_does_not_crash_without_boot_or_efi_mounts(tmp_path: Path) -> None:
    # The bug this fixes: chaining two `| first` lookups through
    # `| default(..., true)` raised "No first item, sequence was empty" when
    # neither /boot nor /boot/efi was mounted -- the common case for cloud
    # images and containers. It must now resolve to an empty mapping.
    result = _run_boot_mount(tmp_path, mounts=[])

    assert result == {}


def test_boot_mount_does_not_crash_with_unrelated_mounts_only(tmp_path: Path) -> None:
    result = _run_boot_mount(
        tmp_path,
        mounts=[{"mount": "/", "size_available": 1000, "size_total": 2000}],
    )

    assert result == {}


def test_boot_mount_resolves_a_dedicated_boot_partition(tmp_path: Path) -> None:
    result = _run_boot_mount(
        tmp_path,
        mounts=[
            {"mount": "/", "size_available": 1000, "size_total": 2000},
            {"mount": "/boot", "size_available": 100, "size_total": 200},
        ],
    )

    assert result == {"mount": "/boot", "size_available": 100, "size_total": 200}


def test_boot_mount_falls_back_to_boot_efi_when_boot_is_not_a_separate_mount(
    tmp_path: Path,
) -> None:
    result = _run_boot_mount(
        tmp_path,
        mounts=[{"mount": "/boot/efi", "size_available": 50, "size_total": 100}],
    )

    assert result == {"mount": "/boot/efi", "size_available": 50, "size_total": 100}


def test_boot_mount_prefers_boot_over_boot_efi_when_both_are_present(tmp_path: Path) -> None:
    result = _run_boot_mount(
        tmp_path,
        mounts=[
            {"mount": "/boot/efi", "size_available": 50, "size_total": 100},
            {"mount": "/boot", "size_available": 100, "size_total": 200},
        ],
    )

    assert result["mount"] == "/boot"
