# Variable Reference

Every `linux_vitals_*` variable, grouped by the role whose `defaults/main.yml`
defines it. All three roles share one flat namespace by design -- see
[architecture.md](architecture.md#why-three-roles-one-variable-namespace).
Override any of these in inventory, `group_vars`, or `-e` extra vars.

## `vitals_scan` -- thresholds and windows

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_log_window` | `"30 minutes ago"` | How far back `journalctl` is scanned for `error`/`failed` lines that feed `log_errors`. |
| `linux_vitals_audit_log_window` | `"7 days ago"` | How far back `journalctl` is scanned for kernel/grub/dracut/initramfs failure lines. |
| `linux_vitals_ram_warning_threshold` | `80` | RAM used % at or above which `ram_status` becomes `Warning`. |
| `linux_vitals_ram_critical_threshold` | `95` | RAM used % at or above which `ram_status` becomes `Critical` (and the host fails). |
| `linux_vitals_boot_warning_threshold` | `20` | Boot partition free % below which `boot_space_status` becomes `Low` (and the host fails). |

## `vitals_heal` -- self-healing

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_heal_enabled` | `false` | Opt-in switch. When `false`, `vitals_heal`'s tasks are skipped entirely -- no service restarts are attempted. |

## `vitals_report` -- maintenance workflow

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_phase` | `"adhoc"` | One of `adhoc`, `baseline`, `postcheck`. Set by `playbooks/baseline.yml` / `postcheck.yml`; `healthcheck.yml` leaves it at `adhoc`. |
| `linux_vitals_maintenance_id` | `""` | Required (non-empty) when phase is `baseline` or `postcheck`. Correlates a baseline snapshot with its postcheck. |
| `linux_vitals_snapshot_dir` | `"{{ inventory_dir }}/reports/snapshots"` | Root directory for per-host, per-phase JSON snapshots. |

## `vitals_report` -- output and archiving

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_output_path` | `"{{ inventory_dir }}/reports/linux_vitals_report.html"` | Where the HTML dashboard is written. |
| `linux_vitals_json_output_path` | `"{{ inventory_dir }}/reports/linux_vitals_report.json"` | Where the JSON report is written. Set to `""` to skip JSON generation. |
| `linux_vitals_report_title` | `"LinuxVitals Health Check Dashboard"` | Title shown in the dashboard `<title>` and hero heading. |
| `linux_vitals_archive_html_reports` | `true` | Copy the HTML dashboard into `linux_vitals_report_archive_dir` with a UTC timestamp on every run. |
| `linux_vitals_archive_json_reports` | `false` | Same, for the JSON report. |
| `linux_vitals_report_archive_dir` | `"{{ linux_vitals_output_path \| dirname }}/archive"` | Where archived, timestamped copies are stored. |
| `linux_vitals_report_retention_count` | `10` | Keep only the newest N archived HTML/JSON files (per type); `0` disables pruning. |
| `linux_vitals_archive_timestamp` | `""` | Override the UTC timestamp used for this run's archive filenames (mainly for testing); blank means "now". |

## `vitals_report` -- Slack

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_slack_webhook_url` | `""` | Slack incoming webhook URL. Falls back to `.env`'s `SLACK_WEBHOOK_URL` if blank. Empty means Slack is skipped. |
| `linux_vitals_slack_message_header` | `"Standard Maintenance Summary"` | First line of the Slack message. |
| `linux_vitals_slack_message_footer` | `""` | Optional last line of the Slack message. |
| `linux_vitals_slack_include_host_breakdown` | `true` | Include a per-host status line in the Slack message. |

## `vitals_report` -- email

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_email_enabled` | `false` | Must be `true`, with at least one recipient, for email to send. |
| `linux_vitals_email_to` | `[]` | Recipient list. |
| `linux_vitals_email_cc` | `[]` | CC list. |
| `linux_vitals_email_from` | `"linux-vitals@example.com"` | From address. |
| `linux_vitals_email_host` | `"localhost"` | SMTP host. Falls back to `.env`'s `EMAIL_SMTP_HOST` unless explicitly set to something other than `"localhost"`. |
| `linux_vitals_email_port` | `25` | SMTP port. |
| `linux_vitals_email_secure` | `"never"` | `community.general.mail`'s `secure` mode (`never`, `starttls`, `always`). |
| `linux_vitals_email_username` | `""` | SMTP username. Falls back to `.env`'s `EMAIL_SMTP_USERNAME`. |
| `linux_vitals_email_password` | `""` | SMTP password. Falls back to `.env`'s `EMAIL_SMTP_PASSWORD`. |
| `linux_vitals_email_subject` | `"LinuxVitals Health Check Summary"` | Email subject line. |

## `vitals_report` -- generic webhook

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_generic_webhook_enabled` | `false` | Must be `true`, with a resolved URL, for the webhook to send. |
| `linux_vitals_generic_webhook_url` | `""` | Webhook URL. Falls back to `.env`'s `GENERIC_WEBHOOK_URL` if blank. |
| `linux_vitals_generic_webhook_headers` | `{}` | Extra HTTP headers (e.g. `Authorization`). |
| `linux_vitals_generic_webhook_status_code` | `200` | Expected HTTP status code for a successful POST. |

## Facts computed at runtime (not overridable defaults)

These are set by role tasks, not `defaults/main.yml`, but are useful to
know when writing custom templates or downstream automation against
`linux_vitals_result` / the JSON report:

| Fact | Set by | Description |
|---|---|---|
| `linux_vitals_result` | `vitals_scan` (built), `vitals_heal` (partially updates), `vitals_report` (adds `comparison`) | The full per-host result object rendered into the dashboard/JSON. |
| `linux_vitals_summary` | `vitals_report/tasks/render.yml` | Fleet-wide rollup: `servers_checked`, `critical_error_count`, `auto_fixed_count`, `health_score_pct`, `health_score_band`, `comparison_active`, `regressed_count`, `improved_count`, `new_hosts_count`, `snippet`. |
| `linux_vitals_result.comparison` | `vitals_scan` (default `{baseline_available: false}`), `vitals_report/tasks/compare.yml` (enriched during postcheck) | Before/after comparison for this host; see [report-guide.md](report-guide.md#json-report). |

## `.env` variables (not Ansible variables)

Read from `{{ inventory_dir }}/.env` by `vitals_report/tasks/config.yml`.
See [.env.example](../.env.example).

| Key | Maps to |
|---|---|
| `SLACK_WEBHOOK_URL` | `linux_vitals_slack_webhook_url` fallback |
| `GENERIC_WEBHOOK_URL` | `linux_vitals_generic_webhook_url` fallback |
| `EMAIL_SMTP_HOST` | `linux_vitals_email_host` fallback |
| `EMAIL_SMTP_USERNAME` | `linux_vitals_email_username` fallback |
| `EMAIL_SMTP_PASSWORD` | `linux_vitals_email_password` fallback |
