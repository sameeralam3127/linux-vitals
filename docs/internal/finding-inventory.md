# Finding inventory (`main` at `e9f04fa`)

Internal working document for the "separate collection from evaluation"
refactor, tracked from
[#98](https://github.com/sameeralam3127/linux-vitals/issues/98). It describes the code **as it is on `main` at `e9f04fa`**, not as it
should be. Nothing here is a proposal; where the current behaviour looks
wrong it is recorded in [NOTES](#notes) and left alone.

Purpose: before anything is moved, know exactly what every finding reads,
where its severity is decided, and which files have to agree for it to fire.

- 23 finding ids in total: **15** from `vitals_scan` (+`vitals_heal`),
  **8** from `vitals_certs`.
- **12 of 23** have their logic split across more than one file.
- **6 evaluation decisions already happen during collection**, inside
  `discovery.yml` — see [Where the boundary actually is](#where-the-boundary-actually-is).

## Raw input sources

Everything any finding consumes ultimately comes from one of these. This is
the candidate content for `state_schema: 1`.

| # | Source | Produced by | Consumed as |
| --- | --- | --- | --- |
| R1 | `ansible.builtin.setup`, subsets `min`, `hardware`, `network`, `virtual` | `discovery.yml:2` | `ansible_facts.*` |
| R2 | `ansible.builtin.service_facts` | `discovery.yml:12` | `ansible_facts.services` |
| R3 | `journalctl --since <linux_vitals_log_window> --no-pager --output=short-iso` | `discovery.yml:53` | `linux_vitals_journalctl.stdout` |
| R4 | `sh -c 'lastb -n 5 2>/dev/null'` | `discovery.yml:68` | `..._failed_login_attempts_cmd.stdout_lines` |
| R5 | `who -b` | `discovery.yml:81` | `..._last_reboot_cmd.stdout` |
| R6 | kernel-listing shell script → `latest=`, `updated_at=`, `filtered=` | `discovery.yml:93` | `..._latest_kernel_cmd.stdout` |
| R7 | bootloader shell script → `supported=`, `source=`, `default_entry=`, `default_kernel=`, `status=` | `discovery.yml:142` | `..._bootloader_default_cmd.stdout` |
| R8 | Debian reboot probe → `supported=`, `detected=`, `source=`, `detail=`, `packages=` | `discovery.yml:442` | `..._debian_reboot_cmd.stdout` |
| R9 | RedHat reboot probe, same five keys | `discovery.yml:492` | `..._redhat_reboot_cmd.stdout` |
| R10 | SUSE reboot probe, same five keys | `discovery.yml:557` | `..._suse_reboot_cmd.stdout` |
| R11 | `getenforce` | `discovery.yml:605` | `..._selinux_cmd.stdout` |
| R12 | `aa-status --enabled` | `discovery.yml:616` | `..._apparmor_cmd.rc` **(exit code only)** |
| R13 | `sh -c 'find /boot -maxdepth 1 ... rescue ...'` | `discovery.yml:628` | `..._rescue_image_cmd.stdout_lines` |
| R14 | `journalctl --since <linux_vitals_audit_log_window> ...` | `discovery.yml:641` | `..._audit_journalctl.stdout` |
| R15 | `linux_vitals_cert_facts` module (files + endpoints + `openssl_available`) | `vitals_certs/tasks/main.yml:12` | `..._cert_scan.*` |
| R16 | `systemctl is-enabled <unit>` per failed unit | `vitals_heal/tasks/main.yml:41` | `..._enabled_checks.results[].stdout` |
| R17 | `ansible.builtin.service` restart results | `vitals_heal/tasks/main.yml:64` | `..._restart_attempts.results[]` |

Specific `ansible_facts` keys read: `services`, `os_family`, `service_mgr`,
`distribution`, `distribution_version`, `hostname`, `default_ipv4.address`,
`kernel`, `memtotal_mb`, `memavailable_mb`, `memfree_mb`, `mounts[]`
(`mount`, `size_available`, `size_total`), `uptime_seconds`,
`virtualization_type`, `virtualization_role`, `product_serial`.

R8–R10 are mutually exclusive by `os_family` and are collapsed into one
`linux_vitals_reboot_probe_output` at `discovery.yml:812`, so the reboot
schema needs only one probe block, not three.

## The 15 core findings

Severity column: **map** = `linux_vitals_finding_severities` in
`roles/vitals_scan/defaults/main.yml`, applied by `severity.yml:33`.
All 15 are map-classified; none computes its own severity.

| id | Severity | Fires when | Raw inputs | Logic lives in | Split |
| --- | --- | --- | --- | --- | --- |
| `ram_critical` | map: critical | `ram_status == 'Critical'` | R1 `memtotal_mb`, `memavailable_mb`\|`memfree_mb` | `discovery.yml:667` (pct), `:704` (threshold), `result.yml:10` | **3 places, 2 files** |
| `log_errors` | map: info | `log_errors \| int > 0` | R3 | `discovery.yml:678` (regex), `:702` (count), `result.yml:13` | **3 places, 2 files** |
| `sssd_inactive` | map: warning | `service_status.sssd.state not in ['running','active']` | R2 | `services.yml:5`, `result.yml:16` | **2 files** |
| `journald_inactive` | map: critical | same shape, `systemd_journald` | R2 | `services.yml:25`, `result.yml:19` | **2 files** |
| `time_sync_absent` | map: warning | `service_status.time_sync.service_name == 'absent'` | R2 | `discovery.yml:26` (candidates), `:40` (resolve), `services.yml:45`, `result.yml:22` | **4 places, 3 files** |
| `time_sync_inactive` | map: warning | `elif` state not running/active | R2 | same four as above | **4 places, 3 files** |
| `reboot_required` | map: warning | `linux_vitals_reboot_required` | R8/R9/R10, falls back to R6+R1 `kernel` | `discovery.yml:812` (select probe), `reboot_facts.yml:4` (parse), `:58` (decide + fallback), `result.yml:27` | **4 places, 3 files** |
| `kernel_not_latest` | map: warning | `not latest_kernel_selected` | R6 `latest=`, R1 `kernel` | `discovery.yml:757`, `result.yml:30` | **2 files** |
| `bootloader_mismatch` | map: warning | `bootloader_default_status == 'resolved' and not ..._matches_latest` | R7, R6 | `discovery.yml:804` (status), `:879` (match), `result.yml:33` | **3 places, 2 files** |
| `boot_space_low` | map: warning | `boot_space_status == 'Low'` | R1 `mounts[]` | `discovery.yml:907` (pick mount), `:955` (threshold), `result.yml:36` | **3 places, 2 files** |
| `kernel_install_failures` | map: warning | `kernel_install_failures \| int > 0` | R14 | `discovery.yml:686` (regex), `:860` (count), `result.yml:39` | **3 places, 2 files** |
| `failed_logins` | map: info | `failed_login_attempts \| length > 0` | R4 | `discovery.yml:835` (filter), `result.yml:42` | **2 files** |
| `selinux_disabled` | map: warning | `selinux_status not in ['Enforcing','Permissive'] and os_family == 'RedHat'` | R11, R1 `os_family` | `discovery.yml:822`, `result.yml:45` | **2 files** |
| `apparmor_disabled` | map: warning | `os_family == 'Debian' and apparmor_status != 'enabled'` | R12 (rc), R1 `os_family` | `discovery.yml:829`, `result.yml:48` | **2 files** |
| `service_manual_followup` | map: critical | per `healing_results` entry where `result != 'Fixed'` | R2, R16, R17 | `vitals_heal/tasks/main.yml:77`, `result.yml:51` | **2 roles** |

`service_manual_followup` is the only core finding that repeats within a host
and the only one carrying a `subject` (the service name).

## The 8 certificate findings

All produced by one template at `vitals_certs/tasks/main.yml:66`, all from
R15, all carrying `subject`. **Severity is decided inline, not by the map** —
`severity.yml`'s precedence step 2 exists for exactly this.

| id | Severity | Fires when |
| --- | --- | --- |
| `cert_expired` | inline: critical | `cert.expired` |
| `cert_expiring` | inline: **critical or warning** | `days_remaining <= cert_critical_days` → critical; `<= cert_warning_days` → warning |
| `cert_weak_signature` | inline: warning | `signature_algorithm` substring-matches the weak list |
| `cert_self_signed` | inline: warning | endpoint only, `self_signed` |
| `cert_weak_tls_version` | inline: warning | `tls_version < cert_minimum_tls_version` (string compare) |
| `cert_served_not_on_disk` | inline: warning | served fingerprint absent from disk set (`main.yml:37`, separate task) |
| `cert_endpoint_unreachable` | inline: warning | endpoint carries `error` |
| `cert_scan_unavailable` | inline: info | `not openssl_available` |

Trust-store suppression (`linux_vitals_cert_trust_store_paths`) gates
`cert_expiring`, `cert_weak_signature` and `cert_self_signed` but **not**
`cert_expired` — deliberate, per the defaults comment.

## Where severity and status are decided

One implementation, three steps, in `roles/vitals_scan/tasks/severity.yml`:

1. `:33` attaches severity. Precedence: operator override → severity the
   finding already carries → shipped map → `warning`.
2. `:58` rolls up `linux_vitals_host_severity` (max by
   `linux_vitals_severity_order`; `none` when empty) and
   `linux_vitals_severity_counts`.
3. `:89` decides `linux_vitals_final_status` — `Fail` if any finding is at or
   above `linux_vitals_fail_on_severity` (default `info`, so any finding
   fails).

`vitals_certs:191` and `vitals_heal:127` re-enter this same file rather than
duplicating it, so there is exactly one severity implementation to snapshot.

Downstream and **not** part of evaluation: `vitals_report/tasks/compare.yml`
diffs findings on `(id, subject)` and normalises 1.x string findings;
`render.yml:92` computes the fleet `health_score_pct` from `final_status`.

## Where the boundary actually is

The refactor assumes collection and evaluation are separable. Today six
evaluation decisions are made inside collection, before `result.yml` ever
runs:

| Decision | Made at | Reads a threshold/policy |
| --- | --- | --- |
| `ram_status` OK/Warning/Critical | `discovery.yml:704` | `ram_warning_threshold`, `ram_critical_threshold` |
| `boot_space_status` Healthy/Low/Not Available | `discovery.yml:955` | `boot_warning_threshold` |
| `latest_kernel_selected` | `discovery.yml:757` | comparison policy (exact string equality) |
| `apparmor_status` enabled/disabled | `discovery.yml:829` | exit code → state mapping |
| `bootloader_default_matches_latest` | `discovery.yml:879` | comparison policy |
| `reboot_required` + fallback to kernel comparison | `reboot_facts.yml:58` | fallback policy when the probe is unsupported |

`services.yml` is a seventh, milder case: it maps `ansible_facts.services`
into a three-key status map, and the `'running'`/`'active'` vocabulary the
findings test against is fixed there.

Consequence for the golden tests (#98): tests anchored at `result.yml`'s
inputs would snapshot none of the six. They are the decisions most likely to
move once evaluation is extracted, so the regression net starts further
upstream and runs the derivation tasks in `discovery.yml` as well.

## NOTES

Recorded, not fixed. Parity first; each fix is its own issue and updates the
golden files deliberately, so the behaviour change is visible in its PR.

1. **A check that cannot run reports no finding, which reads as a pass.**
   Against the project rule that an unrunnable check must report `unknown`:
   - `log_errors` and `kernel_install_failures`: the `journalctl` tasks are
     `when: service_mgr == 'systemd'`. On a non-systemd host the register is
     never set, `| default('')` yields zero matches, and the host looks
     clean. (`discovery.yml:64`, `:652`, `:678`, `:686`)
   - `failed_logins`: no `lastb` binary → empty `stdout_lines` → no finding.
     Indistinguishable from a host with no failed logins. (`discovery.yml:68`)
   - `bootloader_mismatch`: `status` of `unavailable` or `entry-only` → no
     finding. The validation message says so, but the findings list does not.
     (`result.yml:33`)
   - `boot_space_low`: no `/boot` or `/boot/efi` mount → `Not Available` → no
     finding. Common on cloud images where `/boot` is not a separate
     filesystem, and the partition can be full without anything firing.
     (`discovery.yml:955`)

2. **`sssd_inactive` fires on hosts that never had sssd.** A missing unit
   gives `state: 'missing'`, which is not in `['running','active']`, so the
   finding fires. `time_sync` distinguishes absent from inactive with two
   separate ids; `sssd` and `systemd_journald` do not. On a fleet where sssd
   is deliberately not installed this is a permanent false positive.
   (`services.yml:5`, `result.yml:16`)

3. **`journald_inactive` is critical on any non-systemd host** for the same
   reason, and the id says "not active" when the truth is "not present".

4. **Redundant condition in `bootloader_mismatch`.** `result.yml:33` tests
   `status == 'resolved' and not matches_latest`, but `matches_latest`
   (`discovery.yml:881`) already requires `status == 'resolved'`. Harmless
   today; it means the two can disagree if either is changed alone.

5. **`failed_login_count` is capped at 5** by `lastb -n 5` (`discovery.yml:73`).
   The report field reads as a count of recent failures but cannot exceed 5.
   The finding itself only tests `> 0`, so the cap does not affect it.

6. **An operator override flattens `cert_expiring`.** Override precedence
   (step 1) beats the computed severity (step 2), so setting
   `cert_expiring: warning` also downgrades certificates inside the critical
   window. Documented as intended in `severity.yml:16`, noted here because it
   is the one place an override changes more than one finding's meaning.

7. **`cert_weak_tls_version` compares TLS versions as strings**
   (`vitals_certs:132`). `"TLSv1.2" < "TLSv1.2"` works for the shipped values
   but would order `TLSv1.10` before `TLSv1.2` if such a string ever existed.

8. **Unknown severities silently become `warning`** — `severity.yml:44` for an
   unmapped id, and `:62` ranks an unrecognised severity string at index 1.
   A typo in an override is not an error.

9. **`ram_used_pct` divides by `memtotal_mb` with no zero guard**
   (`discovery.yml:672`). `boot_free_pct` does guard, with
   `size_total | default(1)`.

10. **`log_errors` matches the words anywhere in a line**, including inside
    unit names (`...error-reporting.service started`). Classified `info`,
    which is presumably why it has been tolerated.

11. **A mistyped severity override makes a host with a finding pass.**
    Override values are not validated (`meta/argument_specs.yml` types
    `linux_vitals_finding_severity_overrides` as a plain dict). An override
    such as `sssd_inactive: critcal` is attached as-is by `severity.yml:33`;
    the host rollup at `:58` ranks the unknown string as `warning`, but the
    `final_status` step at `:89` counts only severities in
    `linux_vitals_severity_order`, so the finding never fails the host. The
    report shows a `warning` host with a finding attached and `Pass`. Same
    class as NOTES 1 and 8, and worse: it is a wrong answer, not a missing one.

12. **`last_reboot` is never stripped of its `system boot` prefix.** Not a
    finding, but it is in the report. `discovery.yml:857` writes the regex
    as `'^\\s*system boot\\s+'` inside a folded (`>-`) scalar, where YAML
    does not unescape backslashes, so the pattern Jinja receives looks for a
    literal backslash and never matches. Every report shows
    `system boot  2026-09-24 10:55` instead of the date. Found by the golden
    tests (#98); the same regex in a double-quoted scalar works.
