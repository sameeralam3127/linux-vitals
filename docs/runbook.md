# Operator runbook

What to do when LinuxVitals reports something. One section per finding, each
with what it actually means, how to confirm it independently, and what to do
about it.

[Troubleshooting](troubleshooting.md) is the companion to this: it covers the
tool misbehaving. This covers the *fleet* misbehaving.

## Contents

- [Triage: reading a report in the right order](#triage-reading-a-report-in-the-right-order)
- [Critical findings](#critical-findings)
- [Warning findings](#warning-findings)
- [Informational findings](#informational-findings)
- [Certificate findings](#certificate-findings)
- [Procedures](#procedures)
- [When LinuxVitals is wrong](#when-linuxvitals-is-wrong)

## Triage: reading a report in the right order

The dashboard is a queue, not a list. Work it in this order:

1. **Critical hosts tile.** These have at least one finding that means
   something is broken now, or that you are blind to it. Filter to them with
   the **Critical** severity chip.
2. **Regressed** (postcheck runs only). A host that was passing before your
   maintenance window and is failing after it is the window's fault until
   proven otherwise.
3. **Warning hosts.** Work these in a batch, not one at a time -- most warning
   findings are fleet-wide patterns (a missed reboot wave, a config drift),
   not individual incidents.
4. **Info.** Read weekly. Never page on these.

Two numbers worth checking before you start:

- `summary.servers_checked` against your expected host count. A host that
  failed to connect is *absent from the report*, not failing in it.
- `summary.fail_on_severity`. If someone raised it, hosts with warnings are
  reported as `Pass`. The severity column still tells the truth; the status
  column is answering a different question.
- `summary.unknown_host_count` (the *Hosts with unknown checks* tile). A
  finding marked `unknown` means the check could not run on that host, so
  nothing is known about what it covers. Read its `reason`, which usually
  names a missing tool or an unreadable file, and fix that first: until it
  runs, the absence of a problem there is not evidence of anything.

## Critical findings

### `ram_critical` -- RAM usage is critical

**Means:** used memory is at or above `linux_vitals_ram_critical_threshold`
(default 95%). The next allocation spike is an OOM kill.

**Confirm:**
```bash
free -m
ps -eo pid,ppid,rss,comm --sort=-rss | head -15
journalctl -k --since "24 hours ago" | grep -i "out of memory\|oom_kill"
```

**Do:** if the journal already shows OOM kills, this is an incident, not a
warning -- find what was killed and whether it restarted. If not, identify the
top consumer. A steadily climbing RSS on one process across several runs is a
leak; compare against the previous archived report rather than guessing.

**Do not** simply raise the threshold to clear the finding. If 95% is genuinely
normal for this host class, set `linux_vitals_ram_critical_threshold` in that
group's `group_vars` and write down why.

### `journald_inactive` -- systemd-journald is not active

**Means:** the host's own logging is down. Every other log-derived finding on
this host is now unreliable, including the absence of findings.

**Confirm:**
```bash
systemctl status systemd-journald
journalctl --disk-usage
df -h /var/log
```

**Do:** most often this is a full `/var/log` or a corrupt journal file.
`journalctl --verify` identifies a bad file; `systemctl restart
systemd-journald` recovers after you have made space. **Treat any other finding
on this host as unproven until logging is back.**

### `service_manual_followup` -- a service requires manual follow-up

**Means:** `vitals_heal` restarted an enabled service that was in a failed
state, and the restart did not hold. The `subject` field names the unit; the
matching entry in `self_healing.healing_results` says why in `reason` and
`detail` (see [Self-healing outcomes](report-guide.md#self-healing-outcomes)):

| `reason` | What happened |
| --- | --- |
| `failed` | It failed again: its start job failed (`detail` then quotes the restart's error), or it came up and failed within the stability window |
| `restarted_during_check` | It came up, crashed, and systemd's `Restart=` brought it back -- it is flapping |
| `restart_error` | `systemctl start` failed without leaving a failed unit -- the unit is missing, or its state could not be read; `detail` has the error |
| `inactive` | It is not running, but did not fail either -- often a unit whose process exited cleanly |
| `not_settled` | Still starting or stopping when the polling budget ran out (finding `status: unknown`) |
| `check_failed` | Its state could not be read after the restart (finding `status: unknown`) |

**Confirm:**
```bash
systemctl status <unit>
journalctl -u <unit> --since "1 hour ago" --no-pager
systemctl list-dependencies --failed <unit>
```

**Do:** a unit that fails a clean restart has a real cause -- a config it
cannot parse, a port already bound, a dependency that is itself down, a
filesystem it cannot write. Read the journal from the restart attempt forward.
For `not_settled`, check whether the unit came up after the run: if it did,
it is slow to start, and `linux_vitals_heal_settle_retries` /
`linux_vitals_heal_settle_delay` can give it longer.

### `cert_expired` -- a certificate has already expired

See [Certificate findings](#certificate-findings).

### `filesystem_read_only` -- a filesystem unexpectedly became read-only

One finding per mount, named in `subject`. Always `critical`.

**Means:** the mount is read-only and is not listed in
`linux_vitals_disk_expected_readonly_mounts`. This is almost never
intentional -- the kernel remounts a filesystem read-only after it detects an
I/O error or metadata corruption, specifically to stop making things worse.
Treat this as urgent: every write to that mount is silently failing or has
been failing since the remount, and anything that logs, queues, or persists
state there is now degraded in a way that may not be visible until something
downstream notices missing data.

**Confirm:**
```bash
mount | grep ' ro,\| ro)'
dmesg -T | grep -iE 'remount|read-only|ext4-fs error|i/o error' | tail -40
journalctl -k --since "1 hour ago" | grep -iE 'remount|i/o error'
```

**Do:** identify the underlying disk/volume problem before remounting
read-write -- a remount that just papers over a failing device will flip
back to read-only again. If the mount is *supposed* to be read-only (a
golden image, a read-only root), add it to
`linux_vitals_disk_expected_readonly_mounts` so the finding stops firing for
that mount specifically, rather than overriding the finding's severity for
every host.

## Warning findings

### `reboot_required` -- system reboot is required

**Means:** the distro's own mechanism says a reboot is pending. The
`reboot.source` field names which one fired, and `reboot.pending_packages`
lists what wants it.

**Confirm:** per-distro, and see
[kernel-reboot-detection.md](kernel-reboot-detection.md):
```bash
cat /run/reboot-required.pkgs        # Debian/Ubuntu
needs-restarting -r                  # RHEL family
zypper needs-rebooting               # SUSE
```

**Do:** schedule it. Use the [maintenance window
procedure](#procedure-a-maintenance-window) so you get a before/after
comparison. If a host has been pending for weeks, it is carrying an unpatched
kernel -- treat the age, not the finding, as the signal.

### `kernel_not_latest` / `bootloader_mismatch`

**Means:** `kernel_not_latest` -- a newer kernel is installed than the one
running (usually just a pending reboot). `bootloader_mismatch` -- the default
boot entry does **not** select the newest kernel, so rebooting will *not* fix
it.

**Confirm:**
```bash
uname -r
ls -1 /lib/modules
grubby --default-kernel          # RHEL family
grub2-editenv list               # RHEL family
```

**Do:** `bootloader_mismatch` is the serious one of the pair. Rebooting a host
in this state boots the old kernel and leaves you believing you patched it.
Fix the default entry first (`grubby --set-default`), then reboot.

### `boot_space_low` -- boot partition free space is low

**Means:** `/boot` free space is below `linux_vitals_boot_warning_threshold`
(default 20%). The next kernel update will fail partway, which is a far worse
state than a full disk.

**Confirm:**
```bash
df -h /boot
rpm -q kernel                    # RHEL family
dpkg -l | grep linux-image       # Debian family
```

**Do:** remove old kernels through the package manager, never with `rm`:
```bash
dnf remove --oldinstallonly --setopt installonly_limit=2   # RHEL family
apt autoremove --purge                                     # Debian family
```
Deleting files from `/boot` by hand leaves the package database believing they
are present, and the next update will not regenerate them.

### `filesystem_space_low` -- a filesystem is running out of space

One finding per mount, named in `subject`; raised as `warning` or `critical`
by threshold.

**Means:** a mount's used space is at or above
`linux_vitals_disk_warning_threshold` (default 80%) or
`_critical_threshold` (default 95%). Every real filesystem is in scope except
the pseudo/network ones listed in `linux_vitals_disk_exclude_fstypes`
(`tmpfs`, `proc`, `nfs`, and the like); add or remove mounts with
`linux_vitals_disk_include_mounts` / `_exclude_mounts`.

**Confirm:**
```bash
df -h
du -sh /path/to/mount/* | sort -rh | head -20
```

**Do:** find and clear the largest consumer -- logs, core dumps, package
caches, container layers -- rather than growing the volume as a reflex.
A mount that is legitimately full by design should get a per-host threshold
override and a note saying why, the same as a busy CPU host under
`cpu_load_high`.

### `filesystem_inodes_low` -- a filesystem is running out of inodes

One finding per mount, named in `subject`; raised as `warning` or `critical`
by threshold.

**Means:** a mount's used inode count is at or above
`linux_vitals_disk_inode_warning_threshold` / `_critical_threshold`. A
filesystem can read as having plenty of free space and still fail every
write with `No space left on device`, because inodes ran out first -- common
with huge numbers of small files (mail spools, session caches, per-request
temp files that never got cleaned up).

**Confirm:**
```bash
df -i
find /path/to/mount -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head -20
```

**Do:** find and remove the directory tree generating the small files, then
fix whatever is failing to clean up after itself. Reformatting with more
inodes is a last resort and needs a backup/restore window.

### `filesystem_unavailable` -- a filesystem's capacity could not be read

One finding per mount, named in `subject`. `status: unknown` with `reason`.

**Means:** the mount is present but its size or inode facts could not be
read -- for example a `/boot` entry with no size data, which used to be
misread as 0% free and wrongly raise `boot_space_low`; it now surfaces here
instead, with the actual gap named in `reason`.

**Confirm:**
```bash
df -h /path/to/mount
stat -f /path/to/mount
```

**Do:** treat `unknown` the same as any other check that could not run --
under the default `linux_vitals_fail_on_severity`, it still fails the host.
Fix whatever is preventing the read (a stale mount, a disconnected network
share, a device that dropped out), then re-run.

### `filesystem_probe_degraded` -- some filesystem facts could not be read

Host-level, no `subject`, fires at most once per host. `status: unknown`
with `reason` naming how many mounts were affected.

**Means:** one or more mount entries returned unreadable facts during
discovery (a bare string instead of the expected fields) and were folded
into this single finding rather than each raising its own
`filesystem_unavailable`, to avoid flooding a host with near-duplicate
unknowns when the underlying cause is the same for all of them.

**Confirm:** check `filesystem_degraded_count` in the JSON report and look
at the mount list for entries with `status: Unknown`.

**Do:** same as `filesystem_unavailable` -- find the mount(s) behind the
count and fix whatever is blocking the read.

### `sssd_inactive` / `time_sync_absent` / `time_sync_inactive`

**Means:** a service the fleet relies on is not running. Time sync is the one
people under-rate: clock drift breaks TLS validation, Kerberos, log
correlation, and certificate checks, and it does so confusingly.

**Confirm:**
```bash
systemctl status sssd chronyd
chronyc tracking
timedatectl status
```

**Do:** for `sssd`, expect authentication to be failing for directory users
already. For time sync, check drift before restarting -- a host that is hours
out may need `chronyc makestep` rather than a restart.

### `required_service_inactive` -- an operator-declared required service is not active

**Means:** a unit named in `linux_vitals_required_services` -- a fleet's own
must-run service, such as `nginx`, `postgresql`, or `docker` -- is not
running. Same check as `sssd_inactive`/`time_sync_inactive`, just for a name
the operator added rather than one this collection ships.

**Confirm:**
```bash
systemctl status <unit>
journalctl -u <unit> --since "1 hour ago"
```

**Do:** treat it like any other required-service finding -- check why it
stopped before restarting it, since a service that keeps failing on restart
usually has a configuration or dependency problem, not a transient one.

### `failed_units_present` -- enabled units are in a failed state

**Means:** `systemctl --failed` would show at least one unit that
`service_facts` reports as enabled, beyond the handful of required services
this collection checks by name. The finding's count is only the units this
collection could confirm are enabled; disabled and masked units that are
intentionally stopped are excluded, and a crashed unit whose enabled state
could not be read counts toward `failed_unit_count` in the report but not
toward this finding -- see `docs/report-guide.md` for the full field.

**Confirm:**
```bash
systemctl --failed
systemctl is-enabled <unit>
```

**Do:** check each listed unit the same way you would investigate any failed
service -- `journalctl -u <unit>` for why it stopped, then decide whether to
restart it, disable it if it is no longer needed, or leave it for
`vitals_heal` if it is enabled for self-healing.

### `selinux_disabled` / `apparmor_disabled`

**Means:** the host's mandatory access control is off or unavailable.

**Confirm:**
```bash
getenforce; sestatus            # RHEL family
aa-status                       # Debian family
```

**Do:** decide once, per host class, and encode the decision. If a group
genuinely runs without SELinux, record it rather than living with a permanent
finding:
```yaml
linux_vitals_finding_severity_overrides:
  selinux_disabled: info
```
A permanent warning that everyone ignores is worse than no warning.

### `kernel_install_failures`

**Means:** kernel, GRUB, dracut, or initramfs failures appeared in the audit
log window (default 7 days). Often paired with `boot_space_low` -- a failed
kernel install is usually a full `/boot`.

**Confirm:** this is the filter the scan runs on the host:
```bash
journalctl --system --since "7 days ago" --output=short-iso \
  | grep -aEi '(kernel|grub|dracut|initramfs).*(fail|error)'
```

**Do:** re-run the failed transaction after fixing the cause, and **verify the
bootloader entry afterwards**. A partially installed kernel that is listed in
GRUB but has no initramfs will not boot.

### `cpu_load_high` -- CPU load is high for the number of CPUs

Raised as `warning` or `critical` by threshold, so it can sit in either
section of a report.

**Means:** the 5-minute load average divided by the online CPUs is at or above
`linux_vitals_load_warning_threshold` (default 1.5) or
`linux_vitals_load_critical_threshold` (default 3.0). Above 1.0, runnable
tasks are queueing for CPU. On Linux, load also counts tasks blocked on I/O,
so a high load with idle CPUs points at storage, not compute.

**Confirm:**
```bash
uptime; nproc
top -b -n 1 | head -20                 # %us/%sy high = CPU; %wa high = I/O wait
cat /proc/pressure/cpu /proc/pressure/io
```

**Do:** check `pressure_stall_high` on the same host. CPU stall agrees with a CPU
problem; I/O stall with idle CPUs means the load is waiting on disk. Find the
top consumers, then decide between fixing a runaway, rescheduling batch work,
or adding capacity. A host that is busy by design (build agents, batch nodes)
should get its own threshold in `group_vars`, with the reason written down.

### `pressure_stall_high` -- tasks are stalled waiting for CPU, memory or I/O

One finding per resource, named in `subject`; raised as `warning` or
`critical` by threshold.

**Means:** PSI (pressure stall information, kernel 4.20+) shows that for at
least `linux_vitals_psi_warning_threshold` percent (default 25) of the last
minute, some task was waiting for that resource. It measures lost time rather
than utilisation, which makes it the most direct "is this host struggling"
signal Linux has. Memory stall means reclaim or swapping is slowing work down;
I/O stall means storage is the bottleneck.

**Confirm:**
```bash
cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io
vmstat 1 5                             # si/so = swapping, wa = I/O wait
```

**Do:** for memory, read it together with `ram_critical` and `swap_paging_high`:
find the process growing, or the host that is undersized. For I/O, find the
busy device and process (`iostat -x 1`, `iotop`). For CPU, see `cpu_load_high`.
Hosts whose kernel has no PSI show *unsupported* in the report and never raise
this finding.

### `swap_paging_high` -- the host is actively swapping

Raised as `warning` or `critical` by threshold.

**Means:** between two reads `linux_vitals_swap_sample_seconds` apart (default
2), the host swapped at least `linux_vitals_swap_rate_warning_threshold` pages
per second in and out combined (default 100, about 400 KB/s). Swap that is
merely in use is normal. Pages moving in and out is what makes a host slow.

**Confirm:**
```bash
vmstat 1 10                            # si/so columns, pages per second
free -m
cat /proc/pressure/memory
```

**Do:** the sample is short, so treat one occurrence as a lead, not a verdict.
Memory `pressure_stall_high` on the same host confirms it is sustained. Then
treat it as memory pressure: find the consumer, add memory, or cap the
workload.

## Informational findings

### `log_errors` -- recent logs contain error entries

**Means:** the journal holds entries at priority `err` or worse
(`linux_vitals_log_priority`) in the log window. Healthy hosts log some of
these routinely, which is why it is `info`.

**Confirm:**
```bash
journalctl --system --since "30 minutes ago" --priority err --no-pager
```

**Do:** read the excerpt in the dashboard before acting. Escalate only if the
count is anomalous for the host, or if the excerpt names a service you care
about. A sudden fleet-wide jump is worth investigating; a steady background
count is not. A count equal to `linux_vitals_log_max_lines` (default `2000`)
means at least that many -- see
[tuning the journal scans](troubleshooting.md#tuning-the-journal-scans-for-chatty-hosts).

**Watch for a false negative:** the finding counts by priority, not wording.
A service that writes its errors to stdout or stderr without a syslog
priority prefix is logged at `info` and is not counted; check that unit
directly with `journalctl -u <unit>`. Warnings are not counted either,
including systemd's `Failed with result '...'` line for a failed unit; set
`linux_vitals_log_priority: warning` to include them.

### `failed_logins` -- recent failed login attempts

**Means:** `lastb` returned entries. Any internet-facing host has these
constantly.

**Do:** check `security.last_failed_login` for the source. Repeated attempts
from one internal address is usually a stale credential in a script, not an
attack. **Note:** when `lastb` cannot run, this currently reports a clean host
rather than "unknown"
([#39](https://github.com/sameeralam3127/linux-vitals/issues/39)) -- absence of
this finding is not evidence of absence of failed logins.

## Certificate findings

From the opt-in `vitals_certs` role. All name the certificate path or the
`host:port` in `subject`.

| Finding | What to do |
| --- | --- |
| `cert_expired` | **Outage in progress or imminent.** Renew and reload now. Clients are already failing. |
| `cert_expiring` (critical) | Inside `linux_vitals_cert_critical_days`. Renew today. |
| `cert_expiring` (warning) | Inside the warning window. Schedule it; check automated renewal is actually running. |
| `cert_served_not_on_disk` | Usually **a service never reloaded after renewal** -- the new certificate is on disk, the old one is still being served. `systemctl reload nginx` (or equivalent) and re-run. |
| `cert_weak_signature` | An MD5/SHA-1 signed certificate. Modern clients reject these. Reissue. |
| `cert_self_signed` | A *served* self-signed certificate. Intentional for internal endpoints; a misconfiguration when public. |
| `cert_weak_tls_version` | The endpoint negotiated below `linux_vitals_cert_minimum_tls_version`. Fix the server config. |
| `cert_endpoint_unreachable` | The endpoint could not be reached. Confirm the service is up before assuming a certificate problem. |
| `cert_scan_unavailable` | No `openssl` on the host, so nothing was parsed. Certificate findings are absent, not clean. |

Confirm any of these independently:
```bash
openssl x509 -noout -subject -enddate -in /path/to/cert.pem
openssl s_client -connect host:443 -servername www.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -enddate -issuer
```

**Renewal does not reload.** `certbot renew` writes new files; most services
keep serving the old certificate until reloaded. `cert_served_not_on_disk`
exists specifically to catch that gap, and it is the most common certificate
incident there is.

## Procedures

### Procedure: a maintenance window

Gives you an automatic before/after comparison, which is the difference
between "the fleet is fine" and "the fleet is as fine as it was this morning".

```bash
MAINT_ID="$(date +%Y-%m-%d)-patch-window"

# 1. Before touching anything.
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
  -e linux_vitals_maintenance_id="$MAINT_ID"

# 2. Do the maintenance.

# 3. After, with the same id.
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.postcheck \
  -e linux_vitals_maintenance_id="$MAINT_ID"
```

Then read the postcheck dashboard **Regressed** chip first. A host that was
passing and is now failing is the window's fault until proven otherwise. Hosts
marked **New** had no baseline -- they were added mid-window or were
unreachable during the baseline run, and both are worth knowing.

Keep the snapshot directory until the window is signed off. Snapshots are not
pruned by `linux_vitals_report_retention_count`; delete the maintenance-id
directory when you are done.

### Procedure: responding to a fleet-wide alert

When the Slack summary shows many critical hosts at once, it is almost always
one cause, not many:

1. Open the dashboard, filter to **Critical**.
2. Check whether the findings share an `id`. A single shared finding across
   many hosts is a fleet event -- a failed patch wave, an expired shared
   certificate, an NTP source that went away.
3. Check whether they share a host group, OS family, or kernel version. Sort
   by the OS or Kernel column.
4. Only if the findings are genuinely heterogeneous should you work them
   host-by-host.

### Procedure: onboarding a host into the fleet

```bash
# 1. Reachable, and Python present?
ansible -i inventory.ini new-host -m ansible.builtin.ping

# 2. Scan it alone, read-only, before adding it to scheduled runs.
ansible-playbook -i inventory.ini playbooks/healthcheck.yml --limit new-host

# 3. Check the report for findings that are really onboarding gaps --
#    sssd_inactive and time_sync_absent are the usual two.
```

Add it to scheduled runs only once it reports the same findings as its peers.
A host that joins the fleet already failing trains people to ignore failures.

### Procedure: enabling self-healing safely

```yaml
# group_vars/web_tier.yml -- one group at a time, never globally first.
linux_vitals_heal_enabled: true
```

Before enabling it on a group, list what it *would* restart there:
```bash
ansible -i inventory.ini web_tier -b -m ansible.builtin.shell \
  -a "systemctl list-units --state=failed --no-legend" 2>/dev/null
```
`vitals_heal` restarts any unit that is both **enabled** and **failed**, with
no allowlist. If that set contains something you would not restart unattended
at 3am, do not enable it for that group. See
[threat-model.md](threat-model.md#self-healing-what-it-can-and-cannot-modify).

## When LinuxVitals is wrong

It sometimes is, and knowing where saves you chasing a phantom:

- **A host missing from the report is not a passing host.** Check
  `summary.servers_checked` against your inventory count.
- **`failed_logins` absent does not mean no failed logins** if `lastb` could
  not run ([#39](https://github.com/sameeralam3127/linux-vitals/issues/39)).
- **A service reported `Fixed` stayed up for
  `linux_vitals_heal_stability_seconds` (5 s by default), not forever.** One
  that fails later than that is still reported `Fixed`. Trust `systemctl`
  for anything that has had time to fail since the run.
- **Reboot detection degrades to a kernel comparison** where the distro tool
  is missing, which is noisier. `reboot.source` tells you which path answered;
  see [kernel-reboot-detection.md](kernel-reboot-detection.md#known-edge-cases).
- **`--check` mode does not work**
  ([#38](https://github.com/sameeralam3127/linux-vitals/issues/38)). The scan
  is read-only regardless, so run it for real.
- **Facts may be cached.** The source checkout bounds cache reuse to one hour;
  your own Ansible configuration may differ. For a suspiciously unchanged
  report, [run a cold scan](troubleshooting.md#cached-facts) with
  `--flush-cache`.

If a finding is wrong rather than unwelcome, that is a bug --
[open an issue](https://github.com/sameeralam3127/linux-vitals/issues). If it
is a security problem, see [SECURITY.md](../.github/SECURITY.md) instead.

## Unreadable system journals

`log_errors` and `kernel_install_failures` are `unknown` with a reason when
journal access is denied, `journalctl` fails, or the host does not use systemd.
An empty successful system-journal read is clean. Without `become` or journal
group access, expect unknown findings rather than zero errors. Inspect the
reason before changing journal permissions or the requested time window.
See [the finding contract](report-guide.md#status-when-a-check-could-not-run).
