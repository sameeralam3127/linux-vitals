# LinuxVitals demo environment

A disposable three-distro fleet you can break on purpose, in one command.

```bash
cd demo
./run.sh
```

That starts Ubuntu 24.04, Rocky 9, and Fedora 42 containers, provisions them
into healthy hosts, scans them, breaks them, scans them again, and then runs
self-healing -- leaving you three dashboards to compare. It takes a few
minutes on a cold image cache and about forty seconds after that.

```
     docker compose up
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
 Ubuntu   Rocky   Fedora        ← three throwaway systemd containers
   └────────┼────────┘
            │  break.yml injects real faults
            ▼
    ansible-playbook healthcheck.yml
            │
   ┌────────┼────────────┐
   ▼        ▼            ▼
  HTML     JSON     Slack / webhook
```

## Requirements

- Docker (Desktop on macOS/Windows, or `dockerd` on Linux), running
- Python 3.10+ and `ansible-core` 2.16+ on your machine
- About 2 GB of disk for the three images

Nothing is installed outside Docker and `demo/`. `./run.sh clean` removes the
containers, the network, and every file the demo wrote.

## Commands

| Command | What it does |
| --- | --- |
| `./run.sh` | The full walkthrough: `up` → `scan` → `break` → `scan` → `heal` |
| `./run.sh up` | Start and provision the containers, healthy |
| `./run.sh scan` | Read-only health check; opens the dashboard |
| `./run.sh break` | Inject the faults |
| `./run.sh heal` | Re-run with `linux_vitals_heal_enabled=true` |
| `./run.sh repair` | Undo the faults, keep the containers |
| `./run.sh clean` | Remove containers, network, and demo output |

`break` and `repair` take the same tags, so you can demonstrate one check at a
time:

```bash
ansible-playbook -i inventory.ini playbooks/break.yml --tags disk
```

Tags: `service`, `reboot`, `disk`, `logs`, `memory`.

## The faults, and what each one proves

| Fault | How it is injected | What the dashboard shows |
| --- | --- | --- |
| Failed service, recoverable | `demo-payments-api.service` is armed to fail, restarted, then disarmed | `Fixed` in the self-healing panel after `./run.sh heal`, and `auto_fixed_count: 3` across the fleet |
| Failed service, unrecoverable | `demo-log-shipper.service` runs `/bin/false` | `Failed to Fix`, plus the finding *"demo-log-shipper.service requires manual follow-up"* |
| Reboot required | `touch /run/reboot-required` plus a `.pkgs` list, on the Ubuntu host | *"System reboot is required"*, detection source `/run/reboot-required`, and the two pending packages |
| Disk pressure | A computed fill written into a 64 MB ext4 `/boot` | Boot space `Low` at 12% free, with true free/total MB |
| Log errors | Error lines written to the journal with `systemd-cat` | Log error count and excerpt; *"Recent logs contain error or failed entries"* |
| SELinux | *Not injected* -- containers genuinely run without SELinux | *"SELinux is disabled or unavailable"* on Rocky and Fedora; *"AppArmor is disabled or unavailable"* on Ubuntu |
| Memory | Threshold lowered, not memory consumed -- see below | RAM `Warning` against the host's real usage figure |

### One thing the demo shows by omission

Break the fleet and run `./run.sh scan` **without** healing, and the two failed
demo services produce **no finding at all**. That is not a bug in the demo --
it is the current behaviour of `vitals_scan`, which checks a fixed list of
required services (`sssd`, `systemd-journald`, time sync) and does not report
arbitrary failed units. A failed unit only reaches the dashboard once
`vitals_heal` has tried to restart it.

