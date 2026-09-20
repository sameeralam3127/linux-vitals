"""Tests for the copy-paste starting kit under examples/.

These files are not executed by anything, which is exactly why they need
tests: nothing else notices when they drift away from the role defaults they
claim to document. The `playbook_dir` bug these guard against was live in
`group_vars/all.yml.example` for several releases -- it recommended the one
path anchoring the architecture doc explicitly says was abandoned, and stated
`.env` behaviour that had not been true since.

See issue #6.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from test_templates import REPO_ROOT

EXAMPLES = REPO_ROOT / "examples"
GROUP_VARS_EXAMPLE = EXAMPLES / "group_vars" / "all.yml.example"
ROLE_DEFAULTS = {
    "vitals_scan": REPO_ROOT / "roles" / "vitals_scan" / "defaults" / "main.yml",
    "vitals_heal": REPO_ROOT / "roles" / "vitals_heal" / "defaults" / "main.yml",
    "vitals_certs": REPO_ROOT / "roles" / "vitals_certs" / "defaults" / "main.yml",
    "vitals_report": REPO_ROOT / "roles" / "vitals_report" / "defaults" / "main.yml",
}

EXAMPLE_FILES = sorted(p for p in EXAMPLES.rglob("*") if p.is_file())


def test_examples_are_not_empty() -> None:
    assert EXAMPLE_FILES, "examples/ has no files"


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_no_example_recommends_playbook_dir(path: Path) -> None:
    # Every path that should live in the operator's project resolves from
    # inventory_dir, not playbook_dir -- see the dedicated section in
    # docs/architecture.md. playbook_dir breaks for an installed collection:
    # it resolves inside the installed package, which is often read-only and
    # is never where anyone looks for a report.
    text = path.read_text(encoding="utf-8")

    assert "playbook_dir" not in text, (
        f"{path.relative_to(REPO_ROOT)} references playbook_dir; "
        "paths in this project resolve from inventory_dir"
    )


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_every_example_file_is_referenced_by_the_docs(path: Path) -> None:
    # An example nobody links to is an example nobody reads, and it rots
    # silently. If a file here is worth keeping it is worth pointing at.
    relative = path.relative_to(REPO_ROOT).as_posix()
    searched = list(REPO_ROOT.glob("*.md")) + list((REPO_ROOT / "docs").glob("*.md"))

    referencing = [
        doc.name for doc in searched if relative in doc.read_text(encoding="utf-8")
    ]

    assert referencing, f"{relative} is not referenced by any documentation"


def test_commented_variables_in_the_example_all_exist_in_a_role_default() -> None:
    # The file's whole purpose is to be the complete list of tunables. A
    # variable that has been renamed or removed in a role but left here sends
    # an operator to set something that does nothing at all.
    defaults: set[str] = set()
    for path in ROLE_DEFAULTS.values():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults.update(loaded.keys())

    text = GROUP_VARS_EXAMPLE.read_text(encoding="utf-8")
    mentioned = set(re.findall(r"^#\s*(linux_vitals_[a-z0-9_]+):", text, re.MULTILINE))

    assert mentioned, "no linux_vitals_* variables found in the example"
    unknown = sorted(mentioned - defaults)
    assert not unknown, (
        f"{GROUP_VARS_EXAMPLE.name} documents variables no role defines: {unknown}"
    )


def test_the_example_inventories_parse_as_ini_inventories() -> None:
    for inventory in (EXAMPLES / "inventory").glob("*.ini"):
        text = inventory.read_text(encoding="utf-8")
        assert "[linux_servers]" in text, f"{inventory.name} has no linux_servers group"
        # The shipped playbooks all target `hosts: linux_servers`, so an
        # example inventory using a different group name would not run at all.
        assert re.search(r"^\[linux_servers(:vars)?\]$", text, re.MULTILINE)


def test_example_addresses_stay_in_the_documentation_range() -> None:
    # RFC 5737 TEST-NET-1. A real address in an example is an address someone
    # eventually points automation at by accident.
    for inventory in (EXAMPLES / "inventory").glob("*.ini"):
        for address in re.findall(r"ansible_host=(\d+\.\d+\.\d+\.\d+)", inventory.read_text(encoding="utf-8")):
            assert address.startswith("192.0.2."), (
                f"{inventory.name} uses {address}, outside the RFC 5737 range"
            )
