# Variable Reference

Every `linux_vitals_*` variable, grouped by the role whose `defaults/main.yml`
defines it. All three roles share one flat namespace by design -- see
[architecture.md](architecture.md#why-three-roles-one-variable-namespace).
Override any of these in inventory, `group_vars`, or `-e` extra vars.

## `vitals_scan` -- thresholds and windows

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_log_window` | `"30 minutes ago"` | How far back `journalctl` is scanned for entries at `linux_vitals_log_priority` or worse, which feed `log_errors`. Until [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) it matched lines containing `error` or `failed` instead. |
| `linux_vitals_audit_log_window` | `"7 days ago"` | How far back `journalctl` is scanned for kernel/grub/dracut/initramfs failure lines. They are matched on the managed host, so the whole window is read there but only matching lines reach the control node. |
| `linux_vitals_log_priority` | `err` | The journal priority `log_errors` counts, passed to `journalctl --priority`. One level means that level or worse, so `err` counts `err`, `crit`, `alert` and `emerg`. A range (`warning..emerg`) or a number (`0`-`7`) also works. Set `warning` to count warnings too. Errors a service writes to stdout/stderr without a priority prefix are stored at `info`, which only `info` (every entry) would count. |
| `linux_vitals_log_max_lines` | `2000` | The most journal lines either scan returns per host: the newest entries for `log_errors`, the newest matching lines for `kernel_install_failures`. Bounds what each host sends to the control node however large its journal is. A count equal to it means at least that many. Below `1`, both journal findings are `unknown`. |
| `linux_vitals_ram_warning_threshold` | `80` | RAM used % at or above which `ram_status` becomes `Warning`. |
| `linux_vitals_ram_critical_threshold` | `95` | RAM used % at or above which `ram_status` becomes `Critical` (and the host fails). |
| `linux_vitals_boot_warning_threshold` | `20` | Boot partition free % below which `boot_space_status` becomes `Low` (and the host fails). |
| `linux_vitals_disk_warning_threshold` | `80` | Filesystem used % at or above which `filesystem_space_low` is raised as `warning`, for every mount in scope. |
| `linux_vitals_disk_critical_threshold` | `95` | Filesystem used % at or above which `filesystem_space_low` is raised as `critical`. |
| `linux_vitals_disk_inode_warning_threshold` | `80` | Inode used % at or above which `filesystem_inodes_low` is raised as `warning`. Checked independently of space: a filesystem can have gigabytes free and still fail writes with an exhausted inode table. |
| `linux_vitals_disk_inode_critical_threshold` | `95` | Inode used % at or above which `filesystem_inodes_low` is raised as `critical`. |
| `linux_vitals_disk_exclude_fstypes` | pseudo-filesystems, `squashfs`, `nfs`/`nfs3`/`nfs4`/`cifs` -- see [defaults](../roles/vitals_scan/defaults/main.yml) | Filesystem types excluded from capacity and inode checks by default. |
| `linux_vitals_disk_include_mounts` | `[]` | Mount points checked even though their filesystem type is excluded. |
| `linux_vitals_disk_exclude_mounts` | `[]` | Mount points never checked. Wins over `linux_vitals_disk_include_mounts` for a mount named in both. |
| `linux_vitals_disk_expected_readonly_mounts` | `[]` | Mount points allowed to be read-only without raising `filesystem_read_only`. |
| `linux_vitals_load_warning_threshold` | `1.5` | 5-minute load average **per online CPU** at or above which `cpu_load_high` is raised as `warning`. `1.0` means every CPU was busy on average, which a healthy batch host reaches routinely, so the default sits above it. [#34](https://github.com/sameeralam3127/linux-vitals/issues/34) |
| `linux_vitals_load_critical_threshold` | `3.0` | 5-minute load average per online CPU at or above which `cpu_load_high` is raised as `critical`. |
| `linux_vitals_psi_warning_threshold` | `25` | Pressure stall % (PSI `some avg60`: the share of the last minute in which at least one task waited) at or above which `pressure_stall_high` is raised as `warning` for that resource: CPU, memory or I/O. PSI needs kernel 4.20+ with PSI enabled; elsewhere it is reported as unsupported and raises nothing. |
| `linux_vitals_psi_critical_threshold` | `50` | Pressure stall % at or above which `pressure_stall_high` is raised as `critical`. |
| `linux_vitals_swap_rate_warning_threshold` | `100` | Pages swapped in plus out per second, over the sample below, at or above which `swap_paging_high` is raised as `warning`. |
| `linux_vitals_swap_rate_critical_threshold` | `1000` | Pages swapped per second at or above which `swap_paging_high` is raised as `critical`. |
| `linux_vitals_swap_sample_seconds` | `2` | Seconds between the two `/proc/vmstat` reads the swap rate is measured over. Every host waits this long once per scan. `0` skips the measurement and `swap_paging_high`; values above `60` are treated as `60`. |
| `linux_vitals_fail_on_severity` | `info` | Severity at or above which a finding fails the host. `info` means any finding fails it, which is the pre-severity behaviour. Raise to `warning`/`critical` to triage. Also moves the fleet health score. |
| `linux_vitals_finding_severity_overrides` | `{}` | Per-finding severity overrides, merged over the shipped map. E.g. `{apparmor_disabled: info}`. |
| `linux_vitals_finding_severities` | see [defaults](../roles/vitals_scan/defaults/main.yml) | The shipped finding-id to severity map. Prefer the overrides variable above; replacing this map means findings added later fall back to `warning`. |
| `linux_vitals_severity_order` | `[info, warning, critical]` | The severity ladder, least to most severe. Extend rather than reorder. |

## `vitals_heal` -- self-healing

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_heal_enabled` | `false` | Opt-in switch. When `false`, `vitals_heal`'s tasks are skipped entirely -- no service restarts are attempted. |
| `linux_vitals_heal_settle_retries` | `10` | After the restarts, how many more times a unit still activating, deactivating or reloading is polled with `systemctl show` before the role stops waiting. A unit that has not settled by then is reported `Manual Intervention Required` with outcome `unknown`, never `Fixed`. |
| `linux_vitals_heal_settle_delay` | `3` | Seconds between those polls. With the retries above, a unit that has not settled is waited on for up to 30 s. A unit that has already settled costs one poll. |
| `linux_vitals_heal_stability_seconds` | `5` | How long a restarted unit that came up must stay active, on the same run, to be reported `Fixed`. A unit that fails or is restarted by systemd inside the window is `Failed to Fix`. Waited out once per host, and only on hosts where a restarted unit came up. A unit that dies later than this is still reported `Fixed`. |

## `vitals_certs` -- TLS certificate checks (opt-in)

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_certs_enabled` | `false` | Opt-in switch. When `false` the role's tasks are skipped entirely -- no filesystem scan, no TLS connection. |
| `linux_vitals_cert_warning_days` | `30` | Days remaining at or below which a certificate produces a `warning` finding. |
| `linux_vitals_cert_critical_days` | `7` | Days remaining at or below which it produces `critical` instead. An already-expired certificate is always `critical`. |
| `linux_vitals_cert_fs_paths` | see [defaults](../roles/vitals_certs/defaults/main.yml) | Directories and files searched on each host. Missing paths are skipped. |
| `linux_vitals_cert_file_patterns` | `["*.crt", "*.pem", "*.cer"]` | Filename globs treated as certificates. A matching file holding no certificate (a `privkey.pem`) is skipped, not reported as broken. |
| `linux_vitals_cert_max_depth` | `3` | How far below each directory to descend. `2` covers `letsencrypt/live/<domain>/cert.pem`. |
| `linux_vitals_cert_trust_store_paths` | `[/etc/ssl/certs, /etc/pki/tls/certs, /etc/pki/ca-trust]` | Still scanned, but only report when already expired. The system CA bundle is hundreds of certificates that are not yours; reporting their expiry would bury every real finding. Set to `[]` to report on everything. |
| `linux_vitals_cert_endpoints` | `[]` | Live TLS endpoints, as `{host, port, server_name}`. Connections are made **from the managed host**, so `localhost` means what that host serves. Empty by default -- enabling the role must not start scanning the network. |
| `linux_vitals_cert_timeout` | `5` | Seconds to wait for a handshake before recording the endpoint as unreachable. |
| `linux_vitals_cert_weak_signature_algorithms` | `[md5, sha1]` | Matched case-insensitively as a substring, so `sha1` catches `ecdsa-with-SHA1`. |
| `linux_vitals_cert_minimum_tls_version` | `"TLSv1.2"` | Minimum acceptable negotiated version at an endpoint. |

## `vitals_report` -- maintenance workflow

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_phase` | `"adhoc"` | One of `adhoc`, `baseline`, `postcheck`. Set by `playbooks/baseline.yml` / `postcheck.yml`; `healthcheck.yml` leaves it at `adhoc`. |
| `linux_vitals_maintenance_id` | `""` | Required (non-empty) when phase is `baseline` or `postcheck`. Correlates a baseline snapshot with its postcheck. |
| `linux_vitals_snapshot_dir` | `"{{ inventory_dir }}/reports/snapshots"` | Root directory for per-host, per-phase JSON snapshots. |
| `linux_vitals_snapshot_shard` | `""` | Names this run's part of a snapshot set shared by several runs of one maintenance id (a [sharded fleet](performance.md#sharding-a-large-fleet)). Each run records its hosts in `<maintenance_id>/<phase>/.shards/<shard>.json`; a run that reuses a shard id for hosts it was not recorded with fails before writing any snapshot. Re-running all or some of a shard's hosts is allowed. Empty records the run as shard `default` and only warns on a different host set. Letters, digits, `.`, `_`, `-`, starting with a letter or digit. |
| `linux_vitals_fail_on_status` | `""` | Optional final pipeline gate. Empty never fails the run; `any_fail` fails when failed hosts exceed the threshold; `regression` considers only Pass → Fail hosts during a `postcheck`. Reports and notifications are produced before the gate runs. |
| `linux_vitals_fail_threshold_count` | `0` | Number of failed/regressed hosts tolerated before the optional fleet gate returns non-zero. |

## `vitals_report` -- output and archiving

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_output_path` | `"{{ inventory_dir }}/reports/linux_vitals_report.html"` | Where the HTML dashboard is written. |
| `linux_vitals_report_file_mode` | `"0644"` | Mode for generated HTML/JSON reports, archives, and per-host snapshots. Use `"0600"` to restrict reading to the automation user. |
| `linux_vitals_report_dir_mode` | `"0755"` | Mode for report, archive, and snapshot directories created by the role. Use `"0700"` to restrict traversal to the automation user. |
| `linux_vitals_json_output_path` | `"{{ inventory_dir }}/reports/linux_vitals_report.json"` | Where the JSON report is written. Set to `""` to skip JSON generation. |
| `linux_vitals_report_title` | `"LinuxVitals Health Check Dashboard"` | Title shown in the dashboard `<title>` and hero heading. |
| `linux_vitals_archive_html_reports` | `true` | Copy the HTML dashboard into `linux_vitals_report_archive_dir` with a UTC timestamp on every run. |
| `linux_vitals_archive_json_reports` | `false` | Same, for the JSON report. |
| `linux_vitals_report_archive_dir` | `"{{ linux_vitals_output_path \| dirname }}/archive"` | Where archived, timestamped copies are stored. |
| `linux_vitals_report_retention_count` | `10` | Keep only the newest N archived HTML/JSON files (per type) of this report; `0` disables pruning. Archives of other reports in the same directory are never counted or pruned. |
| `linux_vitals_archive_timestamp` | `""` | Override the UTC timestamp used for this run's archive filenames (mainly for testing); blank means "now". Pruning matches archives whose timestamp has the same shape, digits where this one has digits, so keep one format. |

## `vitals_report` -- Slack

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_slack_webhook_url` | `""` | Slack incoming webhook URL. Falls back to `.env`'s `SLACK_WEBHOOK_URL` if blank. Empty means Slack is skipped. |
| `linux_vitals_slack_message_header` | `"LinuxVitals Health Check"` | Heading at the top of the Slack message. The footer names LinuxVitals regardless, so the message stays identifiable when this is customised. |
| `linux_vitals_slack_message_footer` | `""` | Optional last line of the Slack message. |
| `linux_vitals_slack_include_host_breakdown` | `true` | Include the per-host breakdown table in the Slack message. |
| `linux_vitals_slack_max_hosts` | `20` | Maximum rows in the Slack host-breakdown table. Hosts are ordered worst-first, so the cap drops the least interesting ones and the message gains a `+ N more host(s) not shown` note. Clamped to 25 at render time: the table is one text object and Slack caps those at 3000 characters. |

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
