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
```

`linux_vitals_log_window` / `linux_vitals_audit_log_window` accept anything
`journalctl --since` understands. A host fails (`final_status: Fail`) if
RAM usage reaches the critical threshold, boot space drops below the
warning threshold, or any other finding fires (see
[report-guide.md](report-guide.md#findings) for the full list).

## Self-healing

Owned by `vitals_heal`. Off by default -- LinuxVitals never restarts a
service unless you opt in:

```yaml
linux_vitals_heal_enabled: true
```

When enabled, exactly one restart is attempted per systemd-enabled failed
service, once per run. A service that's still failed afterward is reported
as `"Failed to Fix"` and adds a finding; it is not retried.

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

## Report output and retention

```yaml
linux_vitals_output_path: "{{ inventory_dir }}/reports/linux_vitals_report.html"
linux_vitals_json_output_path: "{{ inventory_dir }}/reports/linux_vitals_report.json"
linux_vitals_report_title: "LinuxVitals Health Check Dashboard"
linux_vitals_archive_html_reports: true
linux_vitals_archive_json_reports: false
linux_vitals_report_archive_dir: "{{ linux_vitals_output_path | dirname }}/archive"
linux_vitals_report_retention_count: 10
```

- The **latest** report always overwrites `linux_vitals_output_path` /
  `linux_vitals_json_output_path`.
- Set `linux_vitals_json_output_path: ""` to skip JSON generation entirely.
- Archived copies get a UTC timestamp suffix, e.g.
  `linux_vitals_report-20260712T120000Z.html`.
- Set `linux_vitals_report_retention_count: 0` to keep every archived
  report (no pruning).

Example: keep 30 days of HTML history, skip JSON archiving:

```yaml
linux_vitals_archive_html_reports: true
linux_vitals_archive_json_reports: false
linux_vitals_report_retention_count: 30
```

## Notifications

All three channels are independent and can be combined. Each resolves in
the same order: an explicit inventory/`group_vars`/extra-vars value wins;
otherwise the matching `.env` value is used; otherwise the channel is
skipped.

### Slack

```yaml
linux_vitals_slack_message_header: "Nightly Fleet Health"
linux_vitals_slack_include_host_breakdown: true
```

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
