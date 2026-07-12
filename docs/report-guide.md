# Report Guide

LinuxVitals produces three artifacts per run: an HTML dashboard, a JSON
report, and (when baseline/postcheck snapshots exist) per-host JSON
snapshots. All three live under `reports/` next to your inventory.

## HTML dashboard

`reports/linux_vitals_report.html` -- self-contained (no external CSS/JS,
no CDN), works offline, opens in any browser.

**Header.** Report title, generated timestamp, and -- for `baseline` /
`postcheck` runs -- a phase badge and the maintenance id, so you can tell
at a glance which run you're looking at.

**KPI row.** Servers checked, a health-score ring (pass-rate %, banded
Excellent ≥95% / Good ≥80% / Fair ≥60% / Poor <60%), passing/failing
counts, and auto-fixed count. On a `postcheck` run, three more tiles
appear: Improved, Regressed, New hosts (hosts with no matching baseline
snapshot).

**Toolbar.** A free-text search box (matches hostname, IP, OS, and serial
number), status filter chips (All / Pass / Fail), and -- on `postcheck`
runs -- comparison filter chips (All / Regressed / Improved / New). Expand
all / Collapse all buttons and a Print / Export PDF button (uses the
browser's native print dialog; "Save as PDF" there gives you an offline
copy).

**Host table.** One row per host, sortable by clicking any column header
(click again to reverse). Click the chevron (or the row) to expand an
inline detail panel with everything the summary row doesn't show:

- Identity (OS family, package manager, log source, virtualization type,
  serial number)
- Uptime and last reboot
- Kernel and bootloader validation (running vs. latest installed kernel,
  whether the default boot entry actually selects it)
- Security controls (SELinux/AppArmor status, failed login count and most
  recent attempt)
- Boot partition free space and rescue image availability
- Recent log errors and kernel/bootloader-related failures (with excerpts)
- Self-healing actions taken this run
- Findings -- the specific reasons a host failed, if any
- On `postcheck` runs with a baseline available: status/RAM/kernel/reboot
  before vs. after, plus new and resolved findings

**Theme.** Follows your OS light/dark preference by default; the toggle in
the top-right corner overrides it (stored via `localStorage` where
available). The print stylesheet forces a light, borderless layout
regardless of theme.

**Scaling to hundreds of hosts.** The table renders every host's row and
detail panel up front (search/filter/sort are pure client-side DOM
operations, no server round-trip), which keeps the file self-contained at
the cost of a larger HTML file for very large fleets. Search and filtering
keep the working view small even when the underlying table is large.

## JSON report

`reports/linux_vitals_report.json` -- schema `1.1`, intended for ingestion
by log shippers, SIEMs, or your own dashboards.

