# Changelog

All notable changes to the `sameeralam3127.linux_vitals` collection are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - Unreleased

### Added

- Initial release of LinuxVitals as an Ansible collection (`sameeralam3127.linux_vitals`), rebranded from the `smart_os_health_check` role-based project.
- Three composable roles: `vitals_scan` (read-only discovery and findings), `vitals_heal` (opt-in one-shot self-healing, disabled by default), and `vitals_report` (HTML/JSON dashboard, archive retention, Slack/email/generic-webhook notifications).
- `playbooks/healthcheck.yml`, runnable locally or via FQCN once installed (`sameeralam3127.linux_vitals.healthcheck`).
- Example inventory and `group_vars` under `examples/`.

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
