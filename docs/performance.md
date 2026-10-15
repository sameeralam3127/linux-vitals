# Performance and scale

## No published numbers yet

This project does not currently publish fleet-scale timings, because nobody
has run it against a fleet large enough to produce honest ones. Rather than
quote a figure from a laptop and let it be read as a fleet measurement, this
page documents **what to measure, what dominates the cost, and how to
reproduce it** -- and leaves the results table empty until a real run fills
it in.

If you run LinuxVitals against a fleet of any size, the table below is worth a
pull request.

## Results

Measure with [`demo/benchmark.sh`](../demo/benchmark.sh) (control plane only)
or with the real-fleet method further down. Fill in the environment line; a
number without one is not a measurement.

| Hosts | Forks | Wall time | Control-node peak RSS | Control-node CPU |
| --- | --- | --- | --- | --- |
| 10 | | | | |
| 50 | | | | |
| 100 | | | | |
| 500 | | | | |

> Environment: _(control node spec, Ansible Core version, network topology, average journal volume per host)_

## What dominates the cost

Three things, in this order.

### 1. Journal scans -- capped per host since #23

`vitals_scan` reads the journal twice: entries at `linux_vitals_log_priority`
(default `err`) or worse over `linux_vitals_log_window` for `log_errors`, and
kernel/bootloader failure lines over `linux_vitals_audit_log_window`, which
defaults to **7 days**, for `kernel_install_failures`.

Until [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) both
reads registered the **entire window** as `stdout`, transferred it to the
control node and filtered it there in Jinja, so per-host cost scaled with log
volume rather than host count, and a busy host could hand the control node
tens of megabytes. Now both are filtered on the managed host -- `journalctl
--priority` for the first, `grep` for the second -- and each returns at most
`linux_vitals_log_max_lines` lines (default `2000`), the newest ones. Only a
count and a five-line excerpt per scan are kept as facts.

What that leaves:

- **On the control node, journal data is bounded per host.** A host's
  registered results hold at most `linux_vitals_log_max_lines` lines per scan
  (twice over, as `stdout` and `stdout_lines`), however much it logs. Most
  hosts send far fewer: only error-priority entries and kernel-failure
  matches leave the host. Control-node memory now grows with host count, not
  with how unhealthy the fleet is.
- **On the managed host, the kernel-failure scan still reads its whole
  window.** `grep` has to see every line of the 7 days to find the matches, so
  that probe's run time grows with the host's journal volume. Narrow
  `linux_vitals_audit_log_window` if it dominates (see Tuning below). The
  error scan does not: journalctl looks entries up by priority and stops at
  the cap.

### 2. Fork count

`ansible.cfg` does not set `forks`, so Ansible's default of **5** applies. A
100-host fleet is therefore scanned 5 hosts at a time by default. This is the
cheapest thing to change and usually the first thing worth changing.

### 3. Fact gathering and per-host probes

