"""Keep every report, archive, and snapshot write on the configurable modes."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROLE_DIR = Path(__file__).resolve().parent.parent / "roles" / "vitals_report"
DIR_MODE = "{{ linux_vitals_report_dir_mode }}"
FILE_MODE = "{{ linux_vitals_report_file_mode }}"


@pytest.mark.parametrize(
    ("task_file", "expected_dirs", "expected_files"),
    [("render.yml", 3, 4), ("snapshot.yml", 1, 1)],
)
def test_report_write_tasks_use_configurable_modes(
    task_file: str, expected_dirs: int, expected_files: int
) -> None:
    tasks = yaml.safe_load((ROLE_DIR / "tasks" / task_file).read_text(encoding="utf-8"))
    directory_modes = [
        task["ansible.builtin.file"]["mode"]
        for task in tasks
        if "ansible.builtin.file" in task
        and task["ansible.builtin.file"].get("state") == "directory"
    ]
    file_modes = [
        task[module]["mode"]
        for task in tasks
        for module in ("ansible.builtin.copy", "ansible.builtin.template")
        if module in task
    ]

    assert directory_modes == [DIR_MODE] * expected_dirs
    assert file_modes == [FILE_MODE] * expected_files


def test_report_mode_defaults_preserve_existing_permissions() -> None:
    defaults = yaml.safe_load((ROLE_DIR / "defaults" / "main.yml").read_text(encoding="utf-8"))

    assert defaults["linux_vitals_report_dir_mode"] == "0755"
    assert defaults["linux_vitals_report_file_mode"] == "0644"
