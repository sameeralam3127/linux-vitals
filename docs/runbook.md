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
state, and it did not come back. The `subject` field names the unit.

**Confirm:**
```bash
systemctl status <unit>
journalctl -u <unit> --since "1 hour ago" --no-pager
systemctl list-dependencies --failed <unit>
```

**Do:** a unit that fails a clean restart has a real cause -- a config it
cannot parse, a port already bound, a dependency that is itself down, a
filesystem it cannot write. Read the journal from the restart attempt forward.

**Note the known race** ([#24](https://github.com/sameeralam3127/linux-vitals/issues/24)):
`service_facts` can be read before a restarted unit has settled, so a service
that died again immediately may be reported `Fixed` rather than appearing here.
If a service is misbehaving but the report says it was fixed, trust
`systemctl`, not the report.

### `cert_expired` -- a certificate has already expired

See [Certificate findings](#certificate-findings).

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

### `kernel_install_failures`

**Means:** kernel, GRUB, dracut, or initramfs failures appeared in the audit
log window (default 7 days). Often paired with `boot_space_low` -- a failed
kernel install is usually a full `/boot`.

**Confirm:**
```bash
journalctl --since "7 days ago" | grep -iE "dracut|initramfs|grub|kernel"
```

**Do:** re-run the failed transaction after fixing the cause, and **verify the
bootloader entry afterwards**. A partially installed kernel that is listed in
GRUB but has no initramfs will not boot.

## Informational findings

### `log_errors` -- recent logs contain error entries

**Means:** `journalctl` matched `error`/`failed` in the log window. Healthy
hosts do this routinely, which is why it is `info`.

**Do:** read the excerpt in the dashboard before acting. Escalate only if the
count is anomalous for the host, or if the excerpt names a service you care
about. A sudden fleet-wide jump is worth investigating; a steady background
count is not.

**Watch for a false positive:** Ansible logs its own module invocations to the
journal, and lines like `argv=['systemctl', 'is-failed', ...]` match the error
filter. If this finding appears on hosts you have just run automation against,
set `no_target_syslog = True` in your `ansible.cfg`.

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
- **A service reported `Fixed` may have died again immediately**
  ([#24](https://github.com/sameeralam3127/linux-vitals/issues/24)). Trust
  `systemctl`.
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
