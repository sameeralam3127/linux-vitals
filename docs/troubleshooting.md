# Troubleshooting

This page is for **the tool misbehaving**. For what to do when the tool is
working and reporting a real problem -- a finding fired and you need to act on
it -- see the [Operator Runbook](runbook.md).

**`ansible-playbook sameeralam3127.linux_vitals.healthcheck` can't find the
collection.**
Confirm it's installed (`ansible-galaxy collection list | grep linux_vitals`)
or, for local development, that `.dev-collections/ansible_collections/sameeralam3127/linux_vitals`
exists and symlinks to this repo (see
[installation.md](installation.md#from-source-for-local-development)). If
your shell or CI sets `ANSIBLE_HOME`, note that it silently redirects
Ansible's *default* collections path -- an explicit `collections_path` in
`ansible.cfg` (already set in this repo) avoids that, but a custom
`ANSIBLE_CONFIG` pointing elsewhere can still shadow it.

**`reports/` is missing after a run.**
Report files are generated next to your inventory (`inventory_dir`) and are
gitignored -- run the playbook once and look there, not in the collection's
own install path.

**A `baseline` or `postcheck` run fails with "linux_vitals_maintenance_id is
required".**
Both phases need `-e linux_vitals_maintenance_id=<id>`; the id has no
sensible default because it's what correlates a baseline with its
postcheck. Reuse the exact same id for both runs.

**A `baseline` or `postcheck` run fails with "Snapshot shard '...' of
maintenance id '...' (...) was recorded with N host(s), and this run also
targets ...".**
Another run already wrote this phase's snapshots under the same
`linux_vitals_snapshot_shard`, for a set of hosts that does not include the
ones named. Nothing was written. If this run is another part of the same
fleet, give it a shard id of its own. If it is a different fleet, use a
different `linux_vitals_maintenance_id`. If that shard's hosts really
changed, delete the `.shards/<shard>.json` file the message names and run
again. Re-running some or all of a shard's own hosts is never refused.

**A run prints "WARNING: the snapshot set for maintenance id ... adds N
host(s) that were not in it".**
The same, for runs without a shard id: this run's snapshots were written,
into a set an earlier run of other hosts also wrote. If these runs are shards
of one fleet, that is fine, but give each a `linux_vitals_snapshot_shard` and
the check becomes exact. If not, the postcheck will compare hosts from both;
use a separate maintenance id.

**The dashboard shows every `postcheck` host as "New" with no comparison.**
The baseline snapshot wasn't found. Check that
`linux_vitals_snapshot_dir/<maintenance_id>/baseline/<hostname>.json`
exists (default `reports/snapshots/...`) and that the maintenance id and
`inventory_hostname` match exactly between the two runs.

**Slack / generic webhook notifications don't send.**
Confirm the matching webhook URL resolves from inventory, `group_vars`,
extra vars, or `.env` (which must be next to your inventory, not this
repo, once you're running from an installed collection). A blank/unset URL
means that channel is silently skipped, not an error.

**Email doesn't send.**
Confirm `linux_vitals_email_enabled: true`, at least one entry in
`linux_vitals_email_to`, valid SMTP settings, and that
`community.general` is installed (`ansible-galaxy collection install -r
requirements.yml`).

**`Collection community.general does not support Ansible version 2.16.x` appears.**
The installed `community.general` release requires a newer ansible-core than
your control node has. For ansible-core 2.16, install both collections with a
`community.general` constraint of `>=9.0.0,<12.0.0` as shown in the
[installation requirements](installation.md#requirements). Installing this
repository's wider-range `requirements.yml` again can select the same
incompatible release.

**A run with `--check` stops before discovery.**
`vitals_scan` does not currently support Ansible check mode. Several read-only
discovery commands are skipped by Ansible under `--check`, so continuing would
turn missing probe results into an incomplete or misleading health report. The
role therefore stops immediately with one explanatory message instead of
failing later on undefined discovery facts.

Run the scanner without `--check`. The scanner itself is read-only.
`vitals_heal` is a separate, opt-in role and remains disabled by default; do
not treat `--check` as evidence about remediation behavior.

**A tagged run skips expected output.**
Include `reporting` with your focused tags -- e.g.
`--tags discovery,kernel,reporting` -- since dashboard/JSON generation only
runs under the `reporting` tag. `include_tasks: ... apply: tags: [...]`
means most tasks inherit a broad tag automatically, but the config-loading
step is tagged `always` specifically so notification configuration still
resolves even on a narrow `--tags` run.

**Ansible writes temp-file permission errors.**
Run with writable temp paths, e.g.:

```bash
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote \
  ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck
```

**Bootloader validation shows "not available on this host".**
This is expected on hosts without GRUB (some cloud images boot via direct
kernel/EFI stub), or if none of `grubby`, `grub2-editenv`/`grub-editenv`,
`/etc/default/grub`, or a systemd-boot `loader.conf` are present/readable.
It degrades gracefully rather than failing the run -- see
[kernel-reboot-detection.md](kernel-reboot-detection.md#known-edge-cases).

**A host's reboot status shows "no distro check".**
The distro's own reboot check couldn't answer -- usually `needs-restarting`
isn't installed (`dnf install dnf-utils`), or zypper is older than 1.14.44.
That host's `reboot_required` comes from comparing the running kernel with
the latest installed one instead, and `reboot_required_source` reports
`kernel-comparison`. See
[kernel-reboot-detection.md](kernel-reboot-detection.md).

**A finding fires that you don't expect.**
See [report-guide.md#findings](report-guide.md#findings) for the exact
list of conditions and which threshold/variable controls each one.

### Cached facts

If a report seems stale, check the active configuration with `ansible
--version` and `ansible-config dump --only-changed`. The checkout caches facts
in `.facts/`, relative to `ansible.cfg`, for one hour. Your configuration or
environment may override this.

Add `--flush-cache` to your usual scan command to clear cached facts for the
inventory before gathering fresh data:

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck --flush-cache
```

This leaves report archives and baseline/postcheck snapshots intact. Run the
scan as well as reporting; reporting alone does not refresh health data.

Cache files for retired hosts can remain on disk. With no Ansible runs using
the cache, remove their files from the confirmed cache directory. Reports and
snapshots are separate and do not need to be deleted.

## Unreadable system journals

`log_errors` and `kernel_install_failures` are `unknown` with a reason when
journal access is denied, `journalctl` fails, or the host does not use systemd.
An empty successful system-journal read is clean. Without `become` or journal
group access, expect unknown findings rather than zero errors. Inspect the
reason before changing journal permissions or the requested time window.
See [the finding contract](report-guide.md#status-when-a-check-could-not-run).

## Failed logins or AppArmor reported as unknown

The failed-login check reads `/var/log/btmp`, which is `0600` or `0660
root:utmp`, so **it needs `become`**: run without it and `failed_logins` is
`unknown` with the reason `reading /var/log/btmp was denied`. It is also
`unknown` when `lastb` is not installed or `/var/log/btmp` does not exist --
the default on minimal and container images, where nothing records failed
logins at all. On Debian-family hosts, `apparmor_disabled` is `unknown` when
`aa-status` is missing or cannot read AppArmor's state. None of these is a
clean host; the [runbook](runbook.md#failed_logins----recent-failed-login-attempts)
says what to do for each reason.

## Tuning the journal scans for chatty hosts

Both journal scans are filtered on the managed host and return at most
`linux_vitals_log_max_lines` lines each (default `2000`), so a noisy journal
no longer grows what reaches the control node. What may still need tuning:

- **`log_errors` equals the cap.** The host logged at least that many entries
  at `linux_vitals_log_priority` or worse inside `linux_vitals_log_window`, and
  the count stopped there. The real number is on the host:

  ```bash
  journalctl --system --since "30 minutes ago" --priority err --no-pager | wc -l
  ```

  Raise the cap if you need the exact count, accepting up to that many lines
  per host on the control node, or shorten `linux_vitals_log_window` so the
  count covers less time.
- **A steady stream of errors you have accepted.** Set a shorter
  `linux_vitals_log_window`, or a stricter `linux_vitals_log_priority` such
  as `crit`, in that host group's `group_vars` rather than fleet-wide.
- **Errors you expected are not counted.** `log_errors` counts by journal
  priority, not by wording; `journalctl -u <unit> -o verbose` shows each
  entry's `PRIORITY`. Set `linux_vitals_log_priority: warning` to count
  warnings too. A service that writes errors to stdout or stderr without a
  syslog priority prefix is stored at `info`, and only `info` -- every entry --
  would count it, so check such a service directly, or have it prefix its
  error lines with `<3>`, which journald reads as `err` by default.
- **The kernel-failure scan is slow.** It reads the whole
  `linux_vitals_audit_log_window` (default 7 days) on the host and sends only
  the matching lines, so on a large journal it can be the slowest probe.
  Narrow the window (`24 hours ago` suits a daily scan). See
  [performance.md](performance.md#how-to-measure) for measuring per-task time.
