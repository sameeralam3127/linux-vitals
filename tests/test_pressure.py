"""CPU load, pressure stall (PSI) and swap activity checks (#34).

The probe script runs as written, under `sh -c`, against fake /proc trees
(its optional second parameter replaces /proc). The three pressure_facts.yml
tasks run through ansible-playbook over seeded probe output. The golden
fixtures cover whole hosts; these pin the edges: PSI that is unsupported
rather than zero, values that could not be read, inclusive thresholds, and a
swap rate that was not sampled.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml

from scan_tasks import scan_task
from test_discovery_facts import _run_playbook
from test_golden_findings import KEY_VALUE_PROBES
from test_templates import REPO_ROOT

PROBE_TASK = "Collect CPU load, pressure stalls and swap activity"
FACT_TASKS = (
    "Parse the load, pressure and swap probe",
    "Evaluate CPU load, pressure stalls and swap usage",
    "Classify CPU load, pressure stalls and swap activity",
)
SCAN_DEFAULTS = yaml.safe_load(
    (REPO_ROOT / "roles" / "vitals_scan" / "defaults" / "main.yml").read_text(encoding="utf-8")
)
PSI = "some avg10=1.00 avg60={some} avg300=3.00 total=1\nfull avg10=0.00 avg60={full} avg300=0.00 total=0\n"


# ---------------------------------------------------------------------------
# the probe script
# ---------------------------------------------------------------------------

def _script() -> str:
    argv = scan_task(PROBE_TASK)["ansible.builtin.command"]["argv"]
    assert argv[:2] == ["sh", "-c"]
    return argv[2]


def _proc(tmp_path: Path, *, psi: str | None = "file", swap_in: int = 1000, swap_out: int = 500) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "loadavg").write_text("3.10 2.40 1.90 2/310 4242\n")
    (proc / "cpuinfo").write_text("processor\t: 0\nprocessor\t: 1\n")
    (proc / "meminfo").write_text("MemTotal: 1000 kB\nSwapTotal:     2097148 kB\nSwapFree:      1048574 kB\n")
    (proc / "vmstat").write_text(f"pgfault 1\npswpin {swap_in}\npswpout {swap_out}\n")
    if psi == "file":
        (proc / "pressure").mkdir()
        for resource, some in (("cpu", "12.50"), ("memory", "30.25"), ("io", "4.00")):
            (proc / "pressure" / resource).write_text(PSI.format(some=some, full="1.75"))
    elif psi == "unreadable":
        # A directory where the file should be: reading it fails, the way
        # /proc/pressure/cpu does on a kernel booted with psi=0.
        (proc / "pressure" / "cpu").mkdir(parents=True)
    return proc


def _probe(proc: Path, interval: int = 0) -> tuple[list[tuple[str, str]], subprocess.CompletedProcess]:
    run = subprocess.run(
        ["sh", "-c", _script(), "linux-vitals-pressure", str(interval), str(proc)],
        capture_output=True, text=True, check=False, timeout=30, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
    )
    pairs = [tuple(line.split("=", 1)) for line in run.stdout.splitlines()]
    return pairs, run


def test_the_probe_prints_the_keys_the_golden_adapter_prints(tmp_path: Path) -> None:
    pairs, run = _probe(_proc(tmp_path))
    assert run.returncode == 0, run.stderr
    assert [key for key, _ in pairs] == KEY_VALUE_PROBES["pressure"]


def test_the_probe_reads_load_cpus_psi_and_swap(tmp_path: Path) -> None:
    values = dict(_probe(_proc(tmp_path))[0])
    assert values["load"] == "3.10 2.40 1.90"
    assert int(values["cpus"]) >= 1
    assert values["psi"] == "supported"
    assert values["psi_reason"] == ""
    assert (values["psi_cpu_some"], values["psi_memory_some"], values["psi_io_some"]) == ("12.50", "30.25", "4.00")
    assert (values["psi_memory_full"], values["psi_io_full"]) == ("1.75", "1.75")
    assert (values["swap_total_kb"], values["swap_free_kb"]) == ("2097148", "1048574")


def test_absent_psi_is_unsupported_and_empty_not_zero(tmp_path: Path) -> None:
    values = dict(_probe(_proc(tmp_path, psi=None))[0])
    assert values["psi"] == "unsupported"
    assert "/proc/pressure is not present" in values["psi_reason"]
    assert all(values[f"psi_{key}"] == "" for key in ("cpu_some", "memory_some", "memory_full", "io_some", "io_full"))


def test_unreadable_psi_is_unsupported_with_the_error(tmp_path: Path) -> None:
    values = dict(_probe(_proc(tmp_path, psi="unreadable"))[0])
    assert values["psi"] == "unsupported"
    assert values["psi_reason"].startswith("reading /proc/pressure/cpu failed: ")


def test_sampling_off_measures_no_rate(tmp_path: Path) -> None:
    values = dict(_probe(_proc(tmp_path), interval=0)[0])
    assert values["swap_sample_seconds"] == "0"
    assert (values["swap_in_per_sec"], values["swap_out_per_sec"]) == ("", "")


def test_the_swap_rate_is_the_change_between_two_reads(tmp_path: Path) -> None:
    proc = _proc(tmp_path, swap_in=1000, swap_out=500)

    def page_out() -> None:
        time.sleep(0.4)
        (proc / "vmstat").write_text("pgfault 9\npswpin 1600\npswpout 900\n")

    writer = threading.Thread(target=page_out)
    writer.start()
    values = dict(_probe(proc, interval=1)[0])
    writer.join()
    assert values["swap_sample_seconds"] == "1"
    assert (values["swap_in_per_sec"], values["swap_out_per_sec"]) == ("600", "400")


def test_the_interval_is_a_parameter_not_templated_into_the_script() -> None:
    argv = scan_task(PROBE_TASK)["ansible.builtin.command"]["argv"]
    assert "{{" not in argv[2]
    assert argv[3] == "linux-vitals-pressure"
    assert "linux_vitals_swap_sample_seconds" in argv[4]


# ---------------------------------------------------------------------------
# pressure_facts.yml
# ---------------------------------------------------------------------------

HEALTHY = {
    "load": "0.40 0.40 0.40", "cpus": "4", "psi": "supported", "psi_reason": "",
    "psi_cpu_some": "0.50", "psi_memory_some": "0.00", "psi_memory_full": "0.00",
    "psi_io_some": "1.00", "psi_io_full": "0.20",
    "swap_total_kb": "2097152", "swap_free_kb": "2097152", "swap_sample_seconds": "2",
    "swap_in_per_sec": "0", "swap_out_per_sec": "0",
}


def _evaluate(tmp_path: Path, probe: dict | None = None, rc: int = 0, stderr: str = "", **values: str) -> dict:
    if probe is None:
        output = {**HEALTHY, **values}
        lines = [f"{key}={output[key]}" for key in KEY_VALUE_PROBES["pressure"]]
        probe = {"rc": rc, "stdout": "\n".join(lines), "stdout_lines": lines, "stderr": stderr}
    thresholds = {key: value for key, value in SCAN_DEFAULTS.items()
                  if key.startswith(("linux_vitals_load_", "linux_vitals_psi_", "linux_vitals_swap_"))}
    tasks = [{"name": "Seed the probe", "ansible.builtin.set_fact": {"linux_vitals_pressure_cmd": probe, **thresholds}}]
    tasks += [{key: value for key, value in scan_task(name).items() if key != "tags"} for name in FACT_TASKS]
    tasks.append({
        "name": "Write the result for assertion",
        "ansible.builtin.copy": {
            "content": "{{ linux_vitals_pressure | combine(linux_vitals_pressure_status) | to_nice_json }}\n",
            "dest": "{{ output_dir }}/discovery_fact.json",
            "mode": "0644",
        },
    })
    return _run_playbook(tmp_path, tasks)


def test_a_quiet_host_is_ok_on_every_signal(tmp_path: Path) -> None:
    result = _evaluate(tmp_path)
    assert (result["load_status"], result["psi_status"], result["swap_status"]) == ("OK", "OK", "OK")
    assert result["load_per_cpu"] == {"1m": 0.1, "5m": 0.1, "15m": 0.1}
    assert result["cpu_count"] == 4
    assert result["swap_used_pct"] == 0.0
    assert result["swap_rate_per_sec"] == 0
    assert result["stalled"] == []


@pytest.mark.parametrize(
    ("load", "status"),
    [("5.96", "OK"), ("6.00", "Warning"), ("11.96", "Warning"), ("12.00", "Critical")],
)
def test_load_thresholds_are_per_cpu_and_inclusive(tmp_path: Path, load: str, status: str) -> None:
    # 4 CPUs: 6.00 is exactly the 1.5 warning line, 12.00 exactly the 3.0 critical one.
    result = _evaluate(tmp_path, load=f"0.10 {load} 0.10")
    assert result["load_status"] == status


@pytest.mark.parametrize(("some", "status"), [("24.99", "OK"), ("25.00", "Warning"), ("50.00", "Critical")])
def test_psi_thresholds_are_inclusive(tmp_path: Path, some: str, status: str) -> None:
    result = _evaluate(tmp_path, psi_memory_some=some)
    assert result["psi_status"] == status
    stalled = [entry["resource"] for entry in result["stalled"]]
    assert stalled == ([] if status == "OK" else ["memory"])


def test_stalled_resources_are_listed_worst_first(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, psi_cpu_some="30.00", psi_memory_some="61.00", psi_io_some="40.00")
    assert [(e["resource"], e["severity"]) for e in result["stalled"]] == [
        ("memory", "critical"), ("io", "warning"), ("cpu", "warning")]
    assert result["psi_status"] == "Critical"


@pytest.mark.parametrize(
    ("swap_in", "swap_out", "status"),
    [("60", "39", "OK"), ("60", "40", "Warning"), ("900", "100", "Critical")],
)
def test_swap_thresholds_count_pages_in_and_out(tmp_path: Path, swap_in: str, swap_out: str, status: str) -> None:
    result = _evaluate(tmp_path, swap_in_per_sec=swap_in, swap_out_per_sec=swap_out)
    assert result["swap_status"] == status
    assert result["swap_rate_per_sec"] == int(swap_in) + int(swap_out)


def test_unsupported_psi_is_null_not_zero_and_raises_nothing(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, psi="unsupported", psi_reason="reading /proc/pressure/cpu failed: Operation not supported",
                       psi_cpu_some="", psi_memory_some="", psi_memory_full="", psi_io_some="", psi_io_full="")
    assert result["psi_status"] == "Unsupported"
    assert result["psi_supported"] is False
    assert result["psi"] is None
    assert result["psi_reason"] == "reading /proc/pressure/cpu failed: Operation not supported"


def test_sampling_off_is_not_sampled_rather_than_zero(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, swap_sample_seconds="0", swap_in_per_sec="", swap_out_per_sec="")
    assert result["swap_status"] == "Not sampled"
    assert result["swap_rate_per_sec"] is None
    assert result["swap_reason"] == ""


def test_no_swap_configured_has_no_used_percentage(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, swap_total_kb="0", swap_free_kb="0")
    assert result["swap_total_mb"] == 0.0
    assert result["swap_used_pct"] is None
    assert result["swap_status"] == "OK"


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ({"load": ""}, "could not read /proc/loadavg"),
        ({"load": "0.40 garbage 0.40"}, "could not read /proc/loadavg"),
        ({"cpus": "0"}, "could not count the online CPUs"),
    ],
)
def test_an_unreadable_load_is_unknown_with_a_reason(tmp_path: Path, values: dict, reason: str) -> None:
    result = _evaluate(tmp_path, **values)
    assert result["load_status"] == "Unknown"
    assert result["load_reason"] == reason
    assert result["load"] is None


def test_unreadable_swap_counters_are_unknown_with_a_reason(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, swap_in_per_sec="", swap_out_per_sec="")
    assert result["swap_status"] == "Unknown"
    assert result["swap_reason"] == "could not read the swap counters in /proc/vmstat"


def test_a_probe_that_could_not_run_makes_every_signal_unknown(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, probe={"rc": 2, "stdout": "", "stdout_lines": [],
                                        "stderr": "[Errno 2] No such file or directory: b'sh'"})
    assert (result["load_status"], result["psi_status"], result["swap_status"]) == ("Unknown", "Unknown", "Unknown")
    for key in ("load_reason", "psi_reason", "swap_reason"):
        assert result[key].startswith("the load and pressure probe exited 2:")
        assert "No such file or directory" in result[key]


def test_a_skipped_probe_is_unknown_not_clean(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, probe={"changed": False, "skipped": True})
    assert result["load_status"] == "Unknown"
    assert result["load_reason"] == "the load and pressure probe did not run"