`gathering = smart` with a `jsonfile` fact cache under `.facts` can skip
implicit gathering while entries are younger than the configured one-hour
lifetime (`fact_caching_timeout = 3600`). `vitals_scan` still explicitly
refreshes its platform fact subsets and runs its health probes on every
discovery run. See [the cache policy](architecture.md#fact-cache-lifetime)
and [how to force a cold run](troubleshooting.md#cached-facts).

Beyond facts, each host runs 13 short commands. They are cheap individually;
at 500 hosts they are 6,500 SSH round trips, which is where connection reuse
starts to matter more than anything on the host.

## Tuning

```ini
# ansible.cfg -- in your project, not this repo's
[defaults]
forks = 50
fact_caching_timeout = 3600   # see #25; pick a window shorter than your run cadence

[ssh_connection]
pipelining = True             # removes a round trip per task; needs !requiretty
control_path_dir = ~/.ansible/cp
ssh_args = -o ControlMaster=auto -o ControlPersist=300s -o PreferredAuthentications=publickey
```

```yaml
# group_vars/all.yml -- narrow the journal windows
linux_vitals_log_window: "15 minutes ago"
linux_vitals_audit_log_window: "24 hours ago"
# Lines each journal scan may return per host; lower it to bound the
# control node's worst case more tightly.
linux_vitals_log_max_lines: 2000
```

Rules of thumb, none of which substitute for measuring your own fleet:

- **Raise `forks` before anything else.** Match it to control-node cores and
  to what your SSH infrastructure and any bastion will tolerate. A bastion is
  usually the first thing to saturate, not the control node.
- **`pipelining = True` is the second-biggest win** and costs nothing, as long
  as `requiretty` is not set in sudoers on your targets.
- **Narrow `linux_vitals_audit_log_window` first.** The 7-day default is the
  most expensive setting in the collection -- every host reads that much
  journal to answer it -- and the kernel-install-failure check it feeds is the
  least time-sensitive one.
- **Split very large fleets by group** rather than raising `forks` without
  limit. Control-node memory holds every host's registered results at once.
  Journal output in them is capped by `linux_vitals_log_max_lines`, so the
  worst case is predictable, but it still grows with every host you add.
- **Reporting is `run_once`.** Rendering happens once on the control node
  regardless of fleet size, so it is a fixed cost, but the template iterates
  every host -- expect the HTML file itself to grow roughly linearly. With
  archiving on, each archived report is rendered again rather than copied
  from the latest one, so a concurrent run's report can never be archived
  as this run's.

## Sharding a large fleet

Past what one control node holds in memory, split the fleet into several
runs, one per group, run one after another or side by side. Every shard of a
maintenance window keeps the window's `linux_vitals_maintenance_id` and the
same `linux_vitals_snapshot_dir`, so each postcheck host finds its baseline
whichever shard wrote it. What each shard needs of its own:

- **`linux_vitals_snapshot_shard`.** This is what shards sharing one snapshot
  directory must set. Each shard records its hosts in
  `<snapshot_dir>/<maintenance_id>/<phase>/.shards/<shard>.json`, and a run
  that reuses a shard id for hosts it was not recorded with fails before
  writing anything, so two groups given the same id by mistake cannot quietly
  end up in one comparison. Without shard ids every run counts as shard
  `default`, and a run with other hosts only warns. Re-running a shard, or
  part of it with `--limit`, is fine. Baseline and postcheck shards need not
  line up.
- **`linux_vitals_output_path` and `linux_vitals_json_output_path`**, so each
  shard writes its own dashboard. They can share a directory, and the archive
  directory: retention pruning only touches each report's own archives.

```bash
for group in web db cache; do
  ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
    --limit "$group" \
    -e linux_vitals_maintenance_id=2026-11-02-patch \
    -e linux_vitals_snapshot_shard="$group" \
    -e linux_vitals_output_path="{{ inventory_dir }}/reports/baseline-$group.html" \
    -e linux_vitals_json_output_path="{{ inventory_dir }}/reports/baseline-$group.json" &
done
wait
```

Each shard's dashboard covers its own hosts; there is no merged fleet-wide
dashboard. What is safe for concurrent runs to share, and what is not, is in
[architecture.md](architecture.md#runs-that-share-a-directory).

## How to measure

### Control-plane lower bound (local, reproducible)

```bash
cd demo
./benchmark.sh 10 25 50
```

This starts N systemd containers, runs a warm-up pass, then times a full scan
and render, reporting wall time, peak control-node RSS, and CPU seconds.

**What these numbers are not.** Containers are local, so there is no network
latency and no SSH handshake. Their journals are seconds old, so the dominant
cost described above -- journal transfer -- is absent almost entirely. A
benchmark run is a measurement of Ansible's fan-out and this collection's
control-node work with per-host cost at its floor. It is useful for comparing
fork counts and for catching a regression between releases. It is **not** a
fleet simulation, and a number from it should never be quoted as "tested
against N hosts".

A larger inventory to exercise the dashboard against is in
[examples/inventory/large-fleet.example.ini](../examples/inventory/large-fleet.example.ini) --
ten generated nodes, enough to see how the search, filter, and sort behave
when the table is no longer three rows.

### Real fleet (the only numbers worth publishing)

```bash
time ansible-playbook -i inventory.ini playbooks/healthcheck.yml -f 50

# Per-task breakdown: which probe actually costs you
ANSIBLE_CALLBACKS_ENABLED=ansible.posix.profile_tasks \
  ansible-playbook -i inventory.ini playbooks/healthcheck.yml -f 50

# Control-node peak memory (GNU time; `gtime` from coreutils on macOS)
/usr/bin/time -v ansible-playbook -i inventory.ini playbooks/healthcheck.yml -f 50
```

Record alongside any timing:

- host count, and `forks`
- control node: cores, RAM, and whether it is a VM or a container
- network topology: same VLAN, across a WAN, through a bastion
- **average journal volume per host** for your configured windows --
  `journalctl --since "7 days ago" | wc -c` on a representative host. Since
  #23 it drives the host-side time of the kernel-failure scan rather than
  control-node memory, but two timings from fleets with very different
  journals are still not comparable.
- whether the fact cache was warm

A report of "100 hosts, 50 forks, 4m10s, 2.1 GB peak RSS, ~8 MB journal per
host" is useful to everyone. "100 hosts, 4 minutes" is not.

## Known limits

- **Control-node memory is the likeliest constraint, not CPU.** Before #23 a
  killed run was almost always journal data. Journal output is now capped per
  host (§1), so memory scales with host count and `linux_vitals_log_max_lines`
  rather than with log volume; nobody has yet measured where that limit falls
  on a real fleet.
- **Concurrent runs need their own output paths and shard ids, not their own
  directories** ([#26](https://github.com/sameeralam3127/linux-vitals/issues/26)).
  Two runs writing the same `linux_vitals_output_path` at once leave a
  complete report, the last one's, but two that start rendering in the same
  second share an archive name and keep only one archive. See
  [Sharding a large fleet](#sharding-a-large-fleet).
- **There is no batching or `serial` in the shipped playbooks.** Every host is
  in one play. If you need rolling execution, wrap the roles in your own
  playbook with `serial:` set.
