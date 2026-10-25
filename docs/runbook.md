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

### `firewall_inactive` -- no active firewall was detected

**Means:** none of `firewalld`, `ufw`, `nftables` or `iptables` reported an
active, non-empty ruleset. `firewall.source` says which tool answered (or
`none`); `firewall.detail` has the raw answer. `status: unknown` means a
tool was present but could not be asked -- usually a permission error, not
"no firewall" -- check `firewall.detail` for the reason before assuming the
host is exposed.

**Confirm:**
```bash
firewall-cmd --state                  # RHEL family
ufw status verbose                    # Debian family
nft list ruleset; iptables -S         # generic fallback
```

**Do:** if the host is genuinely behind a cloud security group or an
upstream firewall and runs none locally by design, record that rather than
living with a permanent finding:
```yaml
linux_vitals_finding_severity_overrides:
  firewall_inactive: info
```
Otherwise enable and configure the distro's firewall tool before the next
scan.

### `ssh_permit_empty_passwords_enabled` -- sshd allows empty passwords

**Means:** `sshd -T` reports `PermitEmptyPasswords yes` -- an account with no
password set can log in over SSH. There is no legitimate reason for this on
a reachable host.

**Confirm:**
```bash
sshd -T | grep -i permitemptypasswords
awk -F: '($2 == "") {print $1}' /etc/shadow
```

**Do:** set `PermitEmptyPasswords no` (the OpenSSH default) and reload
`sshd`. Then fix any account the second command lists -- a password-less
account is the actual exposure; the setting only controls whether SSH will
use it.

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

### `ssh_permit_root_login_insecure` -- sshd allows root login

**Means:** `sshd -T` reports `PermitRootLogin` is something other than `no`,
`prohibit-password`, or `without-password`. `status: unknown` when the
effective config could not be read -- see [SSH below](#sshd--t-could-not-run).

**Confirm:**
```bash
sshd -T | grep -i permitrootlogin
```

**Do:** set `PermitRootLogin prohibit-password` (key-based root login,
no password) or `no`, and reload `sshd`. If a host genuinely needs
password-based root login (a rescue console, say), record the decision:
```yaml
linux_vitals_finding_severity_overrides:
  ssh_permit_root_login_insecure: info
```

### `ssh_password_authentication_enabled` -- sshd allows password authentication

**Means:** `sshd -T` reports `PasswordAuthentication yes`. Many fleets run
this intentionally (break-glass access, non-key-based onboarding), so it is
a `warning`, not an assumed misconfiguration -- see
[#8](https://github.com/sameeralam3127/linux-vitals/issues/8).

**Confirm:**
```bash
sshd -T | grep -i passwordauthentication
```

**Do:** if key-based auth is the intended posture, set
`PasswordAuthentication no` and reload `sshd`. If password auth is
deliberate, override the severity rather than living with a permanent
warning:
```yaml
linux_vitals_finding_severity_overrides:
  ssh_password_authentication_enabled: info
```

#### `sshd -T` could not run

Both SSH findings go `unknown` together when `sshd -T` could not be read:
`sshd` is not installed (the host may be managed over something other than
OpenSSH), or the command failed -- most commonly because `become` is not
available. `sshd -T` typically needs root to read the host key material it
touches; see [docs/threat-model.md](threat-model.md#become--what-actually-needs-it).
`ssh_hardening.detection_supported` is `false` and `source` says which case
it was.

### `kernel_tainted` -- the kernel is tainted

**Means:** `/proc/sys/kernel/tainted` is non-zero. `kernel_taint.reasons`
decodes the bits the collection recognises (proprietary module loaded, a
module force-loaded or force-unloaded, an out-of-tree module, a live patch,
a prior OOPS/BUG, and others); an empty list with a non-zero value means a
bit this collection does not yet decode is set.

**Confirm:**
```bash
cat /proc/sys/kernel/tainted
dmesg | grep -i taint
lsmod | grep -v '^Module'   # look for out-of-tree / unsigned modules
```

**Do:** a proprietary or out-of-tree module (GPU, RAID, or virtualization
drivers are common culprits) is often expected on a given host class --
record that rather than living with a permanent finding. A taint from a
live OOPS, BUG, or soft lockup is worth investigating: check `dmesg` and the
journal around the time it was set. A reboot clears the flag; it does not
address whatever set it.

### `reboot_blocking_deleted_libs` -- a process is holding a deleted library open

**Means:** after a package update, a running process still has a file
handle open on a shared library (`.so`) that has since been deleted from
disk -- the classic "needs a restart, not just a reboot" state. Distinct
from `reboot_required`: this can fire without a pending kernel update, and
clears as soon as the process restarts. `reboot_blocking_processes.processes`
lists each as `{pid, name}` (never the full command line). `status: unknown`
means `lsof` is not installed.

**Confirm:**
```bash
lsof +L1 | awk 'NR==1 || $NF ~ /\.so(\.[0-9]+)*$/'
```

**Do:** restart the named process (a service restart is usually enough; a
full host reboot is not required just for this). If the list includes a
core system daemon, treat it with the same care as any other service
restart -- check what depends on it first.

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
