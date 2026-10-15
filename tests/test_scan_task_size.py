"""Keep `vitals_scan`'s task files small enough to review (#27).

`discovery.yml` had grown to 1,048 lines when it was split into one file per
concern. At that length a task that lost its tags in the middle of the file
was invisible in review, which is how a `--tags kernel` run broke in #16.

This is a ratchet. A task file may not grow past `MAX_LINES`. A file that was
already over it when the ratchet landed is pinned at its exact length: it can
shrink, and must then lower its pin, but it can never grow.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scan_tasks import REPO_ROOT, SCAN_TASKS_DIR

MAX_LINES = 250
TASK_FILES = sorted(SCAN_TASKS_DIR.glob("*.yml"))

# Over MAX_LINES when the ratchet landed, pinned at that exact length.
PINNED = {
    # A single task: the bootloader probe's POSIX sh script is 287 lines by
    # itself, and one task cannot be split across files. Moving the script to
    # a file under files/ is what would bring this under the limit.
    "bootloader.yml": 302,
}


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_the_ratchet_sees_the_task_files() -> None:
    assert len(TASK_FILES) > 10, f"expected the split task files in {SCAN_TASKS_DIR}"


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda path: path.name)
def test_task_file_stays_within_the_line_limit(path: Path) -> None:
    limit = PINNED.get(path.name, MAX_LINES)
    lines = _lines(path)
    assert lines <= limit, (
        f"{path.relative_to(REPO_ROOT)} is {lines} lines, over its "
        f"limit of {limit}. Split it into another task file, imported in order from "
        f"discovery.yml -- see the vitals_scan task layout in docs/architecture.md."
    )


@pytest.mark.parametrize("name", sorted(PINNED))
def test_a_pinned_file_has_not_shrunk_without_lowering_its_pin(name: str) -> None:
    lines = _lines(SCAN_TASKS_DIR / name)
    assert lines > MAX_LINES, f"{name} is {lines} lines, within MAX_LINES: remove it from PINNED."
    assert lines == PINNED[name], f"{name} is now {lines} lines: lower its PINNED entry to {lines}."
