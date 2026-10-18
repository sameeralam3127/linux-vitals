# vitals_report

Reporting, comparison, and notification role, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

Loads notification configuration (inventory/`group_vars`/extra-vars, with
a local `.env` fallback), persists baseline/postcheck snapshots, computes
the before/after comparison for postcheck runs, renders the self-contained
HTML dashboard and JSON report, manages archive retention, and sends
Slack/email/generic-webhook summaries. Optionally writes a Prometheus text
0.0.4 file and a 22-column fleet CSV from the same collected results.

## Role Variables

See [docs/variable-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/variable-reference.md)
and [docs/configuration-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/configuration-reference.md)
in the parent collection for the full list: maintenance workflow
(`linux_vitals_phase`, `linux_vitals_maintenance_id`, and
`linux_vitals_snapshot_shard` for a fleet sharded into several runs),
output/archiving, optional exports, and each notification channel.

Several runs can share the report, archive and snapshot directories. Give each
its own output path and, for one maintenance window split across runs, its own
`linux_vitals_snapshot_shard`. See
[docs/architecture.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/architecture.md#runs-that-share-a-directory)
for what is safe to share.

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
for what the dashboard, JSON and optional exports contain.

Set `linux_vitals_metrics_output_path` (for example,
`/var/lib/node_exporter/textfile_collector/linux_vitals.prom`) or
`linux_vitals_csv_output_path` (for example,
`"{{ inventory_dir }}/reports/linux_vitals_report.csv"`) to enable an export.
Both default to empty/off. They write on the controller with the configured
report modes, perform no discovery and expose no HTTP endpoint. All report
paths must differ; concurrent runs need their own paths. Metrics reject
duplicate host identities. Export files are overwritten, not archived.
Disabling an export does not remove its existing file; remove it explicitly
to prevent stale textfile metrics. See the report guide for node_exporter
setup, file-age monitoring and CSV formula protection.

## License

MIT
