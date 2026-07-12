# vitals_heal

Opt-in, one-shot self-healing role, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

Attempts exactly one restart per systemd-enabled service found in a
`failed` state, then re-checks the required-service status so downstream
reporting reflects the post-restart state. Entirely gated by
`linux_vitals_heal_enabled` (default `false`) -- with it left at the
default, this role's tasks are skipped and nothing on managed hosts
changes.

## Role Variables

| Variable | Default | Description |
|---|---|---|
| `linux_vitals_heal_enabled` | `false` | Opt-in switch. Set `true` (globally or per-group) to allow restart attempts. |

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
