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

A restart is verified with read-only `systemctl show` polls, not read once.
Each unit is polled until it is active, failed or inactive; a unit that came
up must still be active, on the same run, after
`linux_vitals_heal_stability_seconds`. Every entry in
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
(`linux_vitals_healing_results`, `linux_vitals_services_healed`) feeds back
into `vitals_scan`'s result object -- run it between `vitals_scan` and
`vitals_report`, not standalone. See the collection's
[architecture doc](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/architecture.md).

## License

MIT
