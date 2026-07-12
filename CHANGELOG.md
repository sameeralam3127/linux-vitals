# Changelog

All notable changes to the `sameeralam3127.linux_vitals` collection are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - Unreleased

### Added

- Initial release of LinuxVitals as an Ansible collection (`sameeralam3127.linux_vitals`), rebranded from the `smart_os_health_check` role-based project.
- Three composable roles: `vitals_scan` (read-only discovery and findings), `vitals_heal` (opt-in one-shot self-healing, disabled by default), and `vitals_report` (HTML/JSON dashboard, archive retention, Slack/email/generic-webhook notifications).
- `playbooks/healthcheck.yml`, runnable locally or via FQCN once installed (`sameeralam3127.linux_vitals.healthcheck`).
- Example inventory and `group_vars` under `examples/`.
- Baseline/postcheck maintenance workflow: `playbooks/baseline.yml` and `playbooks/postcheck.yml` snapshot each host's result under a shared `linux_vitals_maintenance_id` and automatically compute a before/after comparison (status change, RAM delta, kernel change, reboot-required change, new/resolved findings) for the postcheck run.
- Redesigned, self-contained HTML dashboard: executive KPI row with a health-score ring (pass-rate band: Excellent/Good/Fair/Poor), a searchable and sortable host table with expandable per-host detail rows, status/comparison filter chips, light/dark themes (OS-aware plus a manual toggle), a print/export stylesheet, and a per-host serial number field as a first piece of asset-level drilldown data.
- JSON report (schema 1.1) now includes maintenance phase/id, health-score and comparison rollups, and each host's `asset_serial` and `comparison` object.
- Full documentation suite under `docs/` (installation, quickstart, configuration reference, variable reference, report guide, examples, troubleshooting, architecture) plus `CONTRIBUTING.md`.
- `examples/playbooks/custom-thresholds.yml`, a working example of overriding thresholds and enabling self-healing for a single run.

### Packaging

- Excluded `tests/`, `pytest.ini`, and `requirements.yml` from the published tarball via `galaxy.yml`'s `build_ignore` -- they're dev/CI-only; `galaxy.yml`'s own `dependencies:` block is what Galaxy uses to resolve `community.general` for installed-collection consumers.
- Verified end-to-end: built the tarball with `ansible-galaxy collection build`, installed it into an isolated collections path, and confirmed all three playbooks resolve and execute via FQCN (`sameeralam3127.linux_vitals.healthcheck` / `.baseline` / `.postcheck`) from that installed artifact, independent of the dev symlink.

### Changed

- All `smart_os_health_check_*` variables, facts, templates, and default report filenames renamed to the `linux_vitals_*` / `linux_vitals_report.*` convention.
- Report output path and the `.env` secrets loader now resolve relative to `inventory_dir` instead of `playbook_dir`, so both local development and installed-collection usage read/write files in the operator's own project rather than inside the installed package.

### Fixed

- Removed a byte-identical duplicate bootloader-detection task that ran the grub probe twice per host.
- Replaced a gawk-only bootloader parser with a portable POSIX `sh` implementation (bash/dash/system `sh` verified) and added numeric `GRUB_DEFAULT` index resolution.
- Stopped counting `lastb`'s trailing `btmp begins ...` footer line as a failed login attempt.
- Fixed a Jinja filter-precedence bug where `* 100 | round(1)` rounded the literal `100` instead of the computed percentage.
- HTML-escaped journal/`lastb`-derived free text in the dashboard template.
- Added `no_log: true` to the tasks that load webhook/SMTP secrets from `.env`.

### Security

- Removed real lab IP addresses previously committed in `inventory/hosts.ini` and `inventory/multipass-10.ini`; replaced with RFC 5737 documentation-range examples under `examples/inventory/`.
