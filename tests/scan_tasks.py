"""Find `vitals_scan` tasks by name, wherever they live in the role.

`roles/vitals_scan/tasks/discovery.yml` used to hold every discovery task.
Since #27 it is an ordered list of `import_tasks`, and the tasks live in one
file per concern. Tests that need a task's production text look it up here by
name rather than by file, so moving a task between files does not break them.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_TASKS_DIR = REPO_ROOT / "roles" / "vitals_scan" / "tasks"
IMPORT = "ansible.builtin.import_tasks"


def _load(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def scan_tasks() -> list[dict]:
    """Every task in every `vitals_scan` task file, file by file."""
    return [task for path in sorted(SCAN_TASKS_DIR.glob("*.yml")) for task in _load(path)]


def _inline(path: Path) -> list[dict]:
    tasks: list[dict] = []
    for task in _load(path):
        if IMPORT not in task:
            tasks.append(task)
            continue
        # An import passes its own tags and `when` on to every task it
        # imports. None of discovery.yml's imports carry any; if one ever
        # does, the tasks returned here would no longer be what runs.
        extra = sorted(set(task) - {"name", IMPORT})
        assert not extra, f"{path.name}: import {task.get('name')!r} carries {extra}"
        tasks.extend(_inline(path.parent / task[IMPORT]))
    return tasks


def discovery_tasks() -> list[dict]:
    """discovery.yml's tasks in the order they run, every import inlined.

    The two dynamic includes (`reboot_facts.yml`, `services.yml`) stay as the
    include task, which is what runs at that point.
    """
    return _inline(SCAN_TASKS_DIR / "discovery.yml")


def scan_task(name: str) -> dict:
    """The one `vitals_scan` task called `name`, in whichever file holds it."""
    matches = [task for task in scan_tasks() if task.get("name") == name]
    assert len(matches) == 1, (
        f"expected exactly one task named {name!r} in {SCAN_TASKS_DIR}, found {len(matches)}"
    )
    return matches[0]
