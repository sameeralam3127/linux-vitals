# Changelog

All notable changes to the `sameeralam3127.linux_vitals` collection are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- **The comparison's RAM fields were strings on ansible-core 2.16.**
  `comparison.ram_used_pct_before`, `ram_used_pct_after`, and
  `ram_used_pct_delta` reached `report.json` as `"91.0"` on 2.16 -- the
  declared floor -- and as `91.0` on newer cores, so a consumer doing
  arithmetic on the delta got a different type depending on who ran the
  playbook ([#81](https://github.com/sameeralam3127/linux-vitals/issues/81)).
  They are now numbers on every core. The test asserts the type as well as the
  value, because on a newer core the value alone would pass either way.

- **The generic webhook never sent on ansible-core 2.16**, the declared floor,
  in any release since 1.0.0
  ([#85](https://github.com/sameeralam3127/linux-vitals/issues/85)). On 2.16
  the template lookup turns JSON-looking output into a dict before
  `from_json` sees it, and `from_json` raised on the dict. The error happened
  while templating the arguments of a `no_log` task, so the operator saw only
  `"censored"` and never the actionable "Generic webhook notification failed"
  message. The payload is now parsed only when the lookup returns a string,
  and is rendered in its own task outside `no_log` -- as the Slack payload
  already was -- so a template error is visible. The URL and headers, which
  are the credentials, stay masked. The Slack Block Kit payload used the same
  pattern and gets the same fix; it only worked on 2.16 by accident of its
  content.

  `tests/test_core216_compat.py` now rejects a template lookup piped straight
  into `from_json`, since a runtime test passes on any newer core.

## [2.0.0] - 2026-09-24

**Breaking for anything that reads the JSON report, the generic webhook
payload, or the `linux_vitals_result` host fact.** Findings changed from
strings to `{id, message, severity}` objects (see *Changed*), which is why
this is a major release rather than 1.4.0. Before upgrading:

- Update any consumer of `findings`, `comparison.new_findings`, or
  `comparison.resolved_findings` to key on `(.id, .subject)` -- stable, and
  unique within a host -- and to treat `.message` as display text only.
  `schema_version` is now `2.0`, so a consumer can branch on it.
- A maintenance window can span the upgrade: a baseline taken on 1.x is
  translated to 2.0 ids, so a finding that persists through the window is
  reported as neither new nor resolved.
- The pass/fail outcome of a run is unchanged: `linux_vitals_fail_on_severity`
  defaults to `info`, the behaviour of every earlier release.
- The Slack message is restructured and its default header changed (see
  *Added*). Set `linux_vitals_slack_message_header` to keep the old one.

A `requirements.yml` pin of `<2.0.0` keeps you on 1.3.1 until the consumers
are updated.

### Added

- **The Slack summary is now Block Kit, not one plain-text blob**
  ([#52](https://github.com/sameeralam3127/linux-vitals/issues/52)). The
  message gains a colour bar (green / amber / red), a header, the counters in
  two columns, and one block per host with labelled fields -- replacing the
  run-on line of nine `|`-separated fields that soft-wrapped into a paragraph
  at exactly the moment there was most to read. `FAIL` no longer has the same
  visual weight as `Uptime`.

  New `linux_vitals_slack_max_hosts` (default `20`) caps the table rows.
  Hosts are ordered worst-first -- critical, warning, info, then the rest --
  so the cap drops the hosts with nothing wrong, and the message ends with
  `+ N more host(s) not shown`. This fixes a real failure rather than tidying
  output: the old template looped over every host uncapped, so a fleet of
  roughly 175+ produced a message past Slack's 40,000-character limit, and
  Slack refused it with a bare HTTP 400 that `no_log` made almost impossible
  to diagnose.

  The per-host detail is a fixed-width table in a code block. Slack has no
  table primitive, and a code block is the only way to get columns that line
  up. It is also one block rather than one per host, so the block count no
  longer grows with the fleet.

  The top-level `text` field carries a single short line
  (`LinuxVitals: FAIL — 3 host(s) checked, 1 critical, 0 auto-fixed`), which
  doubles as the mobile push preview. It is **not** the full plain-text
  summary: Slack renders that field *above* the attachment, so sending the
  whole summary there printed the old-style message above the new card.
  `slack_message.txt.j2` is unchanged and still carried by the email body and
  the generic webhook's `message` field.

  `linux_vitals_slack_message_header` now defaults to
  `LinuxVitals Health Check` instead of `Standard Maintenance Summary`, and a
  footer naming LinuxVitals is always present so a customised header does not
  make the message unidentifiable in a busy channel.

- **An operator runbook** ([#6](https://github.com/sameeralam3127/linux-vitals/issues/6)),
  at [docs/runbook.md](docs/runbook.md). One section per finding -- what it
  actually means, the commands to confirm it independently, and what to do --
  plus procedures for a maintenance window, a fleet-wide alert, onboarding a
  host, and enabling self-healing safely. It closes with what LinuxVitals gets
  wrong, and where, so nobody chases a phantom: a host missing from a report
  is not a passing host, an absent `failed_logins` finding is not evidence of
  no failed logins, and a service reported `Fixed` may have died again.

  Written against finding ids rather than message text, so rewording a finding
  does not silently invalidate the runbook.


- **`vitals_certs`: TLS certificate expiry and hardening checks**
  ([#15](https://github.com/sameeralam3127/linux-vitals/issues/15)). A fourth,
  opt-in role (`linux_vitals_certs_enabled: false` by default) that reads
  certificates from the filesystem and, optionally, from live TLS endpoints,
  and reports expiry, weak signature algorithms, self-signed served
  certificates, obsolete negotiated TLS versions, and served-versus-on-disk
  mismatches.

  It emits the same `{id, message, severity}` finding shape `vitals_scan`
  produces, so the dashboard, JSON report, comparison, and notifications carry
  certificate findings with no special casing. Run it on its own with
  `--tags certs`.

  **No new dependency on managed hosts.** Parsing shells out to `openssl`,
  which is present on every supported distribution; the handshake uses the
  Python standard library. Nothing is installed, and a host without `openssl`
  reports `cert_scan_unavailable` rather than failing.

  Two defaults exist to keep the signal honest. The system CA trust store is
  scanned but only reported when a certificate is already **expired** --
  reporting normal expiry across hundreds of root certificates that are not
  yours would bury every real finding. And a file matching the certificate
  patterns but holding no certificate -- a `privkey.pem` in a Let's Encrypt
  directory -- is skipped rather than reported as broken.

  Certificate severity is computed rather than looked up, because it depends
  on the certificate: `cert_expiring` is `critical` inside
  `linux_vitals_cert_critical_days` and `warning` inside
  `linux_vitals_cert_warning_days`. See
  [docs/threat-model.md](docs/threat-model.md) for what enabling endpoint
  checks means for outbound connections and for `become`.


- **Severity-based finding classification and alert thresholds**
  ([#8](https://github.com/sameeralam3127/linux-vitals/issues/8)). Every
  finding is now an object with a stable `id`, a human `message`, and a
  `severity` of `info`, `warning`, or `critical`, instead of a bare string.
  Each host carries a rolled-up `severity` (the highest among its findings, or
  `none`) and `severity_counts`; the fleet summary carries
  `hosts_by_severity` and `findings_by_severity`.

  The `id` is the durable identity. It is what severity is keyed on and what
  an external consumer should join against -- `message` wording can now
  change without that being a breaking change. A finding that can occur more
  than once per host also carries `subject` -- the unit for the self-healing
  finding, the path or endpoint for certificate findings -- so nothing has to
  parse the message to find what it refers to, and `(id, subject)` is unique
  within a host.

  The dashboard shows a severity badge per finding (ordered most severe
  first), adds Critical/Warning/Info filter chips and Critical-hosts and
  Warning-hosts tiles. Slack gains a severity line and a "Needs attention
  first" list of the critical hosts. Both JSON outputs carry the new fields.

  Severity is retunable per finding, merged over the shipped map so that
  findings added in a later release keep a sensible default:

  ```yaml
  linux_vitals_finding_severity_overrides:
    apparmor_disabled: info
    reboot_required: critical
  ```

  `linux_vitals_fail_on_severity` decides what fails a host. It defaults to
  `info`, meaning any finding fails it -- **the behaviour of every previous
  release**. Raising it to `warning` or `critical` is what turns severity into
  triage: findings are still all reported, but only ones at or above the
  threshold count against the host. An unrecognised value falls back to
  failing on anything, so a typo in `group_vars` cannot silently pass a broken
  fleet.

### Changed

- **JSON report schema is now `2.0`** (from `1.2`). `findings`, `comparison.new_findings`,
  and `comparison.resolved_findings` changed from arrays of strings to arrays
  of `{id, message, severity}` objects. **A consumer that reads finding
  strings out of the JSON or webhook payload needs updating.** The host object
  gains `severity` and `severity_counts`; `summary` gains `hosts_by_severity`,
  `findings_by_severity`, and `fail_on_severity`; `comparison` gains
  `severity_before` and `severity_after`.

  Snapshots written by an earlier release hold plain strings. A postcheck
  against such a baseline translates each one to the id this release gives
  it, using the fixed set of messages 1.3.1 could emit, so a finding that
  persists through a maintenance window spanning the upgrade is reported as
  neither new nor resolved. A string that matches none of them is compared on
  its message ([#77](https://github.com/sameeralam3127/linux-vitals/issues/77)).

- A severity a finding already carries is now preserved by the classification
  step, rather than being overwritten from the severity map. Findings whose
  level depends on the data rather than on the finding type -- every
  certificate finding -- could not otherwise be classified at all. Precedence
  is: an explicit operator override, then a severity the producing role
  computed, then the shipped map, then `warning`.

- The baseline/postcheck comparison now diffs on finding identity --
  `(id, subject)` -- rather than on the whole finding. A finding whose wording
  or severity changed between the two runs is no longer reported as both new
  and resolved. `subject` is part of the identity because an id repeats
  within a host: two failed services are both `service_manual_followup`, and
  one that newly failed alongside one already failing must still be reported
  as new ([#77](https://github.com/sameeralam3127/linux-vitals/issues/77)).

### Fixed

- **`examples/group_vars/all.yml.example` recommended a path that does not
  work.** It suggested anchoring `linux_vitals_output_path` to `playbook_dir`
  and stated that `.env` is loaded from `{{ playbook_dir }}/.env`. Neither has
  been true for some time: every path that should live in the operator's
  project resolves from `inventory_dir`, and
  [docs/architecture.md](docs/architecture.md) has a section explaining that
  `playbook_dir` was abandoned precisely because it resolves *inside the
  installed collection* when invoked by FQCN. Anyone following the example
  would have put `.env` beside their playbook and silently got no
  notifications at all.

  `tests/test_examples.py` now guards this, along with: no example file
  references `playbook_dir`; every file under `examples/` is referenced by at
  least one doc; every variable the example documents actually exists in a
  role's defaults; and example inventory addresses stay inside the RFC 5737
  documentation range.

## [1.3.1] - 2026-09-12

### Fixed

- **`vitals_report` failed on ansible-core 2.16, the declared floor.** The five
  `.env` patterns in `config.yml` were Jinja string literals containing both a
  double and a single quote, to describe the optional quoting around a value.
  2.16's templating cannot lex that literal and failed the task with
  `unexpected char` before the regex was ever applied -- and because the task
  correctly carries `no_log: true`, the operator saw only `"censored"` and had
  no way to tell a parse error from a secret-handling failure
  ([#49](https://github.com/sameeralam3127/linux-vitals/issues/49)).

  The patterns now capture the rest of the line and clean it up with filters,
  keeping quote characters out of the regex. Verified identical on 2.16.3 and
  2.20.4 across quoted, single-quoted, unquoted, spaced, empty, absent and
  comment-bearing lines.

  This also fixes two silent pre-existing bugs: the old pattern anchored `$`
  immediately after the optional closing quote, so `URL=https://a/b # note` and
  `URL="https://a/b#frag"` matched nothing at all and the channel was skipped
  without a word. Both now resolve. A trailing comment is stripped only when
  whitespace precedes the `#`, so a fragment inside a URL survives.

- `tests/test_core216_compat.py` asserts statically that no Jinja string
  literal mixes both quote characters, since a runtime test passes on any core
  newer than 2.16. It verifies its own detection against the pre-fix pattern.
  Deliberately narrow: an escaped backslash alone is fine, and the two such
  literals in `vitals_heal` and `vitals_scan` were checked against a real
  2.16.3 rather than assumed broken.

## [1.3.0] - 2026-09-12

### Fixed

- **The scan could fail at `Build per-host report object` with
  `type AnsibleUnsafeText doesn't define __round__ method`.**
  `vitals_scan`'s `result.yml` rounded `linux_vitals_memory_used_mb` and
  `linux_vitals_memory_total_mb` directly. Both are produced by a `set_fact`
  template in `discovery.yml`, and on ansible-core 2.16 -- the floor declared
  in `meta/runtime.yml` -- a numeric template result is stored as a plain
  string. Jinja's `round` has no string handling, so the run died at the last
  task of the scan, after all thirty preceding tasks had succeeded, producing
  no dashboard, no JSON report and no notification. This was not intermittent
  and did not depend on fact caching: on 2.16 it failed every run, on every
  host ([#45](https://github.com/sameeralam3127/linux-vitals/issues/45)).

  Both are now coerced with `float` before rounding, which is a no-op on a
  value that is already numeric. These were the only two of the collection's
  nine `round(` call sites at risk; the other seven round a parenthesised
  expression whose operands already carry `float`.

- `tests/test_numeric_coercion.py` rejects `round()` applied to a bare variable
  in any task file or template. This is a static check on purpose: a runtime
  test passes on a core that coerces implicitly, so it could not have caught
  the original bug. The test verifies its own detection against the pre-fix
  expression so it cannot silently stop matching.

### Added

- **Role argument specs.** Each role now ships a `meta/argument_specs.yml`
  documenting every variable its `defaults/main.yml` defines, with a type, a
  default, and a description. `ansible-doc -t role
  sameeralam3127.linux_vitals.vitals_scan` (and the other two) now renders
  usable documentation, which matters most for operators who installed the
  collection from Galaxy and have no repository to read
  ([#40](https://github.com/sameeralam3127/linux-vitals/issues/40)).

  Ansible also validates the declared types at role entry, so a malformed
  override is now reported by name instead of failing deep inside a Jinja
  expression or silently coercing. No variable is marked `required`: every one
  has a working default and the roles stay runnable with no configuration at
  all. `linux_vitals_maintenance_id`, the one conditionally-required variable,
  is still asserted by `vitals_report`'s `snapshot.yml`, which can give a
  better message than an argspec can.

- `tests/test_argument_specs.py` asserts that each spec and its
  `defaults/main.yml` describe the same variables with the same defaults, that
  every option carries a type and a description, and that none is marked
  required -- so the two files cannot drift apart unnoticed.

### Changed

- **Collection dependencies are upper-bounded.** `requirements.yml` and
  `molecule/collections.yml` now bound the major version
  (`community.general >=9.0.0,<13.0.0`, `community.docker >=3.10.0,<6.0.0`)
  rather than only the lower bound, so a breaking upstream major cannot turn a
  green build red with nothing in the diff to explain it, and CI on an
  unchanged commit installs the same majors it did before. Patch and minor
  updates still flow ([#42](https://github.com/sameeralam3127/linux-vitals/issues/42)).

  `galaxy.yml`'s `dependencies:` is deliberately unchanged: that block
  constrains consumers of the published collection, where an over-tight bound
  causes real conflicts in someone else's environment.

### Fixed

- `test_galaxy_version_matches_changelog_latest_entry` compared `galaxy.yml`
  against the newest changelog heading of any kind, so the `[Unreleased]`
  section that `CONTRIBUTING.md` tells contributors to add always failed it.
  It now skips `[Unreleased]` and compares against the newest *released*
  heading, which is what the test's stated intent -- catching a version bump
  with no changelog entry, or the reverse -- actually requires.

### Documentation

- `docs/roadmap.md` groups every open issue into a twelve-month quarterly plan,
  ordered by dependency rather than by priority label alone.
- `CONTRIBUTING.md`'s "Adding or changing a variable" checklist gains the
  argument-spec step.

## [1.2.1] - 2026-08-21

### Security

- **A failed notification printed the credential it was sent with.** Neither
  webhook task in `vitals_report`'s `notify.yml` set `no_log`, and
  `ansible.builtin.uri` does not treat `url` or `headers` as secret. A Slack
  incoming-webhook URL *is* the bearer token for that channel, so any non-2xx
  response, DNS failure, timeout, or `-v` run published it -- along with any
  `Authorization` header configured through
  `linux_vitals_generic_webhook_headers` -- into CI logs, terminal scrollback,
  and any callback plugin or ARA database. Reproduced against the shipped code:
  a post to an unreachable endpoint printed the token verbatim
  ([#22](https://github.com/sameeralam3127/linux-vitals/issues/22)).

  All three sends now run with `no_log`, and each is followed by a task that
  reports the failure quoting only the channel and the HTTP status, so a broken
  notification is still diagnosable without disclosing the secret. The module's
  own `msg` is deliberately not echoed, because some failure modes embed the
  URL in it.

  The email send did not leak in testing -- `community.general.mail` masks
  `password` through its own argspec and does not echo its arguments on this
  path -- but it now carries the same treatment as defence in depth, covering
  the SMTP username and the message body.

### Changed

- `return_content: true` dropped from both webhook posts. Nothing consumed the
  response, and capturing it only widened what a careless `debug` could print.

### Added

- `tests/test_notification_redaction.py` drives the real `notify.yml` at a dead
  endpoint, once per channel and at `-vv`, and asserts the credential never
  appears in the output while the failure stays actionable. Verified to fail
  against the pre-fix code, so it cannot rot into a test that passes either way.

## [1.2.0] - 2026-08-16

Molecule scenarios that run the roles against a live systemd host of every
supported distribution ([#5](https://github.com/sameeralam3127/linux-vitals/issues/5)) --
and the three runtime bugs they immediately found, none of which syntax
checks, linting, or template tests could have caught.

### Added

- **Molecule scenarios for Ubuntu 24.04, Rocky Linux 9, Fedora 42, and
  openSUSE Leap 15**, each booting a container with systemd as PID 1 and
  running `vitals_scan` -> `vitals_heal` -> `vitals_report` end to end. The
  scenarios share one set of playbooks under `molecule/resources/` and differ
  only in image and per-distro expectations.
- **Self-healing is exercised for real**: each scenario plants two enabled
  systemd units, one that fails on first start and succeeds on restart and one
  that can never start, then asserts the first is reported `Fixed` (and is
  genuinely `active` on the host) while the second raises a "requires manual
  follow-up" finding.
- **Per-distro reboot detection is asserted against the source that
  distribution should use** -- `reboot-required-file` on Ubuntu,
  `needs-restarting` on Rocky, `dnf-needs-restarting` on Fedora,
  `zypper-needs-rebooting` on openSUSE -- so a regression that silently
  degrades to the kernel-comparison fallback fails the run.
- CI matrix job running all four scenarios on every push and pull request.
- **[docs/testing.md](docs/testing.md)**, covering both test layers, how to run
  and debug a scenario, the SUSE image fallback strategy, and what containers
  cannot prove.

### Fixed

- **Self-healing never restarted anything.** `vitals_heal` selected services
  with `state == 'failed'` *and* a `status` containing `enabled`, but
  `service_facts` describes a failed systemd unit as `state: stopped` with
  `status: failed` -- the unit-file state is replaced by `failed`, so no unit
  could ever match both conditions. Failed units are now identified by either
  field, and "is this enabled at boot" is answered per unit with
  `systemctl is-enabled` (read from stdout, since it exits 0 for `static` and
  `indirect` too).
- **Healing outcomes never reached the report.** `vitals_scan` builds
  `linux_vitals_result` before `vitals_heal` runs, so `services_healed`,
  `healing_results`, and the "requires manual follow-up" findings were always
  empty in the dashboard and JSON report even when healing had happened.
  `vitals_heal` now rebuilds the result after a healing pass.
- **The scan crashed on any host without a separate `/boot` mount.**
  `linux_vitals_boot_mount` chained two `| first` lookups through
  `| default(..., true)`; with neither `/boot` nor `/boot/efi` in
  `ansible_facts['mounts']` -- the common case for cloud images that keep
  `/boot` on the root filesystem, and for containers -- both sides resolved to
  Undefined and the play failed with "No first item, sequence was empty".
  Boot-space status now degrades to `Not Available` instead.
- **`selinux_status` was reported as an empty string on Debian hosts.**
  `getenforce` is absent there, so the command returned an empty `stdout`,
  which `| default('not-installed')` does not replace (it only substitutes for
  Undefined). The dashboard showed a blank SELinux field instead of
  `not-installed`.

## [1.1.0] - 2026-08-07

Distro-specific hardening of reboot-required, latest-kernel, and bootloader
default detection ([#2](https://github.com/sameeralam3127/linux-vitals/issues/2)).

### Added

- **Reboot detection now reports *how* it decided.** Every host carries
  `reboot_required_source`, `reboot_detection_supported`,
  `reboot_required_packages`, and a human-readable `reboot_reason` alongside
  `reboot_required`. These surface in the JSON report (`reboot.source`,
  `reboot.detection_supported`, `reboot.pending_packages`, `reboot.reason`),
  the generic webhook payload, the Slack host breakdown, and the dashboard's
  host detail.
- **Debian/Ubuntu pending packages.** The packages that requested the reboot
  are read from `/run/reboot-required.pkgs` and reported per host.
- **SUSE `zypper needs-rebooting`.** Used when available (exit `102` means a
  reboot is needed), falling back to the marker files for older zypper.
- **dnf5 hosts.** When the standalone `needs-restarting` binary is absent,
  `dnf needs-restarting --reboothint` is used before giving up.
- **BLS boot entries.** `saved_entry`/`GRUB_DEFAULT` values that name a Boot
  Loader Specification drop-in (RHEL 8+/Fedora, SUSE) now resolve by entry id
  and by entry title, not just by `grub.cfg` menuentry title.
- **systemd-boot.** `loader.conf`'s `default` -- including a glob such as
  `fedora-*`, resolved to the version-highest match -- is read from
  `loader/entries/`, so bootloader validation works on hosts with no GRUB.
- **[docs/kernel-reboot-detection.md](docs/kernel-reboot-detection.md)**,
  documenting the per-distro detection order and the known edge cases
  (live-patched kernels, transactional/immutable hosts, auto-discovered UKIs,
  `grub.cfg` submenus, containers, and more).
- Tests covering the derived reboot facts, each distro probe, and bootloader
  resolution (BLS id, `grub.cfg` index, systemd-boot glob, no bootloader),
  plus a POSIX-syntax check of every embedded discovery script.

### Fixed

- **An unusable distro check was read as "no reboot needed".** A missing
  `needs-restarting` (RHEL minimal images without `dnf-utils`) or a
  non-`0`/`1` exit produced `reboot_required: false` -- indistinguishable from
  a genuinely up-to-date host. Those hosts now fall back to the running-vs-latest
  kernel comparison and report `reboot_required_source: kernel-comparison`.
- **Stale `/lib/modules` directories could masquerade as the latest kernel.** A
  directory left behind by an interrupted removal (no `modules.dep`, no image in
  `/boot`) made a fully patched host report its kernel as outdated forever.
  Directories are now filtered to ones that still look like an installed kernel,
  with the unfiltered listing kept as a fallback.
- **Kernel-comparison fallback referenced a fact defined in the same
  `set_fact`.** The non-Debian/RedHat/SUSE branch of `linux_vitals_reboot_required`
  read `linux_vitals_latest_kernel_selected` from the task that was defining it
  (the same class of bug as 1.0.1/1.0.2). Reboot facts are now derived in their
  own task file after discovery facts are set.
- **`--tags kernel` skipped the bootloader finalize tasks.** The two
  `Finalize bootloader ...` tasks carried no tags, so the documented
  `--tags kernel,reporting` run left `linux_vitals_bootloader_default_matches_latest`
  undefined and failed while building the result. Both are now tagged
  `discovery`/`kernel`.
- **Bootloader kernel paths weren't normalised.** Entries pointing at a symlink
  (Debian's `/vmlinuz`), at a path relative to a separate `/boot` partition, or
  at a `.efi`/`kernel-`-prefixed image compared unequal to the installed kernel
  version and produced spurious "default boot entry does not select the latest
  installed kernel" findings.

### Changed

- JSON report schema is now `1.2` (additive: the new `reboot.*` fields).

## [1.0.2] - 2026-07-12

### Fixed

- **`.env`-based notification config never actually worked.** `linux_vitals_dotenv_slack_webhook_url` (and the four other `linux_vitals_dotenv_*` secrets: generic webhook URL, SMTP host/username/password) referenced `linux_vitals_dotenv_contents` from *within the same `set_fact` call* that defined it -- the same same-task self-reference bug as the 1.0.1 bootloader fix, except here it failed silently (Ansible's `regex_findall` on an Undefined value fell through the `| default('', true)` chain to an empty string) instead of erroring, so it went undetected through every prior test and release. Every channel that relied on `.env` as a fallback (rather than an explicit inventory/`group_vars` value) was silently skipped. Split `vitals_report/tasks/config.yml`'s first task into two sequential tasks. Verified by re-running against the live Multipass fleet: the Slack notification task changed from `skipping` to `ok` and the webhook received an actual HTTP POST.

## [1.0.1] - 2026-07-12

Fixes found by running `playbooks/baseline.yml` / `playbooks/postcheck.yml` against a real 10-node Ubuntu fleet (Multipass) for the first time -- none of these were reachable from the macOS-only testing available during initial development.

### Fixed

- **Service-name resolution was non-deterministic.** Every `<candidates> | intersect(<present services>) | first` lookup (time-sync, `sssd`, `systemd-journald`) used `intersect()`, whose result order is not guaranteed to follow either input list -- it could return a different match on every run against the identical host state, occasionally picking a present-but-inactive unit (e.g. `ntp.service`, stopped) over the actually-running one. Replaced with `<candidates> | select('in', <present services>) | list | first`, which deterministically preserves the candidate list's priority order.
- **`linux_vitals_time_sync_candidates` never included Debian/Ubuntu's actual service names.** It only listed `chronyd*` (RHEL's name) and `ntp*`, missing `chrony.service`/`chrony` (the real unit installed by Debian/Ubuntu's `chrony` package) and `systemd-timesyncd.service`/`systemd-timesyncd` (Ubuntu's out-of-the-box default). Every stock Ubuntu host was reporting a false "chronyd or ntp is not installed" finding despite `systemd-timesyncd` running the whole time. Both are now in the candidate list.
- **Systemd alias units report `state: active`, not `state: running`.** `chronyd.service` is often a symlink alias to `chrony.service` on Debian/Ubuntu; `ansible.builtin.service_facts` reports alias units with `state: active` rather than `running`. The `sssd`/`systemd-journald`/time-sync "is it up" checks, and the self-healing restart-success check, only accepted `running` and treated a perfectly healthy aliased service as down. Both now accept `state in ['running', 'active']`.
- **Same-task variable self-reference in bootloader validation.** `linux_vitals_bootloader_validation_message` referenced `linux_vitals_bootloader_default_matches_latest` from within the *same* `set_fact` call that defined it -- Ansible templates every key in a `set_fact` dict against the variable context that existed *before* the task ran, so this was always undefined at evaluation time. It only surfaced as a hard failure once bootloader detection actually reached `status: resolved` (i.e. on a real host with working `grubby`/`grub2-editenv`, never on the macOS dev machine). Split into two sequential tasks.

## [1.0.0] - 2026-07-12

Published to [Ansible Galaxy](https://galaxy.ansible.com/ui/repo/published/sameeralam3127/linux_vitals/).

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
- Per-role `README.md` for `vitals_scan`, `vitals_heal`, and `vitals_report` (required by Ansible Galaxy's import validation -- the first publish attempt failed with "No role readme found").

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
