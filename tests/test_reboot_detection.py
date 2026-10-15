from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from shutil import which

import pytest

from scan_tasks import discovery_tasks
from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env


REBOOT_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "reboot_detection.yml"

# The discovery probes read fixed absolute paths on the managed host; rewriting
# those roots lets the real script run against a synthetic /boot layout here.
ROOTED_PATHS = re.compile(r"(?<![\w$/])/(var/run|lib/modules|etc/default|boot|efi|run)\b")


def _derived_reboot_facts(tmp_path: Path) -> dict[str, dict]:
    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(REBOOT_PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    return json.loads((tmp_path / "reboot_detection.json").read_text(encoding="utf-8"))


def test_distro_probe_output_drives_reboot_facts(tmp_path: Path) -> None:
    facts = _derived_reboot_facts(tmp_path)

    debian = facts["debian_pending"]
    assert debian["required"] is True
    assert debian["supported"] is True
    assert debian["source"] == "/run/reboot-required"
    assert debian["packages"] == ["libc6", "linux-image-6.8.0-60-generic"]
    assert "linux-image-6.8.0-60-generic" in debian["reason"]

    assert facts["debian_clear"]["required"] is False
    assert facts["debian_clear"]["packages"] == []

    redhat = facts["redhat_pending"]
    assert redhat["required"] is True
    assert redhat["source"] == "needs-restarting"
    assert "Reboot is required" in redhat["reason"]

    suse = facts["suse_pending"]
    assert suse["required"] is True
    assert suse["source"] == "zypper-needs-rebooting"


def test_unusable_distro_check_falls_back_to_kernel_comparison(tmp_path: Path) -> None:
    facts = _derived_reboot_facts(tmp_path)

    # needs-restarting absent and the running kernel is not the latest installed
    # one -- the fallback has to flag the reboot rather than stay silent.
    missing_tool = facts["redhat_tool_missing"]
    assert missing_tool["supported"] is False
    assert missing_tool["required"] is True
    assert missing_tool["source"] == "kernel-comparison"
    assert "no distro reboot check" in missing_tool["reason"]

    # The tool erroring out is not evidence that no reboot is needed: the answer
    # falls back to the kernel comparison, which here says the host is current.
    failed_tool = facts["redhat_tool_failed"]
    assert failed_tool["supported"] is False
    assert failed_tool["required"] is False
    assert failed_tool["source"] == "kernel-comparison"

    unsupported = facts["unsupported_family"]
    assert unsupported["supported"] is False
    assert unsupported["required"] is False
    assert unsupported["source"] == "kernel-comparison"


def _discovery_scripts() -> dict[str, str]:
    return {
        task["name"]: task["ansible.builtin.command"]["argv"][2]
        for task in discovery_tasks()
        if "ansible.builtin.command" in task
        and task["ansible.builtin.command"].get("argv", [])[:2] == ["sh", "-c"]
    }


def _run_rooted(script: str, root: Path) -> dict[str, str]:
    shell = which("dash") or which("sh")
    completed = subprocess.run(
        [shell, "-c", ROOTED_PATHS.sub(lambda m: f"{root}/{m.group(1)}", script)],
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(
        line.split("=", 1)
        for line in completed.stdout.splitlines()
        if "=" in line
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture(name="bootloader_script", scope="module")
def _bootloader_script() -> str:
    return _discovery_scripts()["Collect bootloader default kernel information"]


def test_bootloader_default_resolves_bls_entry_by_id(
    bootloader_script: str, tmp_path: Path
) -> None:
    # RHEL 8+/Fedora: the default names a BLS drop-in, not a grub.cfg menuentry.
    _write(tmp_path / "etc/default/grub", "GRUB_DEFAULT=ffff-6.9.0-1.el9.x86_64\n")
    _write(
        tmp_path / "boot/loader/entries/ffff-6.9.0-1.el9.x86_64.conf",
        "title Red Hat Enterprise Linux (6.9.0-1.el9.x86_64) 9.4\n"
        "linux /vmlinuz-6.9.0-1.el9.x86_64\n"
        "initrd /initramfs-6.9.0-1.el9.x86_64.img\n",
    )

    result = _run_rooted(bootloader_script, tmp_path)

    assert result["supported"] == "true"
    assert result["status"] == "resolved"
    assert result["default_kernel"] == "6.9.0-1.el9.x86_64"


def test_bootloader_default_resolves_grub_cfg_entry_by_index(
    bootloader_script: str, tmp_path: Path
) -> None:
    _write(tmp_path / "etc/default/grub", "GRUB_DEFAULT=1\n")
    _write(
        tmp_path / "boot/grub/grub.cfg",
        "menuentry 'Ubuntu' {\n"
        "  linux /boot/vmlinuz-6.8.0-60-generic root=/dev/sda1\n"
        "}\n"
        "menuentry 'Ubuntu, with Linux 6.8.0-31-generic' {\n"
        "  linux /boot/vmlinuz-6.8.0-31-generic root=/dev/sda1\n"
        "}\n",
    )

    result = _run_rooted(bootloader_script, tmp_path)

    assert result["status"] == "resolved"
    assert result["default_kernel"] == "6.8.0-31-generic"


def test_bootloader_default_resolves_systemd_boot_glob_default(
    bootloader_script: str, tmp_path: Path
) -> None:
    # systemd-boot resolves a glob default to the version-highest match.
    _write(tmp_path / "boot/loader/loader.conf", "timeout 3\ndefault fedora-*\n")
    for version in ("6.8.0-1.fc40", "6.9.0-1.fc40"):
        _write(
            tmp_path / f"boot/loader/entries/fedora-{version}.conf",
            f"title Fedora ({version})\nlinux /vmlinuz-{version}\n",
        )

    result = _run_rooted(bootloader_script, tmp_path)

    assert result["source"] == "systemd-boot"
    assert result["status"] == "resolved"
    assert result["default_kernel"] == "6.9.0-1.fc40"


def test_bootloader_default_reports_unavailable_without_a_bootloader(
    bootloader_script: str, tmp_path: Path
) -> None:
    result = _run_rooted(bootloader_script, tmp_path)

    assert result["supported"] == "false"
    assert result["status"] == "unavailable"


def test_latest_kernel_probe_ignores_leftover_module_directories(tmp_path: Path) -> None:
    script = _discovery_scripts()["Collect latest installed kernel version"]
    # A real kernel (has modules.dep), a real kernel known only by its image in
    # /boot, and a leftover directory from an interrupted removal.
    _write(tmp_path / "lib/modules/6.8.0-1/modules.dep", "")
    _write(tmp_path / "lib/modules/6.7.0-1/modules.builtin", "")
    _write(tmp_path / "boot/vmlinuz-6.7.0-1", "")
    (tmp_path / "lib/modules/6.9.0-1").mkdir(parents=True)

    result = _run_rooted(script, tmp_path)

    assert result["latest"] == "6.8.0-1"
    assert result["filtered"] == "true"


def test_latest_kernel_probe_falls_back_to_the_plain_listing(tmp_path: Path) -> None:
    script = _discovery_scripts()["Collect latest installed kernel version"]
    (tmp_path / "lib/modules/6.9.0-1").mkdir(parents=True)

    result = _run_rooted(script, tmp_path)

    assert result["latest"] == "6.9.0-1"
    assert result["filtered"] == "false"


def test_debian_probe_reports_marker_file_and_pending_packages(tmp_path: Path) -> None:
    script = _discovery_scripts()["Check if reboot is required on Debian family"]
    _write(tmp_path / "run/reboot-required", "*** System restart required ***\n")
    _write(
        tmp_path / "run/reboot-required.pkgs",
        "linux-image-6.8.0-60-generic\nlibc6\nlibc6\n",
    )

    result = _run_rooted(script, tmp_path)

    assert result["supported"] == "true"
    assert result["detected"] == "true"
    assert result["source"].endswith("/run/reboot-required")
    assert result["detail"] == "*** System restart required ***"
    assert result["packages"] == "libc6,linux-image-6.8.0-60-generic"


def test_debian_probe_reports_no_reboot_without_a_marker_file(tmp_path: Path) -> None:
    script = _discovery_scripts()["Check if reboot is required on Debian family"]

    result = _run_rooted(script, tmp_path)

    assert result["supported"] == "true"
    assert result["detected"] == "false"
    assert result["packages"] == ""


@pytest.mark.skipif(
    which("zypper") is not None,
    reason="the marker-file fallback is only reachable without zypper",
)
def test_suse_probe_falls_back_to_marker_files_without_zypper(tmp_path: Path) -> None:
    script = _discovery_scripts()["Check if reboot is recommended on SUSE family"]
    _write(tmp_path / "run/reboot-needed", "")

    result = _run_rooted(script, tmp_path)

    assert result["supported"] == "true"
    assert result["detected"] == "true"
    assert result["source"].endswith("/run/reboot-needed")


@pytest.mark.skipif(
    which("needs-restarting") is not None or which("dnf") is not None,
    reason="the unsupported path is only reachable without needs-restarting/dnf",
)
def test_redhat_probe_reports_unsupported_without_needs_restarting(tmp_path: Path) -> None:
    script = _discovery_scripts()["Check if reboot is recommended on RedHat family"]

    result = _run_rooted(script, tmp_path)

    # No needs-restarting and no dnf on the test host: the probe must say so
    # rather than claim the host does not need a reboot.
    assert result["supported"] == "false"
    assert result["source"] == "needs-restarting-missing"


def test_embedded_discovery_shell_scripts_are_posix_clean() -> None:
    # The discovery probes run on the managed host's /bin/sh, which is dash on
    # Debian/Ubuntu -- syntax-check them with the strictest shell available.
    shell = which("dash") or which("sh")
    assert shell, "a POSIX shell is required to validate the embedded scripts"

    scripts = _discovery_scripts()
    assert len(scripts) >= 5, "expected the discovery probes to be sh -c scripts"

    for script in scripts.values():
        subprocess.run([shell, "-n"], input=script, text=True, check=True)
