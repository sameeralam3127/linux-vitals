"""Golden-file tests for every vitals_scan finding (issue #98).

Each fixture in `tests/fixtures/state/` is one host's collected state, in the
shape `docs/state-schema.md` specifies (`state_schema: 1`). These tests run
that state through the **real, unmodified** scan tasks -- every set_fact in
`discovery.yml`, `reboot_facts.yml`, `services.yml`, `result.yml` and
`severity.yml` -- and compare the per-host result object against a snapshot in
`tests/golden/`.

Only the collection tasks are replaced: `setup` and `service_facts` become one
`set_fact` of `ansible_facts`, and each `command` probe becomes a `set_fact`
of the variable it registers, built from the fixture. Each probe keeps its
production `when:`, so a fixture cannot feed data to a probe the scan would
have skipped on that distro -- `test_fixture_probes_match_what_the_scan_ran`
fails if one tries. A task the adapter does not recognise also fails the
suite rather than being skipped: when a new probe lands (#30, #31, #33), this
file has to be taught about it, which is the point.

A golden diff *is* a behaviour change. When one is intended, regenerate with

    LINUX_VITALS_UPDATE_GOLDEN=1 pytest tests/test_golden_findings.py

and put the diff in the pull request -- see docs/testing.md.

Values are compared after normalising numeric and boolean strings, because
ansible-core 2.16 (the declared floor) stores a scalar template result as a
string where newer cores keep the native type. Without that the same snapshot
could not pass on both. The types themselves are asserted elsewhere
(`test_numeric_coercion.py`, `test_core216_compat.py`).

`vitals_certs` findings are out of scope (the role is frozen during the
refactor), and so is `service_manual_followup`, which depends on what
`vitals_heal` did rather than on collected state; `test_self_healing.py`
covers it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

STATE_DIR = REPO_ROOT / "tests" / "fixtures" / "state"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
TASKS_DIR = REPO_ROOT / "roles" / "vitals_scan" / "tasks"
SCAN_DEFAULTS = REPO_ROOT / "roles" / "vitals_scan" / "defaults" / "main.yml"

UPDATE_GOLDEN = os.environ.get("LINUX_VITALS_UPDATE_GOLDEN") == "1"

# Every registered probe in discovery.yml, mapped to the state-schema probe
# that feeds it. The three reboot probes share one schema entry: exactly one
# of them runs, chosen by os_family.
PROBE_FOR_REGISTER = {
    "linux_vitals_journalctl": "logs",
    "linux_vitals_failed_login_attempts_cmd": "failed_logins",
    "linux_vitals_last_reboot_cmd": "last_reboot",
    "linux_vitals_latest_kernel_cmd": "installed_kernels",
    "linux_vitals_bootloader_default_cmd": "bootloader",
    "linux_vitals_debian_reboot_cmd": "reboot_required",
    "linux_vitals_redhat_reboot_cmd": "reboot_required",
    "linux_vitals_suse_reboot_cmd": "reboot_required",
    "linux_vitals_selinux_cmd": "selinux",
    "linux_vitals_apparmor_cmd": "apparmor",
    "linux_vitals_rescue_image_cmd": "rescue_images",
    "linux_vitals_audit_journalctl": "audit_logs",
}

# The key=value blocks the shell probes print, in the order they print them.
# The schema stores these parsed; the adapter prints them back so the real
# regex_findall parsing in discovery.yml and reboot_facts.yml still runs.
KEY_VALUE_PROBES = {
    "installed_kernels": ["latest", "updated_at", "filtered"],
    "bootloader": ["supported", "source", "default_entry", "default_kernel", "status"],
    "reboot_required": ["supported", "detected", "source", "detail", "packages"],
}
LINE_PROBES = {"failed_logins", "rescue_images"}

SKIPPED = {"changed": False, "skipped": True, "skip_reason": "Conditional result was False"}


def _fixture_paths() -> list[Path]:
    return sorted(STATE_DIR.glob("*.yml"))


def _fixture_names() -> list[str]:
    return [path.stem for path in _fixture_paths()]


def _load_fixture(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# state document -> what the collection tasks would have produced
# ---------------------------------------------------------------------------

def _ansible_facts(state: dict) -> dict:
    host, platform, memory = state["host"], state["platform"], state["memory"]
    facts = {
        key: value
        for key, value in {
            "hostname": host["hostname"],
            "product_serial": host["product_serial"],
            **platform,
            "memtotal_mb": memory["total_mb"],
            "memavailable_mb": memory["available_mb"],
            "memfree_mb": memory["free_mb"],
        }.items()
        # The schema writes null for an absent fact; setup would simply not
        # have returned it, so the task's own default() applies.
        if value is not None
    }
    if host["ip_address"] is not None:
        facts["default_ipv4"] = {"address": host["ip_address"]}
    facts["mounts"] = state["mounts"]
    facts["services"] = {
        name: {"name": name, "state": unit["state"], "status": unit["status"]}
        for name, unit in state["services"].items()
    }
    return facts


def _print_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(value)
    return str(value)


def _registered(probe_name: str, probe: dict) -> dict:
    if not probe["ran"]:
        return dict(SKIPPED)
    if probe_name in KEY_VALUE_PROBES:
        stdout = "\n".join(
            f"{key}={_print_value(probe[key])}" for key in KEY_VALUE_PROBES[probe_name]
        )
        stdout_lines = stdout.splitlines()
    elif probe_name in LINE_PROBES:
        stdout_lines = list(probe["stdout_lines"])
        stdout = "\n".join(stdout_lines)
    else:
        stdout = probe.get("stdout", "")
        stdout_lines = stdout.splitlines()
    return {
        "changed": False,
        "failed": False,
        "rc": probe["rc"],
        "stdout": stdout,
        "stdout_lines": stdout_lines,
        "stderr": "",
        "stderr_lines": [],
    }


def _host_vars(fixture: dict) -> dict:
    state = fixture["state"]
    assert state["state_schema"] == 1
    probes = state["probes"]
    missing = sorted(set(PROBE_FOR_REGISTER.values()) - set(probes))
    assert not missing, f"fixture is missing probes: {missing}"
    return {
        "ansible_connection": "local",
        "ansible_python_interpreter": "{{ ansible_playbook_python }}",
        "golden_facts": _ansible_facts(state),
        "golden_probes": {
            register: _registered(probe, probes[probe])
            for register, probe in PROBE_FOR_REGISTER.items()
        },
        **fixture.get("role_vars", {}),
    }


# ---------------------------------------------------------------------------
# the scan's task files, with collection swapped for the fixture
# ---------------------------------------------------------------------------

def _module(task: dict) -> str:
    modules = [key for key in task if key.startswith("ansible.builtin.")]
    assert len(modules) == 1, f"cannot tell the module of task {task.get('name')!r}"
    return modules[0]


def _adapt(task: dict, source: Path) -> list[dict]:
    module = _module(task)
    name = task["name"]

    if module == "ansible.builtin.setup":
        return [{"name": f"{name} (golden: seeded)",
                 "ansible.builtin.set_fact": {"ansible_facts": "{{ golden_facts }}"}}]
    if module == "ansible.builtin.service_facts":
        return []  # services are part of the seeded ansible_facts
    if module == "ansible.builtin.command":
        register = task.get("register")
        assert register in PROBE_FOR_REGISTER, (
            f"{source.name}: probe {name!r} registers {register!r}, which the golden "
            "adapter does not know. Add it to PROBE_FOR_REGISTER and to the state schema."
        )
        seeded = {
            "name": f"{name} (golden: seeded)",
            "ansible.builtin.set_fact": {
                register: "{{ golden_probes['" + register + "'] }}",
                "golden_ran_" + register: True,
            },
        }
        if "when" not in task:
            return [seeded]
        seeded["when"] = task["when"]
        # A probe skipped by its `when:` still registers, as a skipped result.
        return [{"name": f"{name} (golden: skipped by default)",
                 "ansible.builtin.set_fact": {register: SKIPPED}}, seeded]
    if module == "ansible.builtin.set_fact":
        return [task]
    if module == "ansible.builtin.include_tasks":
        included = TASKS_DIR / task[module]
        assert included.is_file(), f"{source.name} includes missing {included}"
        return [dict(task, **{module: str(included)})]
    raise AssertionError(
        f"{source.name}: task {name!r} uses {module}, which the golden adapter does not "
        "handle. Teach _adapt() about it rather than letting the golden tests skip it."
    )


def _scan_tasks() -> list[dict]:
    tasks: list[dict] = []
    for filename in ("discovery.yml", "result.yml"):
        path = TASKS_DIR / filename
        for task in yaml.safe_load(path.read_text(encoding="utf-8")):
            tasks.extend(_adapt(task, path))
    return tasks


def _dump_task() -> dict:
    ran = ", ".join(
        f"'{register}': golden_ran_{register} | default(false)"
        for register in PROBE_FOR_REGISTER
    )
    return {
        "name": "Write the per-host result for comparison",
        "ansible.builtin.copy": {
            "content": "{{ {'result': linux_vitals_result, 'ran': {" + ran + "}} | to_nice_json }}\n",
            "dest": "{{ output_dir }}/{{ inventory_hostname }}.json",
            "mode": "0644",
        },
    }


@pytest.fixture(scope="module")
def scan_output(tmp_path_factory) -> dict[str, dict]:
    """Run every fixture through the scan once, as one host each."""
    tmp_path = tmp_path_factory.mktemp("golden")
    defaults = yaml.safe_load(SCAN_DEFAULTS.read_text(encoding="utf-8"))
    inventory = {
        "all": {
            "vars": {
                **defaults,
                "output_dir": "{{ lookup('ansible.builtin.env', 'TEST_OUTPUT_DIR') }}",
            },
            "hosts": {
                f"golden-{path.stem}": _host_vars(_load_fixture(path))
                for path in _fixture_paths()
            },
        }
    }
    playbook = [{
        "name": "Run the real scan tasks over fixture host state",
        "hosts": "all",
        "gather_facts": False,
        "tasks": _scan_tasks() + [_dump_task()],
    }]
    inventory_path = tmp_path / "inventory.yml"
    playbook_path = tmp_path / "golden_scan.yml"
    inventory_path.write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")
    playbook_path.write_text(yaml.safe_dump(playbook, sort_keys=False), encoding="utf-8")

    env = _base_env(tmp_path)
    # Fixture hosts must never pick up facts cached from a real run.
    env["ANSIBLE_CACHE_PLUGIN"] = "memory"
    env["ANSIBLE_FORKS"] = "20"
    subprocess.run(
        [_ansible_playbook_bin(), "-i", str(inventory_path), str(playbook_path)],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return {
        name: json.loads((tmp_path / f"golden-{name}.json").read_text(encoding="utf-8"))
        for name in _fixture_names()
    }


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _normalise(value):
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    if isinstance(value, str):
        if value in ("True", "False"):
            return value == "True"
        if _NUMBER.fullmatch(value):
            return float(value) if "." in value else int(value)
    return value


def _serialise(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def test_there_is_a_fixture_per_distro_family_and_condition() -> None:
    names = set(_fixture_names())
    for family in ("ubuntu", "rocky", "fedora", "opensuse"):
        for condition in ("healthy", "degraded", "critical"):
            assert f"{family}_{condition}" in names


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda path: path.stem)
def test_fixture_says_what_it_represents(path: Path) -> None:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("# ") and len(first_line) > 10, (
        f"{path.name} must open with a one-line comment saying what it represents"
    )


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda path: path.stem)
def test_fixture_contains_no_jinja(path: Path) -> None:
    # Fixture values reach Ansible as inventory variables, which are
    # templated. Real log lines can contain braces; these must not.
    text = path.read_text(encoding="utf-8")
    assert "{{" not in text and "{%" not in text


@pytest.mark.parametrize("name", _fixture_names())
def test_fixture_probes_match_what_the_scan_ran(scan_output: dict, name: str) -> None:
    probes = _load_fixture(STATE_DIR / f"{name}.yml")["state"]["probes"]
    ran = scan_output[name]["ran"]
    for probe in sorted(set(PROBE_FOR_REGISTER.values())):
        registers = [r for r, p in PROBE_FOR_REGISTER.items() if p == probe]
        scan_ran = any(ran[register] for register in registers)
        assert scan_ran == probes[probe]["ran"], (
            f"{name}: probes.{probe}.ran is {probes[probe]['ran']} but the scan "
            f"{'ran' if scan_ran else 'skipped'} it for this host's platform"
        )


@pytest.mark.parametrize("name", _fixture_names())
def test_scan_result_matches_golden(scan_output: dict, name: str) -> None:
    actual = _serialise(_normalise(scan_output[name]["result"]))
    golden = GOLDEN_DIR / f"{name}.json"
    if UPDATE_GOLDEN:
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
    assert golden.is_file(), (
        f"no golden file for {name}; generate it with LINUX_VITALS_UPDATE_GOLDEN=1"
    )
    assert actual == golden.read_text(encoding="utf-8"), (
        f"{name}: the scan result changed. If that is intended, regenerate with "
        "LINUX_VITALS_UPDATE_GOLDEN=1 and put the diff in the pull request."
    )


def test_every_scan_finding_is_exercised_by_a_golden_file() -> None:
    # A finding added to the shipped severity map without a fixture that
    # fires it would have no regression net. service_manual_followup is the
    # one exception: it comes from vitals_heal, not from collected state.
    defaults = yaml.safe_load(SCAN_DEFAULTS.read_text(encoding="utf-8"))
    expected = set(defaults["linux_vitals_finding_severities"]) - {"service_manual_followup"}
    fired = {
        finding["id"]
        for path in GOLDEN_DIR.glob("*.json")
        for finding in json.loads(path.read_text(encoding="utf-8"))["findings"]
    }
    assert sorted(expected - fired) == []


def test_every_golden_file_has_a_fixture() -> None:
    orphans = sorted(
        path.name for path in GOLDEN_DIR.glob("*.json") if path.stem not in _fixture_names()
    )
    assert not orphans, f"golden files with no fixture: {orphans}"
