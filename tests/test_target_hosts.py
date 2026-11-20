"""The shipped playbooks scan any inventory, and say so when they would scan nothing (#194).

Each playbook targets `linux_vitals_hosts` (default `linux_servers`), so an
existing inventory works with `-e linux_vitals_hosts=all` and no file edits.
A play whose pattern matches no host runs nothing and exits 0, which reads as
a clean run, so each playbook opens with a guard play that fails instead.

The guard is run here on its own, extracted from each playbook, so the tests
never reach the scan. Targeting is checked with --list-hosts, which runs
nothing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

PLAYBOOKS = ["healthcheck", "baseline", "postcheck"]
HOSTS = "{{ linux_vitals_hosts | default('linux_servers') }}"
INVENTORY = """\
[web]
web01 ansible_connection=local
[db]
db01 ansible_connection=local
"""


def _plays(name: str) -> list[dict]:
    return yaml.safe_load((REPO_ROOT / "playbooks" / f"{name}.yml").read_text(encoding="utf-8"))


def _run(tmp_path: Path, playbook: Path, *args: str) -> subprocess.CompletedProcess:
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(INVENTORY, encoding="utf-8")
    return subprocess.run(
        [_ansible_playbook_bin(), "-i", str(inventory), str(playbook), *args],
        cwd=REPO_ROOT, env=_base_env(tmp_path), capture_output=True, text=True, check=False,
    )


def _guard(tmp_path: Path, name: str, *args: str) -> subprocess.CompletedProcess:
    playbook = tmp_path / "guard.yml"
    playbook.write_text(yaml.safe_dump(_plays(name)[:1], sort_keys=False), encoding="utf-8")
    return _run(tmp_path, playbook, *args)


def test_every_playbook_targets_linux_vitals_hosts_after_the_same_guard() -> None:
    guards = []
    for name in PLAYBOOKS:
        guard, scan = _plays(name)
        assert scan["hosts"] == HOSTS, name
        assert guard["hosts"] == "all:localhost", name
        assert guard["tasks"][0]["tags"] == ["always"], name
        guards.append(guard)
    assert all(guard == guards[0] for guard in guards), "the three guard plays have drifted apart"


@pytest.mark.parametrize("name", PLAYBOOKS)
@pytest.mark.parametrize(
    "args",
    [[], ["--limit", "web01"], ["-e", "linux_vitals_hosts=db", "--limit", "web01"], ["-e", "linux_vitals_hosts=nope*"]],
    ids=["default-group-absent", "default-group-absent-limited", "pattern-outside-limit", "glob-matches-nothing"],
)
def test_a_pattern_that_matches_no_host_fails_and_names_the_variable(tmp_path, name: str, args: list[str]) -> None:
    run = _guard(tmp_path, name, *args)
    assert run.returncode != 0, run.stdout
    assert "linux_vitals_hosts is '" in run.stdout, run.stdout
    assert "-e linux_vitals_hosts=all" in run.stdout, run.stdout


@pytest.mark.parametrize("name", PLAYBOOKS)
@pytest.mark.parametrize(
    "args",
    [["-e", "linux_vitals_hosts=all"], ["-e", "linux_vitals_hosts=web:db"], ["-e", "linux_vitals_hosts=all", "--limit", "db01"]],
    ids=["all", "union", "all-limited"],
)
def test_a_pattern_that_matches_hosts_passes_the_guard(tmp_path, name: str, args: list[str]) -> None:
    run = _guard(tmp_path, name, *args)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("name", PLAYBOOKS)
def test_an_existing_inventory_is_scanned_with_no_file_edits(tmp_path, name: str) -> None:
    run = _run(tmp_path, REPO_ROOT / "playbooks" / f"{name}.yml", "-e", "linux_vitals_hosts=all", "--list-hosts")
    assert run.returncode == 0, run.stdout + run.stderr
    scan_play = run.stdout.split("play #2", 1)[1]
    assert "web01" in scan_play and "db01" in scan_play, run.stdout


@pytest.mark.parametrize("name", PLAYBOOKS)
def test_without_the_variable_the_playbooks_still_target_linux_servers(tmp_path, name: str) -> None:
    run = _run(tmp_path, REPO_ROOT / "playbooks" / f"{name}.yml", "--list-hosts")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "play #2 (linux_servers)" in run.stdout, run.stdout
