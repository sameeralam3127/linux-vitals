"""Runs that share an output, archive or snapshot directory (#26).

Three properties, each driven through the real `vitals_report` tasks with
`ansible-playbook`:

* **Reports are replaced, never rewritten in place.** Every write goes through
  the template or copy module, which renames a finished temporary file over
  the destination. A reader -- or a concurrent run -- sees the old report or
  the new one, never a partial one.
* **Retention pruning only ever touches this report's own archives.** It used
  to glob `<stem>-*<ext>`, which also matched another report's archives when
  that report's name started with this one's (`linux_vitals_report-web.html`
  beside `linux_vitals_report.html`), and deleted this report's history
  instead of theirs.
* **A snapshot set shared by several runs records who wrote what.** Each run
  records its hosts in `.shards/<shard>.json`; reusing a named shard for other
  hosts fails, an unsharded run that mixes host sets warns, and re-runs,
  `--limit` re-runs and new shards are allowed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from test_templates import ARCHIVE_PLAYBOOK, REPO_ROOT, _ansible_playbook_bin, _base_env

ROLE_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks"
SHARD_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "snapshot_shards.yml"
SHARD_INVENTORY = REPO_ROOT / "tests" / "fixtures" / "snapshot_shards.ini"

# What the copy and template modules can leave behind in a destination
# directory if a run is killed mid-write: copy's mkstemp() for remote_src and
# atomic_move()'s cross-filesystem fallback. Neither may ever be pruned as an
# archive or mistaken for a report.
TEMP_NAME_PREFIXES = ("tmp", ".ansible_tmp")


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_ansible_playbook_bin(), *args],
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
        capture_output=True,
        text=True,
    )


def _ok(result: subprocess.CompletedProcess) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _leftover_temp_files(*directories: Path) -> list[str]:
    return sorted(
        path.name
        for directory in directories
        for path in directory.iterdir()
        if path.name.startswith(TEMP_NAME_PREFIXES)
    )


# ---------------------------------------------------------------------------
# Atomic report writes
# ---------------------------------------------------------------------------

WRITE_MODULES = {"ansible.builtin.template", "ansible.builtin.copy"}
NON_ATOMIC_MODULES = {
    "ansible.builtin.shell",
    "ansible.builtin.command",
    "ansible.builtin.raw",
    "ansible.builtin.lineinfile",
    "ansible.builtin.blockinfile",
    "ansible.builtin.replace",
}


@pytest.mark.parametrize("task_file", ["render.yml", "snapshot.yml"])
def test_report_writes_only_go_through_atomic_modules(task_file: str) -> None:
    # template and copy write a temporary file and rename() it over the
    # destination (AnsibleModule.atomic_move). unsafe_writes is the one switch
    # that lets them write in place, and the other modules here always do.
    tasks = yaml.safe_load((ROLE_TASKS / task_file).read_text(encoding="utf-8"))

    in_place = [task["name"] for task in tasks if NON_ATOMIC_MODULES & set(task)]
    unsafe = [
        task["name"]
        for task in tasks
        for module in WRITE_MODULES & set(task)
        if task[module].get("unsafe_writes")
    ]

    assert not in_place, f"{task_file}: tasks that can write a file in place: {in_place}"
    assert not unsafe, f"{task_file}: tasks with unsafe_writes: {unsafe}"


def test_each_run_archives_the_report_it_rendered() -> None:
    # Copying linux_vitals_output_path into the archive would archive whatever
    # is at that path by then -- another run's report, if two runs write the
    # same output path at once.
    tasks = {
        task["name"]: task
        for task in yaml.safe_load((ROLE_TASKS / "render.yml").read_text(encoding="utf-8"))
    }

    html = tasks["Archive consolidated HTML dashboard"]["ansible.builtin.template"]
    json_report = tasks["Archive JSON report"]["ansible.builtin.template"]

    assert html["src"] == "dashboard.html.j2"
    assert html["dest"] == "{{ linux_vitals_archive_html_path }}"
    assert json_report["src"] == "report.json.j2"
    assert json_report["dest"] == "{{ linux_vitals_archive_json_path }}"


def test_rerendering_replaces_reports_instead_of_rewriting_them(tmp_path: Path) -> None:
    _ok(_run([str(ARCHIVE_PLAYBOOK)], tmp_path))

    latest = tmp_path / "latest"
    html_path = latest / "linux_vitals_report.html"
    json_path = latest / "linux_vitals_report.json"
    first_html = html_path.read_bytes()

    # A reader that opened the reports during the first run.
    with html_path.open("rb") as html_reader, json_path.open("rb") as json_reader:
        first_html_inode = os.fstat(html_reader.fileno()).st_ino
        first_json_inode = os.fstat(json_reader.fileno()).st_ino

        _ok(
            _run(
                [
                    str(ARCHIVE_PLAYBOOK),
                    "-e",
                    "linux_vitals_report_title='Second run'",
                    "-e",
                    "linux_vitals_archive_timestamp=20260430T120000Z",
                ],
                tmp_path,
            )
        )

        # Replaced by rename: the path names a new file, and the reader still
        # holds the whole of the old one. A write in place (truncate, then
        # write) keeps the inode, and the reader would see the new or a
        # truncated report.
        assert html_path.stat().st_ino != first_html_inode
        assert json_path.stat().st_ino != first_json_inode
        assert html_reader.read() == first_html
        assert first_html.rstrip().endswith(b"</html>")
        assert json.loads(json_reader.read())["summary"]["overall_status"] == "PASS"

    second_html = html_path.read_text(encoding="utf-8")
    assert "Second run" in second_html
    assert second_html.rstrip().endswith("</html>")
    assert json.loads(json_path.read_text(encoding="utf-8"))["generated_at"] == "20260430T120000Z"
    assert _leftover_temp_files(latest, tmp_path / "archive") == []


# ---------------------------------------------------------------------------
# Archive retention
# ---------------------------------------------------------------------------


def test_concurrent_runs_sharing_an_archive_directory(tmp_path: Path) -> None:
    # Four runs at once into one archive directory: three of the same report,
    # pruning the same set concurrently, and one of a report whose name starts
    # with the first one's -- the layout of a sharded fleet that gives each
    # shard its own output path. The old glob, shard-a-*.html, matched
    # shard-a-eu's archives too and, a letter sorting above a digit, ranked
    # them newest, kept them, and deleted shard-a's own.
    #
    # Whatever the interleaving, every run succeeds and each report keeps
    # exactly its own newest archives: an archive is pruned only when two
    # newer ones of its own report exist, and the run whose listing comes last
    # saw every archive created before it. Files a killed run's copy or
    # template could leave behind are never pruned.
    latest = tmp_path / "latest"
    archive = tmp_path / "archive"
    archive.mkdir()
    temp_files = ["tmpk2j3h4g5", ".ansible_tmpab12cdshard-a-20200101T000000Z.html"]
    for name in temp_files:
        (archive / name).write_text("partial", encoding="utf-8")
    runs = [
        ("shard-a", "20261001T000001Z"),
        ("shard-a", "20261001T000002Z"),
        ("shard-a", "20261001T000003Z"),
        ("shard-a-eu", "20261001T000004Z"),
    ]
    processes = [
        subprocess.Popen(
            [
                _ansible_playbook_bin(),
                str(ARCHIVE_PLAYBOOK),
                "-e",
                f"linux_vitals_output_path={latest}/{stem}.html",
                "-e",
                f"linux_vitals_json_output_path={latest}/{stem}.json",
                "-e",
                f"linux_vitals_archive_timestamp={timestamp}",
            ],
            cwd=REPO_ROOT,
            env=_base_env(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for stem, timestamp in runs
    ]
    outputs = [process.communicate(timeout=300)[0] for process in processes]

    for process, output in zip(processes, outputs):
        assert process.returncode == 0, output

    def archives(stem: str) -> list[str]:
        return sorted(
            path.name
            for path in archive.iterdir()
            if path.name.startswith(f"{stem}-2026")
        )

    assert archives("shard-a") == [
        "shard-a-20261001T000002Z.html",
        "shard-a-20261001T000002Z.json",
        "shard-a-20261001T000003Z.html",
        "shard-a-20261001T000003Z.json",
    ]
    assert archives("shard-a-eu") == [
        "shard-a-eu-20261001T000004Z.html",
        "shard-a-eu-20261001T000004Z.json",
    ]
    # The fixture's seeded linux_vitals_report archives belong to a report
    # none of these runs writes.
    assert len(archives("linux_vitals_report")) == 6
    for stem in ("shard-a", "shard-a-eu"):
        assert (latest / f"{stem}.html").read_text(encoding="utf-8").rstrip().endswith("</html>")
        json.loads((latest / f"{stem}.json").read_text(encoding="utf-8"))
    assert _leftover_temp_files(latest, archive) == sorted(temp_files)


# ---------------------------------------------------------------------------
# Snapshot shard manifests
# ---------------------------------------------------------------------------

PHASE_DIR = Path("snapshots") / "shard-window" / "baseline"
SHARDS_DIR = PHASE_DIR / ".shards"
MIXED_HOSTS_WARNING = "WARNING: the snapshot set for maintenance id 'shard-window'"
PRE_MANIFEST_WARNING = "written before this release recorded shard manifests"


def _snapshot(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return _run(["-i", str(SHARD_INVENTORY), str(SHARD_PLAYBOOK), *args], tmp_path)


def _manifest(tmp_path: Path, shard: str) -> dict:
    return json.loads((tmp_path / SHARDS_DIR / f"{shard}.json").read_text(encoding="utf-8"))


def _manifest_bytes(tmp_path: Path, shard: str) -> bytes:
    return (tmp_path / SHARDS_DIR / f"{shard}.json").read_bytes()


def _snapshotted_hosts(tmp_path: Path) -> list[str]:
    return sorted(path.stem for path in (tmp_path / PHASE_DIR).glob("*.json"))


def _no_warnings(output: str) -> None:
    assert MIXED_HOSTS_WARNING not in output
    assert PRE_MANIFEST_WARNING not in output


def test_shard_manifests_through_a_sharded_maintenance_window(tmp_path: Path) -> None:
    # Fresh: an unsharded run records itself as shard "default". It runs in
    # batches of one host, as under `serial`, where the role runs once per
    # batch: every batch must record and compare the whole play's hosts, or
    # the second batch would conflict with the first.
    output = _ok(_snapshot(tmp_path, "--limit", "host-a,host-b", "-e", "fixture_serial=1"))
    manifest = _manifest(tmp_path, "default")
    assert manifest["hosts"] == ["host-a", "host-b"]
    assert manifest["maintenance_id"] == "shard-window"
    assert manifest["phase"] == "baseline"
    assert manifest["shard"] == "default"
    assert _snapshotted_hosts(tmp_path) == ["host-a", "host-b"]
    _no_warnings(output)
    recorded = _manifest_bytes(tmp_path, "default")

    # A re-run of the same hosts, and a --limit re-run of some of them.
    for limit in ("host-a,host-b", "host-b"):
        _no_warnings(_ok(_snapshot(tmp_path, "--limit", limit)))
    # A manifest is never rewritten: it keeps the first run's host list.
    assert _manifest_bytes(tmp_path, "default") == recorded

    # A second shard extends the set.
    east = ["-e", "linux_vitals_snapshot_shard=east"]
    _no_warnings(_ok(_snapshot(tmp_path, "--limit", "host-c,host-d", *east)))
    assert _manifest(tmp_path, "east")["hosts"] == ["host-c", "host-d"]
    assert _manifest(tmp_path, "east")["shard"] == "east"
    assert _snapshotted_hosts(tmp_path) == ["host-a", "host-b", "host-c", "host-d"]
    recorded_east = _manifest_bytes(tmp_path, "east")

    # Reusing that shard id for a different host set fails before any
    # snapshot is written, naming the host that differs and the fix.
    result = _snapshot(tmp_path, "--limit", "host-c,host-e", *east)
    assert result.returncode != 0
    assert "Snapshot shard 'east'" in result.stdout
    assert "not in it: host-e." in result.stdout
    assert "give this run a linux_vitals_snapshot_shard" in result.stdout
    assert "No snapshot was written" in result.stdout
    assert _snapshotted_hosts(tmp_path) == ["host-a", "host-b", "host-c", "host-d"]
    assert _manifest_bytes(tmp_path, "east") == recorded_east

    # An unsharded run that brings other hosts into the unsharded shard is
    # reported, not refused: sequential per-group runs sharing a maintenance
    # id worked before shard ids existed, and must keep working.
    output = _ok(_snapshot(tmp_path, "--limit", "host-e"))
    assert MIXED_HOSTS_WARNING in output
    assert "not in it: host-e." in output
    assert "give each its own linux_vitals_snapshot_shard" in output
    assert "host-e" in _snapshotted_hosts(tmp_path)
    assert _manifest_bytes(tmp_path, "default") == recorded


def test_snapshot_set_from_before_shard_manifests(tmp_path: Path) -> None:
    # Host snapshots and no .shards/: written by an earlier release, so which
    # run wrote them cannot be checked. The run goes ahead, and names only the
    # snapshots it will not overwrite -- not host-a, which it rewrites.
    phase_dir = tmp_path / PHASE_DIR
    phase_dir.mkdir(parents=True)
    for host in ("host-a", "legacy-x", "legacy-y"):
        (phase_dir / f"{host}.json").write_text('{"final_status": "Pass"}\n', encoding="utf-8")

    output = _ok(_snapshot(tmp_path, "--limit", "host-a,host-b"))

    assert PRE_MANIFEST_WARNING in output
    assert "does not cover: legacy-x, legacy-y." in output
    assert MIXED_HOSTS_WARNING not in output
    assert _manifest(tmp_path, "default")["hosts"] == ["host-a", "host-b"]
    assert _snapshotted_hosts(tmp_path) == ["host-a", "host-b", "legacy-x", "legacy-y"]

    # Once the set has a manifest it is no longer a pre-manifest set.
    _no_warnings(_ok(_snapshot(tmp_path, "--limit", "host-a,host-b")))


def _shard_id_pattern() -> str:
    tasks = yaml.safe_load((ROLE_TASKS / "snapshot.yml").read_text(encoding="utf-8"))
    (task,) = [t for t in tasks if t["name"] == "Require a usable snapshot shard id"]
    (pattern,) = re.findall(r"is match\('([^']+)'\)", task["ansible.builtin.assert"]["that"][0])
    return pattern


@pytest.mark.parametrize(
    ("shard", "accepted"),
    [
        ("", True),
        ("east", True),
        ("shard-07", True),
        ("eu.west_2", True),
        ("../escape", False),
        (".hidden", False),
        ("-dash-first", False),
        ("two words", False),
        ("east/west", False),
    ],
)
def test_shard_id_pattern(shard: str, accepted: bool) -> None:
    # The shard id names a file under the snapshot directory, so it must not
    # be able to point anywhere else or hide itself. Ansible's `match` test is
    # re.match.
    assert bool(re.match(_shard_id_pattern(), shard)) is accepted


@pytest.mark.parametrize(
    "maintenance_id",
    [".", "..", "../x", ".hidden", "a/b", "a\\b", "bad\x01id"],
)
def test_an_unusable_maintenance_id_stops_before_writing(
    tmp_path: Path, maintenance_id: str
) -> None:
    result = _snapshot(
        tmp_path,
        "--limit", "host-a",
        "-e", json.dumps({"linux_vitals_maintenance_id": maintenance_id}),
    )

    assert result.returncode != 0
    assert "linux_vitals_maintenance_id" in result.stdout
    assert "path separators" in result.stdout
    assert not (tmp_path / "snapshots").exists()


@pytest.mark.parametrize(
    ("maintenance_id", "normalized_id"),
    [
        ("2026-10-17-patch", "2026-10-17-patch"),
        ("monthly patch", "monthly patch"),
        ("  monthly patch  ", "monthly patch"),
    ],
)
def test_maintenance_id_is_trimmed_and_keeps_valid_values(
    tmp_path: Path, maintenance_id: str, normalized_id: str
) -> None:
    result = _snapshot(
        tmp_path,
        "--limit", "host-a",
        "-e", json.dumps({"linux_vitals_maintenance_id": maintenance_id}),
    )

    _ok(result)
    phase_dir = tmp_path / "snapshots" / normalized_id / "baseline"
    assert (phase_dir / "host-a.json").is_file()
    manifest = json.loads((phase_dir / ".shards" / "default.json").read_text(encoding="utf-8"))
    assert manifest["maintenance_id"] == normalized_id
    if maintenance_id != normalized_id:
        assert not (tmp_path / "snapshots" / maintenance_id / "baseline").exists()


def test_an_unusable_shard_id_stops_the_run_before_anything_is_written(tmp_path: Path) -> None:
    result = _snapshot(tmp_path, "--limit", "host-a", "-e", "linux_vitals_snapshot_shard=../escape")

    assert result.returncode != 0
    assert "linux_vitals_snapshot_shard must be empty, or a name of letters" in result.stdout
    assert not (tmp_path / "snapshots").exists()
