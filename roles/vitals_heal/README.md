# vitals_heal

Opt-in, one-shot self-healing role, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

Attempts exactly one restart per systemd-enabled service found in a
`failed` state, verifies that each restart held, then re-checks the
required-service status and rebuilds `vitals_scan`'s result so downstream
reporting reflects the verified outcome. Failed units are identified from
`service_facts` (which reports them as `state: stopped`, `status: failed`)
and filtered to the enabled ones with `systemctl is-enabled`. Entirely gated
by `linux_vitals_heal_enabled` (default `false`) -- with it left at the
default, this role's tasks are skipped and nothing on managed hosts
changes.

Failed-and-enabled is a statement about the host, not a policy, so three
guardrails narrow it further -- include/exclude lists per unit, a maintenance
window and a cap on restarts per host per run. All are off by default, so a
run that configures none of them restarts exactly what the role always did.
A unit a guardrail rules out is never silently dropped: it is reported in
`linux_vitals_heal_skipped`, which reaches the JSON report as
`self_healing.skipped_by_policy` with the reason it was left alone.

A restart is verified with read-only `systemctl show` polls, not read once.
Each unit is polled until it is active, failed or inactive; a unit that came
up must still be active, on the same run, after
`linux_vitals_heal_stability_seconds`. A `Type=oneshot` unit without
`RemainAfterExit=yes` is inactive once it has run, so it is judged on
`Result=` instead -- `inactive` with `Result=success` is a unit that ran to
completion, not one that needs a human.

Every wait is bounded by the role's own variables, whatever a unit's
`TimeoutStartSec=` says: `linux_vitals_heal_restart_timeout` per restart, the
settle budget per unsettled unit, and the stability window once per host. One
hung start job cannot hold the role, and with it the rest of a linear run,
open-ended. Every entry in
`linux_vitals_healing_results` records the `result` (`Fixed`, `Failed to
Fix`, `Manual Intervention Required`), an `outcome` (`fixed`,
`still_failed`, `unknown`), a `reason` code and a `detail` sentence. See the
[report guide](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/report-guide.md#self-healing-outcomes).

## Role Variables

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_heal_enabled` | `false` | Opt-in switch. Set `true` (globally or per-group) to allow restart attempts. |
| `linux_vitals_heal_settle_retries` | `10` | Extra polls while a restarted unit is still activating, deactivating or reloading. A unit still unsettled after them is reported as `unknown`, never `Fixed`. |
| `linux_vitals_heal_settle_delay` | `3` | Seconds between those polls (30 s in total by default). |
| `linux_vitals_heal_stability_seconds` | `5` | How long a unit that came up must stay active on the same run to count as `Fixed`. Waited once per host, only where something came up. |
| `linux_vitals_heal_restart_timeout` | `120` | Seconds one restart may block the run before the role stops waiting and lets the settle poll judge the unit. Above systemd's own 90 s default start timeout, so only a unit with no start timeout at all -- `Type=oneshot` by default -- is cut short, and then reported `unknown`/`restart_timeout`. `0` waits as long as it takes. |
| `linux_vitals_heal_include_services` | `["*"]` | Units in scope for a restart. Globs (`*`, `?`) against the unit name, with `.service` optional. The default puts every failed, enabled unit in scope. |
| `linux_vitals_heal_exclude_services` | `[]` | Units never to restart, whatever the include list says. For anything you would not restart unattended -- a database or clustered service, or a `Type=oneshot` job a restart would run again. |
| `linux_vitals_heal_max_restarts` | `0` | The most units one run may restart on one host; `0` means no limit. Over the limit the host is left entirely alone rather than having an arbitrary subset restarted. |
| `linux_vitals_heal_window_start` | `""` | Start of the time of day, on the managed host's own clock, when restarts are allowed, as 24-hour `HH:MM`. Empty means any time; must be set together with the end. |
| `linux_vitals_heal_window_end` | `""` | End of that window. An end before the start spans midnight. Unrelated to `linux_vitals_heal_stability_seconds`, which is how long a restart must hold rather than when one is allowed. |

## Example

```yaml
- hosts: linux_servers
  vars:
    linux_vitals_heal_enabled: true
  roles:
    - role: sameeralam3127.linux_vitals.vitals_scan
    - role: sameeralam3127.linux_vitals.vitals_heal
    - role: sameeralam3127.linux_vitals.vitals_report
```

Depends on `linux_vitals_service_status`/`ansible_facts.services` set by
`vitals_scan`'s discovery step, and its output
(`linux_vitals_healing_results`, `linux_vitals_services_healed`,
`linux_vitals_heal_skipped`) feeds back
into `vitals_scan`'s result object -- run it between `vitals_scan` and
`vitals_report`, not standalone. See the collection's
[architecture doc](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/architecture.md).

## License

MIT
