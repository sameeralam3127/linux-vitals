# vitals_report

Reporting, comparison, and notification role, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

Loads notification configuration (inventory/`group_vars`/extra-vars, with
a local `.env` fallback), persists baseline/postcheck snapshots, computes
the before/after comparison for postcheck runs, renders the self-contained
HTML dashboard and JSON report, manages archive retention, and sends
Slack/email/generic-webhook summaries.

## Role Variables

See [docs/variable-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/variable-reference.md)
and [docs/configuration-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/configuration-reference.md)
in the parent collection for the full list: maintenance workflow
(`linux_vitals_phase`, `linux_vitals_maintenance_id`), output/archiving,
and each notification channel.

## Example

```yaml
- hosts: linux_servers
  roles:
    - role: sameeralam3127.linux_vitals.vitals_scan
    - role: sameeralam3127.linux_vitals.vitals_heal
    - role: sameeralam3127.linux_vitals.vitals_report
```

Reporting tasks are `delegate_to: localhost` and `run_once: true`, so they
execute once per play regardless of fleet size. Requires
`linux_vitals_result` to already be set per host (by `vitals_scan`), so run
it last. See the collection's
[report guide](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/report-guide.md)
for what the dashboard and JSON output contain.

## License

MIT
