# Configuration Reference

This groups configuration by what it controls rather than by variable name
(see [variable-reference.md](variable-reference.md) for the flat list).
Precedence for every setting follows standard Ansible rules: extra vars
(`-e`) > inventory/`group_vars` > role defaults.

## Health thresholds

Owned by `vitals_scan`. Override in `group_vars/all.yml`:

```yaml
linux_vitals_ram_warning_threshold: 80
linux_vitals_ram_critical_threshold: 95
linux_vitals_boot_warning_threshold: 20
linux_vitals_log_window: "30 minutes ago"
linux_vitals_audit_log_window: "7 days ago"
linux_vitals_log_priority: err
linux_vitals_log_max_lines: 2000
```

`linux_vitals_log_window` / `linux_vitals_audit_log_window` accept anything
`journalctl --since` understands. `log_errors` counts entries at
`linux_vitals_log_priority` or worse, and each journal scan returns at most
`linux_vitals_log_max_lines` lines per host (see
[tuning the journal scans](troubleshooting.md#tuning-the-journal-scans-for-chatty-hosts)).
A host fails (`final_status: Fail`) if RAM usage reaches the critical
threshold, boot space drops below the warning threshold, or any other finding
fires (see [report-guide.md](report-guide.md#findings) for the full list).

## Self-healing

Owned by `vitals_heal`. Off by default -- LinuxVitals never restarts a
service unless you opt in:

```yaml
linux_vitals_heal_enabled: true
```

When enabled, exactly one restart is attempted per systemd-enabled failed
service, once per run. A service that's still failed afterward is reported
as `"Failed to Fix"` and adds a finding; it is not retried.

A restart is only reported `"Fixed"` once it has held. Each restarted unit is
polled until it is active, failed or inactive, and a unit that came up must
still be active on the same run after a stability window. One that dies or is
restarted by systemd in that window is `"Failed to Fix"`. One still starting
when the polling budget runs out is `"Manual Intervention Required"` with an
`unknown` finding, because nobody could tell. The budget is configurable:

```yaml
linux_vitals_heal_settle_retries: 10      # extra polls while a unit is still changing state
linux_vitals_heal_settle_delay: 3         # seconds between polls (30 s in total by default)
linux_vitals_heal_stability_seconds: 5    # how long a unit must stay up to count as fixed
```

Hosts where nothing was restarted pay none of this. Raise
`linux_vitals_heal_stability_seconds` for services known to fail some time
after starting; raise the settle budget for units that take longer than 30 s
to leave `activating` after a restart.

## Maintenance workflow

Owned by `vitals_report`, set via `-e` rather than `group_vars` (a
maintenance id is a per-run value, not a fleet-wide default):

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
  -e linux_vitals_maintenance_id=2026-07-12-patch-window
```

`linux_vitals_snapshot_dir` (default `{{ inventory_dir }}/reports/snapshots`)
controls where snapshots live if you want them somewhere other than next to
your other reports.

A fleet too large for one run is split into several runs that share the
maintenance id. Give each its own `-e linux_vitals_snapshot_shard=<name>`, so
that a shard id reused for other hosts is refused rather than merged; see
[Sharding a large fleet](performance.md#sharding-a-large-fleet).

## Report output and retention

```yaml
linux_vitals_output_path: "{{ inventory_dir }}/reports/linux_vitals_report.html"
linux_vitals_json_output_path: "{{ inventory_dir }}/reports/linux_vitals_report.json"
linux_vitals_metrics_output_path: ""  # Optional .prom textfile on the controller
linux_vitals_csv_output_path: ""      # Optional fleet CSV on the controller
linux_vitals_report_file_mode: "0644"
linux_vitals_report_dir_mode: "0755"
linux_vitals_report_title: "LinuxVitals Health Check Dashboard"
linux_vitals_archive_html_reports: true
linux_vitals_archive_json_reports: false
linux_vitals_report_archive_dir: "{{ linux_vitals_output_path | dirname }}/archive"
linux_vitals_report_retention_count: 10
```

- The **latest** report always overwrites `linux_vitals_output_path` /
  `linux_vitals_json_output_path`.
- Set `linux_vitals_json_output_path: ""` to skip JSON generation entirely.
- Set `linux_vitals_report_file_mode: "0600"` and
  `linux_vitals_report_dir_mode: "0700"` to keep reports, archives, and
  snapshots private to the automation user on a shared control node.
- Archived copies get a UTC timestamp suffix, e.g.
  `linux_vitals_report-20260712T120000Z.html`. Retention counts and prunes
  only the report's own archives, so several reports with different output
  paths can share one archive directory.
- Set `linux_vitals_report_retention_count: 0` to keep every archived
  report (no pruning).

Example: keep 30 days of HTML history, skip JSON archiving:

```yaml
linux_vitals_archive_html_reports: true
linux_vitals_archive_json_reports: false
linux_vitals_report_retention_count: 30
```

### Optional metrics and CSV destinations

Set either path to enable that export; both are off by default:

```yaml
linux_vitals_metrics_output_path: "/var/lib/node_exporter/textfile_collector/linux_vitals.prom"
linux_vitals_csv_output_path: "{{ inventory_dir }}/reports/linux_vitals_report.csv"
```

These are controller-side writes from the already collected report results,
with the configured report file/directory modes; there is no new discovery or
HTTP endpoint. Choose separate metrics, CSV, HTML and JSON paths, and separate
paths for concurrent runs. Metrics also require unique host identities.
Exports overwrite their files, without the HTML/JSON archive retention policy.
Setting a path back to `""` skips future writes but does not delete the old
file; remove obsolete exports explicitly, especially textfiles that would
otherwise keep being scraped. The [report guide](report-guide.md#optional-prometheus-textfile-and-csv-exports)
has a node_exporter scrape example, metric/CSV semantics and a file-age check.

## Notifications

All three channels are independent and can be combined. Each resolves in
the same order: an explicit inventory/`group_vars`/extra-vars value wins;
otherwise the matching `.env` value is used; otherwise the channel is
skipped.

**Webhook URLs are credentials.** A Slack incoming-webhook URL is all anyone
needs to post to that channel, and `linux_vitals_generic_webhook_headers` is
where an `Authorization` header goes. Keep both out of anything committed to
git -- use `.env` next to your inventory, or a vaulted variable.

The sending tasks run with `no_log`, so a failed notification reports the
channel and the HTTP status without printing the URL, the headers, or the
response. That means a failure looks like this:

```text
TASK [Fail when the Slack notification did not arrive] ***
[ERROR]: Task failed: Action failed: Slack notification failed: HTTP status -1
(the endpoint could not be reached). The webhook URL is withheld from this
message because it is a credential.
```

To debug the URL itself, exercise it by hand (`curl -X POST ...`) rather than
re-running with `-v`, which will not reveal it either.

### Slack

```yaml
linux_vitals_slack_message_header: "Nightly Fleet Health"
linux_vitals_slack_include_host_breakdown: true
linux_vitals_slack_max_hosts: 20
```

The summary is sent as [Block Kit](https://api.slack.com/block-kit): a colour
bar (green, amber, or red), a header, the counters in two columns, and the
per-host detail as a fixed-width table rather than one `|`-joined line per
host. See [report-guide.md](report-guide.md#the-slack-message) for the shape.

On a large fleet, `linux_vitals_slack_max_hosts` is the setting that matters.
Hosts are ordered worst-first, so the cap drops the hosts with nothing wrong
and the message ends with `+ N more host(s) not shown`. Leaving the breakdown
on for a 500-host fleet is fine; it is capped either way. Set
`linux_vitals_slack_include_host_breakdown: false` to drop per-host detail
entirely and keep only the counters.

```dotenv
# .env, next to your inventory
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/your/team/webhook"
```

### Generic webhook

Useful for piping into an internal ChatOps bot, SIEM, or automation
platform. The payload is documented in
[report-guide.md](report-guide.md#generic-webhook-payload).

```yaml
linux_vitals_generic_webhook_enabled: true
linux_vitals_generic_webhook_headers:
  Authorization: "Bearer {{ lookup('ansible.builtin.env', 'WEBHOOK_TOKEN') }}"
```

```dotenv
GENERIC_WEBHOOK_URL="https://example.com/health-events"
```

### Email

```yaml
linux_vitals_email_enabled: true
linux_vitals_email_to:
  - "ops@example.com"
linux_vitals_email_port: 587
linux_vitals_email_secure: "starttls"
```

```dotenv
EMAIL_SMTP_HOST="smtp.example.com"
EMAIL_SMTP_USERNAME="smtp-user"
EMAIL_SMTP_PASSWORD="smtp-password"
```

Email requires `community.general` (`ansible-galaxy collection install -r
requirements.yml`).

## `.env` file

`vitals_report` reads `{{ inventory_dir }}/.env` -- next to your
inventory, not inside this collection -- if present. See
[.env.example](../.env.example). Values here are only used as a fallback
when the matching Ansible variable is unset; they never override an
explicit inventory/`group_vars`/extra-vars value. `.env` is read with
`no_log: true`, so its contents never appear in verbose task output.
