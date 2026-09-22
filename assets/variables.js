// Generated from the collection's role argument specs -- do not edit by hand.
// 51 variables across 4 roles.
// meta/argument_specs.yml is the authoritative source: tests/test_argument_specs.py
// fails if it disagrees with a role's defaults/main.yml.
window.LV_DATA = {
  "roles": [
    {
      "id": "vitals_scan",
      "label": "Scan",
      "blurb": "Read-only discovery. Always runs.",
      "vars": [
        {
          "name": "linux_vitals_log_window",
          "type": "str",
          "default": "30 minutes ago",
          "choices": null,
          "description": "How far back `journalctl` is scanned for `error`/`failed` lines that feed the `log_errors` count. Passed to `journalctl --since` as a single argument, so any value that option accepts works.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_audit_log_window",
          "type": "str",
          "default": "7 days ago",
          "choices": null,
          "description": "How far back `journalctl` is scanned for kernel, grub, dracut, and initramfs failure lines. Longer than `linux_vitals_log_window` because a failed kernel install is worth catching well after the fact.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_ram_warning_threshold",
          "type": "int",
          "default": 80,
          "choices": null,
          "description": "RAM used percentage at or above which `ram_status` becomes `Warning`. A warning does not fail the host on its own.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_ram_critical_threshold",
          "type": "int",
          "default": 95,
          "choices": null,
          "description": "RAM used percentage at or above which `ram_status` becomes `Critical`, which produces a finding and fails the host.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_boot_warning_threshold",
          "type": "int",
          "default": 20,
          "choices": null,
          "description": "Boot partition free percentage below which `boot_space_status` becomes `Low`, which produces a finding and fails the host. Note this is a free percentage, unlike the RAM thresholds, which are used percentages.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_severity_order",
          "type": "list",
          "default": [
            "info",
            "warning",
            "critical"
          ],
          "choices": null,
          "description": "The severity ladder, least to most severe. Used to rank a host's findings into one `severity`, and to decide which findings clear `linux_vitals_fail_on_severity`. Changing the order, rather than extending it, will confuse both.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_finding_severities",
          "type": "dict",
          "default": {
            "ram_critical": "critical",
            "journald_inactive": "critical",
            "service_manual_followup": "critical",
            "boot_space_low": "warning",
            "reboot_required": "warning",
            "kernel_not_latest": "warning",
            "bootloader_mismatch": "warning",
            "kernel_install_failures": "warning",
            "sssd_inactive": "warning",
            "time_sync_absent": "warning",
            "time_sync_inactive": "warning",
            "selinux_disabled": "warning",
            "apparmor_disabled": "warning",
            "log_errors": "info",
            "failed_logins": "info"
          },
          "choices": null,
          "description": "Maps each finding id to `info`, `warning`, or `critical`. Prefer `linux_vitals_finding_severity_overrides` for retuning a single finding; replacing this whole map means findings added in a later release have no entry and fall back to `warning`.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_finding_severity_overrides",
          "type": "dict",
          "default": {},
          "choices": null,
          "description": "Per-finding severity overrides, merged over `linux_vitals_finding_severities`. Example: `{apparmor_disabled: info, reboot_required: critical}`.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_fail_on_severity",
          "type": "str",
          "default": "info",
          "choices": [
            "info",
            "warning",
            "critical"
          ],
          "description": "The severity at which a finding makes a host `Fail`. The default `info` means any finding fails the host, which is how every release before severity existed behaved. Raising it to `warning` or `critical` is what turns severity into triage - every finding is still reported, but only ones at or above this level count against the host. This changes `final_status` and therefore the fleet health score.",
          "secret": false,
          "env": null
        }
      ]
    },
    {
      "id": "vitals_heal",
      "label": "Heal",
      "blurb": "Opt-in. One restart per enabled, failed unit.",
      "vars": [
        {
          "name": "linux_vitals_heal_enabled",
          "type": "bool",
          "default": false,
          "choices": null,
          "description": "Opt-in switch for self-healing. When `false` (the default) the role's tasks are skipped entirely and no service restarts are attempted, leaving the collection a read-only health check. When `true` the role attempts one restart per service that is both enabled at boot and in a failed state. It never enables, installs, or masks a unit, and never retries.",
          "secret": false,
          "env": null
        }
      ]
    },
    {
      "id": "vitals_certs",
      "label": "Certs",
      "blurb": "Opt-in. The only role that opens an outbound connection.",
      "vars": [
        {
          "name": "linux_vitals_certs_enabled",
          "type": "bool",
          "default": false,
          "choices": null,
          "description": "Opt-in switch. When false, the role's tasks are skipped entirely and no filesystem scan or TLS connection happens.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_warning_days",
          "type": "int",
          "default": 30,
          "choices": null,
          "description": "Days remaining at or below which a certificate produces a `warning` finding.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_critical_days",
          "type": "int",
          "default": 7,
          "choices": null,
          "description": "Days remaining at or below which a certificate produces a `critical` finding instead of a warning. An already-expired certificate is always `critical`, regardless of this value.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_fs_paths",
          "type": "list",
          "default": [
            "/etc/ssl/certs",
            "/etc/pki/tls/certs",
            "/etc/letsencrypt/live",
            "/etc/nginx/ssl",
            "/etc/httpd/conf/ssl"
          ],
          "choices": null,
          "description": "Directories and files searched on each managed host. Paths that do not exist are skipped. In a mixed fleet where only some hosts run a web server, that is the normal case rather than an error.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_file_patterns",
          "type": "list",
          "default": [
            "*.crt",
            "*.pem",
            "*.cer"
          ],
          "choices": null,
          "description": "Filename globs treated as certificates. A file matching one of these but containing no certificate - a `privkey.pem`, say - is skipped rather than reported as broken.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_max_depth",
          "type": "int",
          "default": 3,
          "choices": null,
          "description": "How far below each directory in `linux_vitals_cert_fs_paths` to descend. Two is enough for `letsencrypt/live/<domain>/cert.pem`; three leaves headroom without walking an entire `/etc/ssl` tree.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_trust_store_paths",
          "type": "list",
          "default": [
            "/etc/ssl/certs",
            "/etc/pki/tls/certs",
            "/etc/pki/ca-trust"
          ],
          "choices": null,
          "description": "Paths holding the system CA trust store. Certificates under these paths are still inspected, but only produce a finding when already expired. The bundle is hundreds of root certificates that are not yours, several of which are always near expiry, so reporting on their expiry would bury every real finding. Set to an empty list to report on everything.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_endpoints",
          "type": "list",
          "default": [],
          "choices": null,
          "description": "Live TLS endpoints to inspect, as the certificate is actually presented in the handshake. Each entry accepts `host`, `port` (default 443), and `server_name` for the SNI name when it differs from `host`. Connections are made from the managed host, so `localhost` means the service that host serves. Empty by default. Enabling the role must not start scanning the network.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_timeout",
          "type": "int",
          "default": 5,
          "choices": null,
          "description": "Seconds to wait for a TLS handshake before recording the endpoint as unreachable.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_weak_signature_algorithms",
          "type": "list",
          "default": [
            "md5",
            "sha1"
          ],
          "choices": null,
          "description": "Signature algorithms treated as weak. Matched case-insensitively as a substring, so `sha1` catches both `sha1WithRSAEncryption` and `ecdsa-with-SHA1`.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_cert_minimum_tls_version",
          "type": "str",
          "default": "TLSv1.2",
          "choices": null,
          "description": "Minimum acceptable negotiated TLS version at an endpoint. Compared as a string against what OpenSSL reports, which orders correctly for the `TLSv1.x` family.",
          "secret": false,
          "env": null
        }
      ]
    },
    {
      "id": "vitals_report",
      "label": "Report",
      "blurb": "Snapshot, compare, render, notify.",
      "vars": [
        {
          "name": "linux_vitals_phase",
          "type": "str",
          "default": "adhoc",
          "choices": [
            "adhoc",
            "baseline",
            "postcheck"
          ],
          "description": "`adhoc` is a one-shot health check with no snapshot or comparison bookkeeping. `baseline` persists a pre-maintenance snapshot; `postcheck` persists a post-maintenance snapshot and compares it against the matching baseline. Set by the shipped baseline.yml and postcheck.yml playbooks; there is normally no reason to set it by hand.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_maintenance_id",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "Correlates a baseline snapshot with its postcheck. Reuse the same value for both runs of a maintenance window. Must be non-empty when `linux_vitals_phase` is `baseline` or `postcheck`; the role asserts this at run time.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_snapshot_dir",
          "type": "str",
          "default": "{{ inventory_dir }}/reports/snapshots",
          "choices": null,
          "description": "Root directory for per-host, per-phase JSON snapshots. Anchored to `inventory_dir` rather than `playbook_dir` so it resolves inside your project when the collection is installed and invoked by FQCN.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_output_path",
          "type": "str",
          "default": "{{ inventory_dir }}/reports/linux_vitals_report.html",
          "choices": null,
          "description": "Where the self-contained HTML dashboard is written.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_json_output_path",
          "type": "str",
          "default": "{{ inventory_dir }}/reports/linux_vitals_report.json",
          "choices": null,
          "description": "Where the JSON report is written. Set to an empty string to skip JSON generation entirely.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_report_title",
          "type": "str",
          "default": "LinuxVitals Health Check Dashboard",
          "choices": null,
          "description": "Title used for the dashboard's HTML `<title>` and hero heading.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_archive_html_reports",
          "type": "bool",
          "default": true,
          "choices": null,
          "description": "Copy the HTML dashboard into `linux_vitals_report_archive_dir` with a UTC timestamp on every run.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_archive_json_reports",
          "type": "bool",
          "default": false,
          "choices": null,
          "description": "Same as `linux_vitals_archive_html_reports`, for the JSON report.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_report_archive_dir",
          "type": "str",
          "default": "{{ linux_vitals_output_path | dirname }}/archive",
          "choices": null,
          "description": "Where archived, timestamped copies of the reports are stored.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_report_retention_count",
          "type": "int",
          "default": 10,
          "choices": null,
          "description": "Keep only the newest N archived files per artefact type. Set to `0` to disable pruning and keep everything.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_archive_timestamp",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "Override the UTC timestamp used for this run's archive filenames. Exists mainly so tests can produce deterministic filenames; blank means \"now\".",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_slack_webhook_url",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "Slack incoming webhook URL. Falls back to `SLACK_WEBHOOK_URL` in the `.env` beside your inventory when blank; blank in both places skips Slack. This value is a credential -- an incoming webhook URL is the bearer token for that channel. Keep it in `.env` or a vaulted variable, never in inventory committed to git.",
          "secret": true,
          "env": "SLACK_WEBHOOK_URL"
        },
        {
          "name": "linux_vitals_slack_message_header",
          "type": "str",
          "default": "LinuxVitals Health Check",
          "choices": null,
          "description": "Heading shown at the top of the Slack message. The footer always names LinuxVitals regardless of this value, so the message stays identifiable in a busy channel when it is customised.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_slack_message_footer",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "Optional last line of the Slack message. Blank omits it.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_slack_include_host_breakdown",
          "type": "bool",
          "default": true,
          "choices": null,
          "description": "Include the per-host breakdown table in the Slack message.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_slack_max_hosts",
          "type": "int",
          "default": 20,
          "choices": null,
          "description": "Maximum number of rows in the Slack host-breakdown table. Hosts are ordered worst-first, so the cap drops the least interesting ones, and the message gains a `+ N more host(s` not shown) note whenever it applies. Clamped to 25 at render time regardless of this value. The table is a single text object and Slack caps those at 3000 characters, rejecting anything longer with a bare HTTP 400 that says nothing about the cause.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_enabled",
          "type": "bool",
          "default": false,
          "choices": null,
          "description": "Must be `true`, with at least one recipient in `linux_vitals_email_to`, for email to send.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_to",
          "type": "list",
          "default": [],
          "choices": null,
          "description": "Recipient addresses. An empty list skips email even when `linux_vitals_email_enabled` is true.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_cc",
          "type": "list",
          "default": [],
          "choices": null,
          "description": "CC addresses. An empty list omits the header entirely.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_from",
          "type": "str",
          "default": "linux-vitals@example.com",
          "choices": null,
          "description": "Envelope and header sender address. Change this -- the default is a placeholder that many SMTP servers will reject.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_host",
          "type": "str",
          "default": "localhost",
          "choices": null,
          "description": "SMTP server hostname. Falls back to `EMAIL_SMTP_HOST` in `.env` when left at the `localhost` default.",
          "secret": false,
          "env": "EMAIL_SMTP_HOST"
        },
        {
          "name": "linux_vitals_email_port",
          "type": "int",
          "default": 25,
          "choices": null,
          "description": "SMTP server port. Use `587` with `starttls` or `465` with `always` for authenticated submission.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_secure",
          "type": "str",
          "default": "never",
          "choices": [
            "never",
            "starttls",
            "try",
            "always"
          ],
          "description": "Transport security mode passed through to `community.general.mail`. `try` attempts STARTTLS and silently continues in plain text if it is unavailable, so prefer `starttls` or `always` when credentials are involved.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_email_username",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "SMTP username. Falls back to `EMAIL_SMTP_USERNAME` in `.env` when blank; blank in both places means no authentication.",
          "secret": true,
          "env": "EMAIL_SMTP_USERNAME"
        },
        {
          "name": "linux_vitals_email_password",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "SMTP password. Falls back to `EMAIL_SMTP_PASSWORD` in `.env` when blank. This value is a credential. Keep it in `.env` or a vaulted variable, never in inventory committed to git.",
          "secret": true,
          "env": "EMAIL_SMTP_PASSWORD"
        },
        {
          "name": "linux_vitals_email_subject",
          "type": "str",
          "default": "LinuxVitals Health Check Summary",
          "choices": null,
          "description": "Subject line of the summary email.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_generic_webhook_enabled",
          "type": "bool",
          "default": false,
          "choices": null,
          "description": "Must be `true`, with a non-empty URL, for the generic webhook to post.",
          "secret": false,
          "env": null
        },
        {
          "name": "linux_vitals_generic_webhook_url",
          "type": "str",
          "default": "",
          "choices": null,
          "description": "Generic webhook endpoint. Falls back to `GENERIC_WEBHOOK_URL` in `.env` when blank. Treat as a credential if the endpoint authenticates by URL. Keep it in `.env` or a vaulted variable.",
          "secret": true,
          "env": "GENERIC_WEBHOOK_URL"
        },
        {
          "name": "linux_vitals_generic_webhook_headers",
          "type": "dict",
          "default": {},
          "choices": null,
          "description": "Extra HTTP headers sent with the generic webhook request. This is the documented place for an `Authorization` header. Treat as a credential. The sending task runs with `no_log` so a failed post cannot print these.",
          "secret": true,
          "env": null
        },
        {
          "name": "linux_vitals_generic_webhook_status_code",
          "type": "int",
          "default": 200,
          "choices": null,
          "description": "HTTP status code the endpoint is expected to return. Anything else is reported as a delivery failure. Set to `202` or `204` for endpoints that acknowledge asynchronously or return no content.",
          "secret": false,
          "env": null
        }
      ]
    }
  ],
  "generated_from": "roles/*/meta/argument_specs.yml"
};