Making the required-service list configurable and reporting every failed unit
is tracked as [#32](https://github.com/sameeralam3127/linux-vitals/issues/32)
and scheduled for Q2 on the [roadmap](../docs/roadmap.md). Until it lands,
this is a real gap worth knowing about, and the demo is the fastest way to see
it: compare the findings list after `./run.sh scan` with the one after
`./run.sh heal`.

## What is real and what is staged

Worth saying out loud, because a demo that overstates itself is worse than no
demo:

**Real.** The failed services are really failed systemd units, found through
`service_facts` and `systemctl is-enabled` the same way they would be on a
production host. `/boot` is a real mount with real free space, and the
boot-space check reads it out of `ansible_facts['mounts']`. The journal lines
are really in the journal. `/run/reboot-required` is the same marker
`unattended-upgrades` writes and the same one `vitals_scan` looks for. The
self-healing step really does restart a service and really does fail to fix
the one that cannot be fixed.

**Staged.** Two things:

- **Memory.** A container's `/proc/meminfo` is the *host's* -- Ansible's
  memory facts describe your laptop, not the container, and allocating memory
  inside the container does not move them. Rather than write a fake number
  into the report, `break.yml` lowers the warning threshold until your real
  memory usage crosses it. The reading is true; the line it is judged against
  is what moved.
- **`/boot` itself.** Containers have no separate boot partition, so
  `provision.yml` builds a 64 MB ext4 image and loop-mounts it there. It has
  to be a real filesystem rather than a tmpfs, because Ansible omits tmpfs
  from `ansible_facts['mounts']` -- which is exactly where `vitals_scan` reads
  boot space from. The check is not being faked; it is being given something
  to look at, and the free-space numbers it reports are true.

**Never green.** A container fleet cannot score a passing health check, and
the demo does not pretend it can: `sssd` is not installed, the "running
kernel" is the Docker VM's, and neither SELinux nor AppArmor is active. Those
three findings are present in every frame, so the health score reads 0.0% even
in the "healthy" state. What the demo shows is the *delta* -- boot space going
`Healthy` → `Low`, reboot going `No` → `Required`, auto-fixed going `0` → `3`
-- not a green-to-red transition. On real hosts the score moves; here, the
columns do.

**Not demonstrable here.** Bootloader default-kernel validation and
`needs-restarting`-based reboot detection on the RHEL family both need a real
boot path and a real package transaction. The containers report those checks
as unavailable, which is the same documented degradation you would see on a
host where the tooling is missing -- see
[../docs/kernel-reboot-detection.md](../docs/kernel-reboot-detection.md).

## Why containers, and why privileged

`vitals_scan` reads `service_facts` and `journalctl`, so systemd has to be PID
1 -- a sleep-forever container would exercise none of the paths this demo
exists to show. That is what forces `privileged: true` and the cgroup mount in
`docker-compose.yml`. These are disposable demo containers on your laptop, not
a pattern to copy into production. The same trade-off, for the same reason, is
already made by the Molecule suite under [../molecule/](../molecule/), and
both are called out as out of scope in [../SECURITY.md](../SECURITY.md).

Ansible reaches the containers through `community.docker.docker` rather than
SSH, so the demo needs no keys, no `sshd`, and no cleanup on your machine. On
a real fleet the transport is SSH; nothing else about the run differs.

## Adding notifications to the demo

Drop a `.env` next to `inventory.ini` and the reporting role will pick it up --
the demo resolves `.env` from `inventory_dir` like any other project:

```dotenv
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/your/team/webhook"
```

A [webhook.site](https://webhook.site) URL in `GENERIC_WEBHOOK_URL` is the
quickest way to show the payload without a Slack workspace.

## Regenerating the README screenshots

The dashboard images in the top-level README come from a real demo run and can
be rebuilt in one command:

```bash
./screenshots.sh
```

It runs the full cycle, captures the fleet overview, an expanded host, and a
baseline/postcheck comparison with a headless Chrome, and writes them to
`docs/images/`. Screenshots age badly -- this is what keeps refreshing them
after a dashboard change from being a chore anyone has to remember how to do.

## Recording a walkthrough

The three archived dashboards under `demo/reports/archive/` are the story:
healthy, broken, healed. A recording that opens each in turn and points at the
health-score banner needs no narration beyond naming the fault. `./run.sh
break --tags service` then `./run.sh heal` is the shortest loop that shows
remediation end to end.
