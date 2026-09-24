# Testing

LinuxVitals has two layers of automated tests, both run by CI on every push
and pull request:

| Layer | Command | What it proves |
| --- | --- | --- |
| Unit / template | `pytest -q` | Report templates render, reboot/kernel detection logic derives the right facts, and the embedded discovery shell scripts are POSIX-clean. No hosts involved. |
| Molecule scenarios | `molecule test -s <scenario>` | The roles actually run end to end against a live systemd host of each supported distribution. |

Plus `ansible-lint roles/ playbooks/ molecule/ demo/` and
`ansible-playbook playbooks/healthcheck.yml --syntax-check`.

## ansible-core versions

`meta/runtime.yml` declares `requires_ansible: ">=2.16.0"`, and CI tests both
ends of that range rather than only the newest core. Two total failures on
2.16 ([#45](https://github.com/sameeralam3127/linux-vitals/issues/45),
[#49](https://github.com/sameeralam3127/linux-vitals/issues/49)) reached users
through a CI that never ran it, and two more
([#81](https://github.com/sameeralam3127/linux-vitals/issues/81),
[#85](https://github.com/sameeralam3127/linux-vitals/issues/85)) were found the
first time the suite did.

| Job | ansible-core | Python | Collections |
| --- | --- | --- | --- |
| `validate` | latest (`requirements-dev.txt`) | 3.12 | `requirements.yml` |
| `validate (ansible-core 2.16)` | 2.16.x | 3.10 | `.github/constraints/collections-floor.yml` |
| `molecule (ubuntu \| rocky \| fedora \| opensuse)` | latest | 3.12 | `requirements.yml` + `molecule/collections.yml` |
| `molecule (rocky, ansible-core 2.16)` | 2.16.x | 3.10 | `.github/constraints/collections-floor.yml` |

The floor runs the full validate job (syntax check, ansible-lint, pytest) but
Molecule on one distribution only. Every 2.16 failure so far has been a core
failure rather than a distribution one, so one scenario catches that class,
and Rocky stands in for the RHEL estates most likely to sit on an older core.
Python 3.10 is the oldest Python the README supports, so the floor job tests
that claim too.

**How the floor is pinned.** `.github/constraints/ansible-core-floor.txt`
pins the `2.16.x` series. `.github/scripts/install-tooling.sh floor` installs
`requirements-dev.txt` without its own `ansible-core` line, under that
constraint, then refuses to continue unless the installed core really is
`2.16.x`. The pin in `requirements-dev.txt` is left alone because a
constraints file can narrow a requirement but not contradict it, and a widened
pin would be raised straight back by Dependabot.

**Floor collections.** `community.general` 12 and `community.docker` 5 require
ansible-core 2.17 or later, so the floor jobs install the newest majors that
still support 2.16 (`collections-floor.yml`). See
[#86](https://github.com/sameeralam3127/linux-vitals/issues/86) for what this
means for users on 2.16.

**Raising the floor** is a change to `meta/runtime.yml` and
`ansible-core-floor.txt` together, plus the job names in `ci.yml`.
`tests/test_ci_floor.py` fails if the constraint and `meta/runtime.yml`
disagree, or if a latest-core job loses the name branch protection requires.

### Running the floor locally

```bash
python3.10 -m venv .venv-floor && . .venv-floor/bin/activate
./.github/scripts/install-tooling.sh floor
pytest -q
```

That runs the suite on 2.16 against whatever collections you already have
installed, which is what catches core failures such as #81 and #85. To match
CI exactly, also install the floor collections:

```bash
ansible-galaxy collection install -r .github/constraints/collections-floor.yml --force
```

`--force` is needed because `ansible-galaxy` will not downgrade an installed
collection. The collections path is shared with your usual environment, so
switch back afterwards with
`ansible-galaxy collection install -r requirements.yml --force`.

## Molecule scenarios

One scenario per supported distribution family:

| Scenario | Image | Stands in for |
| --- | --- | --- |
| `ubuntu` | `geerlingguy/docker-ubuntu2404-ansible` | Debian family (Ubuntu, Debian) |
| `rocky` | `geerlingguy/docker-rockylinux9-ansible` | RHEL-compatible (RHEL, AlmaLinux, CentOS Stream) |
| `fedora` | `geerlingguy/docker-fedora42-ansible` | Fedora, and the newest dnf5/systemd behaviour ahead of RHEL |
| `opensuse` | `dokken/opensuse-leap-15` | SUSE family (openSUSE Leap, SLES) |

Each one boots a container with **systemd as PID 1** (privileged, host cgroup
namespace) -- `vitals_scan` reads `service_facts` and `journalctl`, so a
sleep-forever container would exercise none of the paths worth testing.

### Running them

Requires a working Docker daemon. Everything else is installed by
`pip install -r requirements-dev.txt`.

```bash
molecule test -s ubuntu          # one distribution, full create/converge/verify/destroy
molecule test --all              # every scenario, sequentially

molecule converge -s rocky       # leave the container up for debugging
molecule login -s rocky          # shell into it
molecule verify -s rocky         # re-run only the assertions
molecule destroy -s rocky        # clean up
```

The generated dashboard, JSON report, and archive for a run land in that
scenario's ephemeral directory (`molecule converge` prints the path; it is
`~/.ansible/tmp/molecule.*.<scenario>/reports/`).

### What a scenario does

1. **create** -- starts the container and ensures
   `.dev-collections/ansible_collections/sameeralam3127/linux_vitals` links back
   to the repo, so `converge.yml`'s FQCN roles resolve from a fresh clone.
2. **prepare** -- bootstraps a Python interpreter Ansible can use, installs the
   packages the checks look for (chrony, and `yum-utils` on Rocky so
   `needs-restarting` exists), then plants two systemd units:
   - `molecule-flaky.service`, which fails on first start and succeeds on
     restart -- a service `vitals_heal` can genuinely fix;
   - `molecule-broken.service` (`ExecStart=/bin/false`), which can never be
     fixed.
   Both are enabled and left in a failed state.
3. **converge** -- runs `vitals_scan` -> `vitals_heal` -> `vitals_report` with
   `linux_vitals_heal_enabled: true`, writing reports into the scenario's
   ephemeral directory instead of `inventory_dir`.
4. **verify** -- asserts against the generated JSON report, the HTML dashboard,
   and the container itself:
   - **discovery**: OS family, package manager, log source, uptime, memory,
     running kernel, boot-space status, security-control status, and that the
     installed time-sync unit was resolved (and, where a container can run it,
     that it is active);
   - **reboot detection**: the source is one this distribution can actually
     provide, so a regression that silently degrades to the kernel-comparison
     fallback fails the scenario (see
     [kernel-reboot-detection.md](kernel-reboot-detection.md));
   - **self-healing**: `molecule-flaky.service` is reported `Fixed`, is counted
     in `auto_fixed_count`, and is genuinely `active` on the host;
     `molecule-broken.service` is *not* fixed and raises a
     "requires manual follow-up" finding;
   - **reporting**: the JSON summary, the rendered dashboard, and the
     timestamped archive copy.

Each distribution reaches reboot detection by a different route, which is the
point of running all four:

| Scenario | `reboot_required_source` |
| --- | --- |
| `ubuntu` | `reboot-required-file` |
| `rocky` | `needs-restarting` |
| `fedora` | `dnf-needs-restarting` (dnf5) |
| `opensuse` | `zypper-needs-rebooting` |

### The SUSE image (fallback strategy)

There is no systemd + Ansible-ready openSUSE image from the same publisher as
the other three, so the SUSE scenario uses Chef's `dokken/opensuse-leap-15`,
which runs systemd as PID 1 but ships **no Python at all**. Leap 15.6's default
`python3` is 3.6, which ansible-core cannot use, so the scenario installs
`python311` over `raw` and pins `ansible_python_interpreter` to
`/usr/bin/python3.11`. This is per-scenario configuration
(`vitals_python_package` / `vitals_python_interpreter` in
`molecule/opensuse/molecule.yml`), so swapping in a different SUSE image later
means changing two lines.

If the dokken image ever becomes unavailable, the fallbacks in order of
preference are: build a small `Dockerfile` from `opensuse/leap:15.6` that
installs `systemd` and `python311`; or drop to `opensuse/tumbleweed`, accepting
that it tracks a rolling release rather than the SLES-aligned Leap.

### What containers cannot prove

Containers share the host kernel and have no bootloader, so some findings fire
in every scenario and are deliberately not asserted against:

- `Latest installed kernel is not currently running` -- `/lib/modules` is empty
  in a container, so no installed kernel can match `uname -r`.
- Bootloader validation reports `unavailable` -- there is no `/boot` content,
  no GRUB, and no systemd-boot loader configuration.
- `boot_space_status` is `Not Available` -- `/boot` is not a separate mount.
- `RAM usage is critical` can fire depending on the Docker host's memory
  pressure at the time.
- `chronyd` does not start in the openSUSE image on GitHub's runners, so that
  scenario sets `vitals_expect_time_sync_active: false`. It still asserts the
  installed unit was *resolved* -- what the scan is responsible for -- just not
  that chrony can discipline a clock it does not own.

Bootloader resolution and latest-kernel filtering are covered instead by the
synthetic-root unit tests in `tests/test_reboot_detection.py`, which run the
real discovery shell scripts against a fabricated `/boot` layout.
