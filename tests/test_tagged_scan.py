"""The real `vitals_scan` role under `--tags`, run over the golden fixtures.

The README documents tagged runs, and a tag that goes missing deep in the
discovery tasks breaks them in a way nobody sees in review: a later task reads
a fact that a skipped task never set (#16).
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
exactly. A focused one (`kernel`, `security` or `boot` without `discovery`)
cannot build a result, because `result.yml` reads facts from every slice of
the scan. It must stop at the guard in `main.yml` before any probe runs, and
say which command does work (#138), rather than run on and stop wherever its
slice happens to leave a fact undefined.
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
# Focused selections: a slice of the scan without discovery.
FOCUSED = ["kernel,reporting", "security,reporting", "boot,reporting"]
GUARD = "Require discovery alongside a focused scan tag"


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


@pytest.mark.parametrize("selection", FOCUSED)
def test_a_focused_scan_stops_at_the_guard_and_names_the_command_that_works(runs, selection: str) -> None:
    run = runs[selection]
    output = run["output"]
    assert run["rc"] != 0, f"--tags {selection} ran without discovery and did not stop"
    assert run["results"] == {}, "a host built a result without discovery"
    # Stopped at the guard, before any probe, not on a fact its slice left unset.
    tasks = re.findall(r"^TASK \[(.+?)\]", output, re.MULTILINE)
    assert tasks[-1] == f"{ROLE_UNDER_TEST} : {GUARD}", tasks
    assert "is undefined" not in output, output[-4000:]
    # ansible_run_tags carries no order, so compare the suggested tags as a set.
    suggested = [set(tags.split(",")) for tags in re.findall(r"e\.g\. --tags (\w+(?:,\w+)*)", output)]
    assert {"discovery", *selection.split(",")} in suggested, output[-4000:]
