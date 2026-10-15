"""Bounded journal scans (#23).

Both journal probes used to ship their whole time window to the control node,
where Jinja matched it, and the full match lists were kept as host facts. Now
the filtering happens on the managed host and both probes are capped at
`linux_vitals_log_max_lines`:

- the error scan asks journalctl for entries at `linux_vitals_log_priority`
  or worse, newest first (`--reverse`) up to the cap;
- the kernel-failure scan pipes the journal through grep with the pattern the
  control node used to apply, unchanged, and keeps the newest matches up to
  the cap. The pipeline must still tell "nothing matched" (grep exits 1) from
  "journalctl could not read the journal", or #118's unknown path breaks.

The pipeline tests run the real script from `kernel_install_failures.yml` under
bash, with a stub `journalctl` on PATH, so they need no systemd. What a real
journalctl does with these arguments is proved by the Molecule scenarios
(`molecule/resources/tasks/journal_bound.yml`).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from shutil import which

import pytest
import yaml

from scan_tasks import scan_task, scan_tasks
from test_discovery_facts import _run_playbook
from test_templates import REPO_ROOT

STATE_DIR = REPO_ROOT / "tests" / "fixtures" / "state"
MOLECULE_RESOURCES = REPO_ROOT / "molecule" / "resources"

ERROR_PROBE = "Collect recent systemd log errors"
AUDIT_PROBE = "Collect kernel install failures from logs"
SUMMARY_TASK = "Summarise journal scans as counts and excerpts"
AVAILABILITY_TASK = "Evaluate journal probe availability"

# The control-node regex kernel_install_failures used before #23. The host-side
# grep must select exactly the lines this did.
PRE_23_KERNEL_FAILURE_REGEX = r"(?im)^.*(?:kernel|grub|dracut|initramfs).*(?:fail|error).*$"

JOURNAL_REGISTERS = ("linux_vitals_journalctl", "linux_vitals_audit_journalctl")


def _tasks() -> list[dict]:
    return scan_tasks()


def _task(name: str) -> dict:
    return scan_task(name)


# ---------------------------------------------------------------------------
# The error scan: priority and cap are applied by journalctl on the host
# ---------------------------------------------------------------------------

def test_error_scan_filters_by_priority_and_caps_on_the_host() -> None:
    argv = _task(ERROR_PROBE)["ansible.builtin.command"]["argv"]

    assert argv[0] == "journalctl"
    assert "--system" in argv
    assert argv[argv.index("--since") + 1] == "{{ linux_vitals_log_window }}"
    assert argv[argv.index("--priority") + 1] == "{{ linux_vitals_log_priority }}"
    # --lines takes an optional argument: a separate argv element would not be
    # read as its value, so it must be attached with '='.
    assert "--lines={{ linux_vitals_log_max_lines | int }}" in argv
    # Before systemd v254, --lines with --since kept the oldest entries in the
    # window. Reading newest first keeps the newest on every version.
    assert "--reverse" in argv


# ---------------------------------------------------------------------------
# The kernel-failure scan: a grep pipeline on the host
# ---------------------------------------------------------------------------

def _audit_argv() -> tuple[str, str, str, str]:
    argv = _task(AUDIT_PROBE)["ansible.builtin.command"]["argv"]
    assert argv[:2] == ["bash", "-c"], "the pipeline needs bash for pipefail"
    script, name, window, pattern, cap = argv[2:]
    assert window == "{{ linux_vitals_audit_log_window }}"
    assert cap == "{{ linux_vitals_log_max_lines | int }}"
    return script, name, pattern, cap


def test_audit_script_takes_every_templated_value_as_a_parameter() -> None:
    # docs/threat-model.md: a shell script with a {{ }} in it is a
    # command-injection bug. Values go in their own argv elements.
    script, _, pattern, _ = _audit_argv()

    assert "{{" not in script and "{%" not in script
    assert "{{" not in pattern
    assert "set -o pipefail" in script


def _run_audit_probe(
    tmp_path: Path,
    *,
    journal: str = "",
    stderr: str = "",
    rc: int = 0,
    cap: int = 2000,
    grep_rc: int | None = None,
) -> subprocess.CompletedProcess:
    """Run the real probe script against a stub journalctl."""
    script, name, pattern, _ = _audit_argv()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "journal.out").write_text(journal, encoding="utf-8")
    (tmp_path / "journal.err").write_text(stderr, encoding="utf-8")
    stub = bin_dir / "journalctl"
    stub.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(tmp_path / 'journalctl.args'))}\n"
        f"cat {shlex.quote(str(tmp_path / 'journal.out'))}\n"
        f"cat {shlex.quote(str(tmp_path / 'journal.err'))} >&2\n"
        f"exit {rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    if grep_rc is not None:
        broken_grep = bin_dir / "grep"
        broken_grep.write_text(f"#!/bin/sh\necho 'grep: broken' >&2\nexit {grep_rc}\n", encoding="utf-8")
        broken_grep.chmod(0o755)

    bash = which("bash")
    assert bash, "bash is required to run the kernel-failure probe script"
    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", LC_ALL="C")
    return subprocess.run(
        [bash, "-c", script, name, "7 days ago", pattern, str(cap)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# Lines a real 7-day journal could hold, chosen to probe the pattern's edges.
AUDIT_CORPUS = "\n".join([
    "-- Boot 3f0c1a --",
    "2026-09-24T01:02:03+0000 db-02 dracut[4410]: dracut-install: Failed to find module 'xfs'",
    "2026-09-24T01:02:05+0000 db-02 kernel-install[4402]: /usr/lib/kernel/install.d/50-dracut.install failed with exit status 1.",
    "2026-09-25T02:14:51+0000 web-02 update-initramfs[88210]: update-initramfs: failed for /boot/initrd.img-6.8.0-45-generic with 1.",
    # initramfs, but nothing says it failed.
    "2026-09-25T02:14:52+0000 web-02 run-parts[88213]: /etc/kernel/postinst.d/initramfs-tools exited with return code 1",
    "2026-09-24T07:18:10+0000 app-04 grub2-mkconfig[5102]: /etc/grub.d/40_custom: line 7: syntax error near unexpected token",
    # The match runs over the whole line: here "kernel" is only the identifier.
    "2026-09-24T07:20:00+0000 app-04 kernel: EXT4-fs error (device sda1): ext4_find_entry:1455: inode #2",
    # Case-insensitive.
    "2026-09-24T07:21:00+0000 app-04 DRACUT[11]: FAILED to install module",
    # Order matters: the failure word comes before the keyword.
    "2026-09-24T07:22:00+0000 app-04 systemd[1]: Failed to start grub-boot-success.service.",
    "2026-09-20T06:12:04+0000 db-01 kernel: Linux version 5.14.0-427.13.1.el9_4.x86_64 (mockbuild@build)",
    "2026-09-20T06:13:00+0000 db-01 sshd[41230]: Failed password for root from 10.0.1.5 port 51022 ssh2",
    # A continuation line of a multi-line message is matched as a line, as before.
    "                                         initramfs generation error on line 3",
    "-- Reboot --",
    "2026-09-26T13:45:00+0000 ws-07 systemd[1]: Started dnf-makecache.service - dnf makecache.",
])


def test_host_side_grep_keeps_exactly_the_lines_the_old_regex_matched(tmp_path: Path) -> None:
    completed = _run_audit_probe(tmp_path, journal=AUDIT_CORPUS + "\n")

    assert completed.returncode == 0, completed.stderr
    expected = re.findall(PRE_23_KERNEL_FAILURE_REGEX, AUDIT_CORPUS)
    assert len(expected) == 7  # guards the corpus itself
    assert completed.stdout.splitlines() == expected


def test_audit_probe_reads_the_system_journal_for_the_window(tmp_path: Path) -> None:
    _run_audit_probe(tmp_path)

    args = (tmp_path / "journalctl.args").read_text(encoding="utf-8").splitlines()
    assert "--system" in args
    assert args[args.index("--since") + 1] == "7 days ago"
    assert "--output=short-iso" in args


def test_no_match_is_a_clean_read_not_a_failure(tmp_path: Path) -> None:
    # grep exits 1 when nothing matches. That must not reach the probe's rc,
    # or every host without a kernel failure would report `unknown`.
    completed = _run_audit_probe(
        tmp_path,
        journal="2026-09-26T13:45:00+0000 ws-07 systemd[1]: Started dnf-makecache.service.\n",
    )

    assert completed.returncode == 0
    assert completed.stdout == ""


def test_an_empty_journal_is_a_clean_read(tmp_path: Path) -> None:
    completed = _run_audit_probe(tmp_path, journal="-- No entries --\n")

    assert completed.returncode == 0
    assert completed.stdout == ""


@pytest.mark.parametrize(
    "journal",
    ["", "2026-09-24T01:02:03+0000 db-02 dracut[4410]: dracut-install: Failed to find module 'xfs'\n"],
    ids=["nothing-read", "partial-read"],
)
def test_a_failed_journalctl_is_still_a_failure(tmp_path: Path, journal: str) -> None:
    # Without pipefail the pipeline's status is tail's, and this would read as
    # a clean host. With it, the unknown path from #118 still fires.
    message = "No journal files were opened due to insufficient permissions."
    completed = _run_audit_probe(tmp_path, journal=journal, stderr=message + "\n", rc=1)

    assert completed.returncode == 1
    assert message in completed.stderr


def test_the_partial_journal_hint_still_reaches_stderr(tmp_path: Path) -> None:
    # journalctl exits 0 when it can read only the caller's own journal; the
    # availability check recognises that from this hint on stderr.
    hint = "Hint: You are currently not seeing messages from other users and the system."
    completed = _run_audit_probe(tmp_path, stderr=hint + "\n")

    assert completed.returncode == 0
    assert hint in completed.stderr


def test_a_grep_error_is_a_failure(tmp_path: Path) -> None:
    completed = _run_audit_probe(tmp_path, journal="anything\n", grep_rc=2)

    assert completed.returncode == 2


def test_audit_probe_keeps_only_the_newest_matches_up_to_the_cap(tmp_path: Path) -> None:
    journal = "".join(
        f"2026-09-24T01:{n:02d}:00+0000 db-02 dracut[{n}]: dracut-install: Failed to find module {n}\n"
        for n in range(50)
    )
    completed = _run_audit_probe(tmp_path, journal=journal, cap=3)

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == journal.splitlines()[-3:]


# ---------------------------------------------------------------------------
# What is kept: a count and an excerpt, never the matched lines
# ---------------------------------------------------------------------------

def _summarise(tmp_path: Path, error_probe: dict, audit_probe: dict) -> dict:
    task = {key: value for key, value in _task(SUMMARY_TASK).items() if key != "tags"}
    facts = (
        "linux_vitals_log_errors",
        "linux_vitals_log_excerpt",
        "linux_vitals_kernel_install_failures",
        "linux_vitals_kernel_install_failure_excerpt",
    )
    dump = "{{ {" + ", ".join(f"'{fact}': {fact}" for fact in facts) + "} | to_nice_json }}\n"
    tasks = [
        {
            "name": "Seed the journal probe results",
            "ansible.builtin.set_fact": {
                "linux_vitals_journalctl": error_probe,
                "linux_vitals_audit_journalctl": audit_probe,
            },
        },
        task,
        {
            "name": "Write the result for assertion",
            "ansible.builtin.copy": {
                "content": dump,
                "dest": "{{ output_dir }}/discovery_fact.json",
                "mode": "0644",
            },
        },
    ]
    return _run_playbook(tmp_path, tasks)


def test_log_errors_counts_entries_and_keeps_a_five_line_excerpt(tmp_path: Path) -> None:
    entries = [f"2026-09-26T13:{n:02d}:00+0000 web-01 app[{n}]: request {n} failed" for n in range(7)]
    # journalctl --reverse prints the newest entry first.
    stdout = "\n".join([
        entries[6],
        entries[5],
        entries[4],
        "-- Boot 3f0c1a --",
        entries[3],
        "",
        entries[2],
        # A multi-line message is one entry: its continuation is indented.
        "                                          caused by: connection reset",
        entries[1],
        entries[0],
    ])
    audit = [f"2026-09-24T01:0{n}:00+0000 db-02 dracut[1]: dracut-install: Failed {n}" for n in range(6)]

    result = _summarise(
        tmp_path,
        {"rc": 0, "stdout": stdout, "stdout_lines": stdout.splitlines()},
        {"rc": 0, "stdout": "\n".join(audit), "stdout_lines": audit},
    )

    assert int(result["linux_vitals_log_errors"]) == 7
    # Back in time order, so the excerpt opens with the oldest, as it always has.
    assert result["linux_vitals_log_excerpt"] == entries[:5]
    assert int(result["linux_vitals_kernel_install_failures"]) == 6
    assert result["linux_vitals_kernel_install_failure_excerpt"] == audit[:5]


def test_no_entries_marker_is_not_an_error(tmp_path: Path) -> None:
    result = _summarise(
        tmp_path,
        {"rc": 0, "stdout": "-- No entries --", "stdout_lines": ["-- No entries --"]},
        {"rc": 0, "stdout": "", "stdout_lines": []},
    )

    assert int(result["linux_vitals_log_errors"]) == 0
    assert result["linux_vitals_log_excerpt"] == []
    assert int(result["linux_vitals_kernel_install_failures"]) == 0


def test_skipped_probes_summarise_to_zero(tmp_path: Path) -> None:
    skipped = {"changed": False, "skipped": True}
    result = _summarise(tmp_path, skipped, skipped)

    assert int(result["linux_vitals_log_errors"]) == 0
    assert result["linux_vitals_log_excerpt"] == []
    assert int(result["linux_vitals_kernel_install_failures"]) == 0
    assert result["linux_vitals_kernel_install_failure_excerpt"] == []


def test_no_fact_keeps_the_matched_journal_lines() -> None:
    # Before #23 linux_vitals_log_matches and linux_vitals_kernel_failure_matches
    # held every matching line for the rest of the play. Any set_fact that
    # reads a journal probe may now set only these.
    allowed = {
        "linux_vitals_journal_checks",
        "linux_vitals_log_errors",
        "linux_vitals_log_excerpt",
        "linux_vitals_kernel_install_failures",
        "linux_vitals_kernel_install_failure_excerpt",
    }
    for task in _tasks():
        facts = task.get("ansible.builtin.set_fact")
        if not facts:
            continue
        text = yaml.safe_dump({key: value for key, value in task.items() if key != "name"})
        if any(register in text for register in JOURNAL_REGISTERS):
            assert set(facts) <= allowed, f"{task['name']!r} keeps journal data in {sorted(set(facts) - allowed)}"


# ---------------------------------------------------------------------------
# A cap below 1 is a check that looked at nothing
# ---------------------------------------------------------------------------

def _journal_checks(tmp_path: Path, max_lines: int) -> dict:
    task = {key: value for key, value in _task(AVAILABILITY_TASK).items() if key != "tags"}
    clean = {"rc": 0, "stdout": "", "stderr": ""}
    tasks = [
        {
            "name": "Seed a systemd host whose journal reads succeeded",
            "ansible.builtin.set_fact": {
                "ansible_facts": {"service_mgr": "systemd"},
                "linux_vitals_journalctl": clean,
                "linux_vitals_audit_journalctl": clean,
                "linux_vitals_log_max_lines": max_lines,
            },
        },
        task,
        {
            "name": "Write the result for assertion",
            "ansible.builtin.copy": {
                "content": "{{ linux_vitals_journal_checks | to_nice_json }}\n",
                "dest": "{{ output_dir }}/discovery_fact.json",
                "mode": "0644",
            },
        },
    ]
    return _run_playbook(tmp_path, tasks)


def test_a_zero_line_cap_makes_both_journal_checks_unknown(tmp_path: Path) -> None:
    checks = _journal_checks(tmp_path, 0)

    assert set(checks) == {"log_errors", "kernel_install_failures"}
    for reason in checks.values():
        assert "linux_vitals_log_max_lines is 0" in reason


def test_a_positive_cap_leaves_successful_reads_clean(tmp_path: Path) -> None:
    assert _journal_checks(tmp_path, 1) == {"log_errors": "", "kernel_install_failures": ""}


# ---------------------------------------------------------------------------
# Golden fixtures hold what the host-filtered probes return
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(STATE_DIR.glob("*.yml")), ids=lambda p: p.stem)
def test_audit_log_fixtures_hold_only_lines_the_host_side_grep_returns(path: Path) -> None:
    # The scan no longer matches on the control node, so a fixture line the
    # host-side grep would have dropped would count as a kernel failure.
    stdout = yaml.safe_load(path.read_text(encoding="utf-8"))["state"]["probes"]["audit_logs"]["stdout"]
    lines = [line for line in (stdout or "").splitlines() if line]

    assert lines == re.findall(PRE_23_KERNEL_FAILURE_REGEX, stdout or "")


# ---------------------------------------------------------------------------
# The Molecule regression: a flooded journal, a bounded result
# ---------------------------------------------------------------------------

def test_molecule_floods_the_journal_past_the_cap_and_asserts_the_bound() -> None:
    play = yaml.safe_load((MOLECULE_RESOURCES / "verify.yml").read_text(encoding="utf-8"))[0]
    include = play["tasks"][-1]
    assert include["ansible.builtin.include_tasks"] == "tasks/journal_bound.yml"
    # Last, because the flood it writes would otherwise reach the assertions
    # that read the converge report or the unprivileged scan.
    assert include["vars"]["vitals_flood_lines"] > include["vars"]["vitals_flood_cap"] * 10

    tasks = {
        task["name"]: task
        for task in yaml.safe_load((MOLECULE_RESOURCES / "tasks" / "journal_bound.yml").read_text(encoding="utf-8"))
    }
    flood = next(task for task in tasks.values() if "ansible.builtin.command" in task
                 and task["ansible.builtin.command"]["argv"][0] == "systemd-cat")
    # systemd-cat ships with systemd everywhere; logger and su do not (#130).
    assert "--priority=err" in flood["ansible.builtin.command"]["argv"]

    scan = next(task for task in tasks.values() if "ansible.builtin.include_role" in task)
    assert scan["ansible.builtin.include_role"]["name"].endswith(".vitals_scan")
    assert scan["vars"]["linux_vitals_log_max_lines"] == "{{ vitals_flood_cap }}"

    bound = next(task for task in tasks.values() if task["name"] == "Assert the flooded journal produced a bounded result")
    rules = " ".join(bound["ansible.builtin.assert"]["that"])
    assert "linux_vitals_log_errors | int == vitals_flood_cap | int" in rules
    assert "linux_vitals_kernel_install_failures | int == vitals_flood_cap | int" in rules
    assert "linux_vitals_log_matches is not defined" in rules


def test_scan_defaults_bound_the_journal() -> None:
    defaults = yaml.safe_load(
        (REPO_ROOT / "roles" / "vitals_scan" / "defaults" / "main.yml").read_text(encoding="utf-8")
    )

    assert defaults["linux_vitals_log_priority"] == "err"
    assert isinstance(defaults["linux_vitals_log_max_lines"], int)
    assert 1 <= defaults["linux_vitals_log_max_lines"] <= 10000
