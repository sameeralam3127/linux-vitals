"""The real `vitals_scan` role under `--tags`, run over the golden fixtures.

The README documents `--tags kernel,reporting` for a kernel-only run, and a
tag that goes missing deep in the discovery tasks breaks it in a way nobody
sees in review: a later task reads a fact that a skipped task never set (#16).
The golden tests (`test_golden_findings.py`) cannot catch that. They run the
tasks flattened into one untagged play, so neither tags nor the role's
include/import structure is exercised.

This runs the role itself: `main.yml`'s `include_tasks` with `apply: tags`,
`discovery.yml`'s imports, the nested includes and `result.yml`, each task
with its production tags. Only collection is swapped out, the way the golden
tests do it: `setup` and each `command` probe become a `set_fact` of what the
fixture says the host returned. Here each replacement keeps the tags of the
task it replaces, since tags are what is under test, and a play-level task
tagged `always` stands in for `gather_facts`.

A selection that runs every scan task must reproduce the golden result
exactly. A narrower one must still build a result of the same shape.

`KNOWN_TAG_GAPS` lists the selections that do not build a result today, each
with the facts it is known to stop on. They fail the same way on `main`
before #27 (checked by running both), and fixing them would change behaviour,
which a structural refactor must not do. Each is a strict xfail that only
accepts that exact failure: a run that stops anywhere else fails the test,
and one that starts working fails it too, until its entry is removed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from test_golden_findings import (
    GOLDEN_DIR,
    STATE_DIR,
    _adapt,
    _fixture_names,
    _host_vars,
    _load_fixture,
    _module,
    _normalise,
    _serialise,
)
from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

SCAN_ROLE = REPO_ROOT / "roles" / "vitals_scan"
# A name nothing else can resolve to, so the run can only use the copy.
ROLE_UNDER_TEST = "vitals_scan_under_tags"
COLLECTION = {"ansible.builtin.setup", "ansible.builtin.service_facts", "ansible.builtin.command"}

# Selections that run every scan task, so the result must match the golden file.
# discovery,kernel,reporting is the one docs/troubleshooting.md suggests.
FULL_SCAN = ["untagged", "discovery,kernel,reporting"]
# Selections the README documents for a focused run.
FOCUSED = ["kernel,reporting", "security,reporting", "boot,reporting"]

# Each selection that does not complete today, and the facts it stops on.
# Which one depends on ansible-core: 2.16 stops at "Finalize extended discovery
# facts" (linux_vitals_bootloader_default_cmd, registered by a kernel-only
# probe), while newer cores tolerate that and stop in result.yml instead
# (linux_vitals_service_status, set by services.yml, tagged discovery only).
# kernel stops at "Evaluate journal probe availability" on every core: it reads
# linux_vitals_journalctl, registered by a probe tagged discovery only.
KNOWN_TAG_GAPS = {
    "kernel,reporting": {"linux_vitals_journalctl"},
    "security,reporting": {"linux_vitals_service_status", "linux_vitals_bootloader_default_cmd"},
    "boot,reporting": {"linux_vitals_service_status", "linux_vitals_bootloader_default_cmd"},
}


class KnownTagGap(Exception):
    """The run stopped on a fact KNOWN_TAG_GAPS says this selection leaves undefined."""


def _keeping_tags(task: dict, source: Path) -> list[dict]:
    if _module(task) not in COLLECTION:
        return [task]
    replaced = _adapt(task, source)
    if "tags" not in task:
        return replaced
    return [dict(new, tags=task["tags"]) for new in replaced]


def _role_copy(roles_dir: Path) -> None:
    role = roles_dir / ROLE_UNDER_TEST
    shutil.copytree(SCAN_ROLE, role)
    for path in sorted((role / "tasks").glob("*.yml")):
        tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
        adapted = [new for task in tasks for new in _keeping_tags(task, path)]
        path.write_text(yaml.safe_dump(adapted, sort_keys=False), encoding="utf-8")


def _playbook() -> list[dict]:
    return [{
        "name": "Run the vitals_scan role over fixture host state",
        "hosts": "all",
        "gather_facts": False,
        "pre_tasks": [{
            # gather_facts runs whatever the tags. It does not collect services;
            # the stand-in for service_facts is the discovery-tagged setup task.
            "name": "Stand in for gather_facts",
            "ansible.builtin.set_fact": {
                "ansible_facts": (
                    "{{ golden_facts | dict2items"
                    " | rejectattr('key', 'equalto', 'services') | items2dict }}"
                ),
            },
            "tags": ["always"],
        }],
        "roles": [ROLE_UNDER_TEST],
        "post_tasks": [{
            "name": "Write the per-host result",
            "ansible.builtin.copy": {
                "content": "{{ linux_vitals_result | to_nice_json }}\n",
                "dest": "{{ output_dir }}/{{ inventory_hostname }}.json",
                "mode": "0644",
            },
            "tags": ["always"],
        }],
    }]


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, dict]:
    """Run every selection at once, each in its own output directory."""
    base = tmp_path_factory.mktemp("tagged")
    _role_copy(base / "roles")
    inventory = {
        "all": {
            "vars": {"output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}"},
            "hosts": {
                f"golden-{name}": _host_vars(_load_fixture(STATE_DIR / f"{name}.yml"))
                for name in _fixture_names()
            },
        }
    }
    (base / "inventory.yml").write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")
    (base / "scan.yml").write_text(yaml.safe_dump(_playbook(), sort_keys=False), encoding="utf-8")

    started = {}
    for selection in FULL_SCAN + FOCUSED:
        out = base / selection.replace(",", "+")
        out.mkdir()
        env = _base_env(out)
        env["ANSIBLE_CACHE_PLUGIN"] = "memory"
        env["ANSIBLE_FORKS"] = "20"
        env["ANSIBLE_ROLES_PATH"] = str(base / "roles")
        command = [_ansible_playbook_bin(), "-i", str(base / "inventory.yml"), str(base / "scan.yml")]
        if selection != "untagged":
            command += ["--tags", selection]
        started[selection] = (out, subprocess.Popen(
            command, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        ))

    finished = {}
    for selection, (out, process) in started.items():
        output, _ = process.communicate()
        finished[selection] = {
            "rc": process.returncode,
            "output": output,
            "results": {
                name: json.loads((out / f"golden-{name}.json").read_text(encoding="utf-8"))
                for name in _fixture_names()
                if (out / f"golden-{name}.json").is_file()
            },
        }
    return finished


def _check(run: dict, selection: str, compare) -> None:
    undefined = set(re.findall(r"'(\w+)' is undefined", run["output"]))
    if run["rc"] != 0 and undefined and undefined <= KNOWN_TAG_GAPS.get(selection, set()):
        raise KnownTagGap(f"--tags {selection} stops on undefined {sorted(undefined)}")
    assert run["rc"] == 0, f"--tags {selection} failed:\n{run['output'][-4000:]}"
    assert sorted(run["results"]) == _fixture_names(), "a host built no result"
    for name, result in run["results"].items():
        compare(name, result)


@pytest.mark.parametrize("selection", FULL_SCAN)
def test_a_full_scan_through_the_role_reproduces_the_golden_result(runs, selection: str) -> None:
    def compare(name: str, result: dict) -> None:
        golden = (GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8")
        assert _serialise(_normalise(result)) == golden, f"{name} under --tags {selection}"

    _check(runs[selection], selection, compare)


@pytest.mark.parametrize(
    "selection",
    [
        pytest.param(
            selection,
            marks=pytest.mark.xfail(
                strict=True,
                raises=KnownTagGap,
                reason=f"pre-existing tag gap: stops on {sorted(KNOWN_TAG_GAPS[selection])}",
            ),
        )
        if selection in KNOWN_TAG_GAPS
        else selection
        for selection in FOCUSED
    ],
)
def test_a_focused_scan_builds_a_complete_result(runs, selection: str) -> None:
    def compare(name: str, result: dict) -> None:
        golden = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert sorted(result) == sorted(golden), f"{name} under --tags {selection}"

    _check(runs[selection], selection, compare)
