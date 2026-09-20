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

Three things, in this order. Two of them are fixable and tracked.

### 1. Journal transfer -- the scaling ceiling

`vitals_scan` runs `journalctl --since "{{ linux_vitals_log_window }}"` and
registers the **entire output** as `stdout`, which is transferred to the
control node and filtered there in Jinja
([discovery.yml:53](../roles/vitals_scan/tasks/discovery.yml#L53) and the
match at line 681). A second pass does the same over
`linux_vitals_audit_log_window`, which defaults to **7 days**.

The consequence is that per-host cost scales with *log volume*, not with host
count -- and log volume is the variable you control least. A busy host can
return tens of megabytes for a week of journal, all of it crossing the network
and then sitting in control-node memory as a registered variable across every
host in the play, simultaneously.

**This is the single biggest lever on both runtime and control-node memory.**
It is tracked as
[#23](https://github.com/sameeralam3127/linux-vitals/issues/23) and is a Q1
item on the [roadmap](roadmap.md); the fix is to filter on the managed host and
return counts plus a bounded excerpt, rather than shipping the window. Until
then, the mitigation is to narrow the windows -- see Tuning below.

### 2. Fork count

`ansible.cfg` does not set `forks`, so Ansible's default of **5** applies. A
100-host fleet is therefore scanned 5 hosts at a time by default. This is the
cheapest thing to change and usually the first thing worth changing.

### 3. Fact gathering and per-host probes

`gathering = smart` with a `jsonfile` fact cache under `.facts` is already
configured, so repeat runs skip re-gathering. Note that the cache has **no
expiry set** ([#25](https://github.com/sameeralam3127/linux-vitals/issues/25)),
which is a correctness caveat as much as a performance one: a fast run may be
fast because it is reporting stale facts.

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
```

Rules of thumb, none of which substitute for measuring your own fleet:

- **Raise `forks` before anything else.** Match it to control-node cores and
  to what your SSH infrastructure and any bastion will tolerate. A bastion is
  usually the first thing to saturate, not the control node.
- **`pipelining = True` is the second-biggest win** and costs nothing, as long
  as `requiretty` is not set in sudoers on your targets.
- **Narrow `linux_vitals_audit_log_window` first.** The 7-day default is the
  most expensive setting in the collection, and the kernel-install-failure
  check it feeds is the least time-sensitive one.
- **Split very large fleets by group** rather than raising `forks` without
  limit. Control-node memory holds every host's registered journal output at
  once; that is what falls over first, and it fails at whatever size your
  fleet's log volume dictates rather than at a fixed host count.
- **Reporting is `run_once`.** Rendering happens once on the control node
  regardless of fleet size, so it is a fixed cost, but the template iterates
  every host -- expect the HTML file itself to grow roughly linearly.

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
  `journalctl --since "30 minutes ago" | wc -c` on a representative host.
  Without this, two timings from different fleets are not comparable.
- whether the fact cache was warm

A report of "100 hosts, 50 forks, 4m10s, 2.1 GB peak RSS, ~8 MB journal per
host" is useful to everyone. "100 hosts, 4 minutes" is not.

## Known limits

- **Control-node memory is the binding constraint, not CPU**, for the reason
  in §1. If a run is killed, it is almost always the journal data.
- **Concurrent runs sharing an output directory can corrupt reports and
  snapshots** ([#26](https://github.com/sameeralam3127/linux-vitals/issues/26)).
  Sharding a large fleet across parallel runs needs a distinct
  `linux_vitals_output_path` and `linux_vitals_snapshot_dir` per shard until
  that is fixed.
- **There is no batching or `serial` in the shipped playbooks.** Every host is
  in one play. If you need rolling execution, wrap the roles in your own
  playbook with `serial:` set.