```json
{
  "schema_version": "1.1",
  "generated_at": "20260712T120000Z",
  "report": { "title": "...", "html_output_path": "...", "json_output_path": "..." },
  "maintenance": { "phase": "postcheck", "maintenance_id": "2026-07-12-patch-window" },
  "summary": {
    "overall_status": "PASS",
    "servers_checked": 5,
    "auto_fixed_count": 1,
    "critical_error_count": 1,
    "health_score_pct": 80.0,
    "health_score_band": "Good",
    "comparison_active": true,
    "regressed_count": 1,
    "improved_count": 1,
    "new_hosts_count": 2,
    "snippet": "5 Servers Checked, 1 Auto-Fixed, 1 Critical Error"
  },
  "hosts": [
    {
      "inventory_name": "web01",
      "hostname": "web01",
      "ip_address": "192.0.2.11",
      "status": "Pass",
      "os": { "distribution": "Ubuntu 24.04", "family": "Debian", "package_manager": "apt", "log_source": "journald" },
      "platform": { "type": "Virtual Machine", "virtualization_type": "kvm", "uptime": "12d 4h 21m", "last_reboot": "2026-06-30 08:15" },
      "kernel": { "running": "6.8.0-60-generic", "latest_installed": "6.8.0-60-generic", "latest_selected": true, "install_failures": 0, "install_failure_excerpt": [] },
      "bootloader": { "supported": true, "default_status": "resolved", "default_matches_latest": true, "validation_message": "Default boot entry selects the latest installed kernel" },
      "reboot": { "required": false },
      "security": { "selinux_status": "not-installed", "apparmor_status": "enabled", "failed_login_count": 0, "last_failed_login": "No failed login attempts found" },
      "boot_space": { "mount": "/boot", "free_pct": 65.3, "status": "Healthy", "rescue_image_available": true, "rescue_image_paths": ["..."] },
      "memory": { "status": "OK", "used_pct": 42.5, "used_mb": 3480.0, "total_mb": 8192.0 },
      "logs": { "error_count": 0, "excerpt": [] },
      "self_healing": { "services_healed": ["chronyd.service"], "healing_results": [{ "service": "chronyd.service", "result": "Fixed" }] },
      "asset_serial": "VMware-56 4d 2a",
      "comparison": {
        "baseline_available": true,
        "status_before": "Fail",
        "status_after": "Pass",
        "status_improved": true,
        "status_regressed": false,
        "ram_used_pct_delta": -45.5,
        "kernel_changed": true,
        "new_findings": [],
        "resolved_findings": ["RAM usage is critical", "System reboot is required"]
      },
      "findings": []
    }
  ]
}
```

`comparison` is always present with at least `baseline_available`; on
`adhoc`/`baseline` runs, or for a host with no matching baseline snapshot,
it's `{"baseline_available": false}` and the rest of the comparison fields
are absent.

## Findings

A host's `final_status` is `Fail` if any of these fire (see
`roles/vitals_scan/tasks/result.yml` for the exact logic):

- RAM usage at or above `linux_vitals_ram_critical_threshold`
- Recent log errors (`journalctl` matches `error`/`failed` in the log
  window)
- `sssd`, `systemd-journald`, or the resolved time-sync service isn't
  running (or no time-sync service is installed at all)
- A system reboot is required (per-distro detection: `/var/run/reboot-required`
  on Debian, `needs-restarting -r` on RedHat, `/var/run/reboot-needed` on
  SUSE)
- The running kernel isn't the latest installed one
- The default boot entry doesn't select the latest installed kernel
  (when bootloader validation is available)
- Boot partition free space is below `linux_vitals_boot_warning_threshold`
- Kernel/bootloader-related failures appear in the audit log window
- Recent failed login attempts were detected
- SELinux is disabled/unavailable on RedHat-family hosts, or AppArmor is
  disabled/unavailable on Debian-family hosts
- Any self-healing attempt didn't end in `"Fixed"`

## Generic webhook payload

Sent as a JSON POST body when `linux_vitals_generic_webhook_enabled: true`
and a URL resolves:

```json
{
  "summary": { "header": "...", "overall_status": "PASS", "servers_checked": 5, "auto_fixed_count": 1, "critical_error_count": 1, "snippet": "..." },
  "message": "<the same text sent to Slack>",
  "hosts": [
    { "hostname": "web01", "ip_address": "192.0.2.11", "status": "Pass", "platform_type": "Virtual Machine", "uptime": "12d 4h 21m", "running_kernel": "6.8.0-60-generic", "latest_kernel_selected": true, "reboot_required": false, "boot_space_status": "Healthy", "failed_login_count": 0, "findings": [] }
  ]
}
```

## Snapshots

`reports/snapshots/<maintenance_id>/<phase>/<hostname>.json` -- one file
per host per phase, written whenever `linux_vitals_phase` is `baseline` or
`postcheck`. Each file is exactly that host's `linux_vitals_result` object
at snapshot time (schema matches a single entry in the JSON report's
`hosts` array, minus the top-level `comparison` enrichment). These aren't
pruned automatically -- clean them up per your own retention policy if you
run many maintenance windows.
