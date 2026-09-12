"""`round()` must never be applied to an uncoerced variable.

Jinja's `round` filter has no string handling. On ansible-core 2.16 -- the
floor this collection declares in `meta/runtime.yml` -- a `set_fact` whose
template renders a number stores a plain string. (List, dict and boolean
results are converted back to real types; numeric scalars are the gap.) So a
later `round()` on that fact dies with

    type str doesn't define __round__ method

or `AnsibleUnsafeText` in its place where the source facts are unsafe-tagged,
and the whole scan fails at `Build per-host report object`.

Verified against 2.16.3 (fails) and 2.20.4 (passes, because newer cores
coerce).

A runtime test cannot catch this: on a core that coerces implicitly, the
unfixed expression passes. So this asserts the *shape* of the source instead --
every `round()` must be fed something explicitly numeric. `float` and `int` are
no-ops on a value that is already a number, so the coercion is free.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_FILES = sorted((REPO_ROOT / "roles").glob("*/tasks/*.yml"))
TEMPLATE_FILES = sorted((REPO_ROOT / "roles").glob("*/templates/*.j2"))

# Whatever is piped straight into `round(` must be either a numeric coercion
# filter or the close of a parenthesised arithmetic expression. Anything else
# is a bare variable reference, which is the shape that fails.
PIPED_INTO_ROUND = re.compile(r"(?P<prev>[)\]]|[A-Za-z_][A-Za-z0-9_.\[\]']*)\s*\|\s*round\(")
SAFE_PREDECESSORS = {"float", "int", ")", "]"}


def _offenders(text: str) -> list[str]:
    return [
        prev
        for prev in (m.group("prev") for m in PIPED_INTO_ROUND.finditer(text))
        if prev.split(".")[-1] not in SAFE_PREDECESSORS
    ]


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda p: f"{p.parts[-3]}/{p.name}")
def test_task_files_coerce_before_rounding(path: Path) -> None:
    offenders = _offenders(path.read_text(encoding="utf-8"))

    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)}: round() applied to an uncoerced value "
        f"{offenders}. Insert `| float` (or `| int`) before `| round(`."
    )


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.name)
def test_templates_coerce_before_rounding(path: Path) -> None:
    offenders = _offenders(path.read_text(encoding="utf-8"))

    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)}: round() applied to an uncoerced value "
        f"{offenders}. Insert `| float` (or `| int`) before `| round(`."
    )


def test_the_two_memory_facts_are_coerced() -> None:
    # The specific regression: both are built by a set_fact template in
    # discovery.yml and then rounded in result.yml.
    result = (REPO_ROOT / "roles" / "vitals_scan" / "tasks" / "result.yml").read_text(
        encoding="utf-8"
    )

    for fact in ("linux_vitals_memory_used_mb", "linux_vitals_memory_total_mb"):
        assert f"{{{{ {fact} | float | round(1) }}}}" in result, (
            f"{fact} must be coerced with `float` before `round(1)`"
        )


def test_the_guard_actually_catches_the_original_bug() -> None:
    # Guard against the regex silently matching nothing forever.
    assert _offenders("{{ linux_vitals_memory_used_mb | round(1) }}") == [
        "linux_vitals_memory_used_mb"
    ]
    assert _offenders("{{ linux_vitals_memory_used_mb | float | round(1) }}") == []
    assert _offenders("{{ (a | float / b | float) | round(1) }}") == []
