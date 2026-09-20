# Examples

## Custom thresholds per environment

```yaml
# group_vars/production.yml
linux_vitals_ram_warning_threshold: 70
linux_vitals_ram_critical_threshold: 90
linux_vitals_boot_warning_threshold: 25

# group_vars/staging.yml
linux_vitals_ram_warning_threshold: 85
linux_vitals_ram_critical_threshold: 97
```

## Self-healing on one group only

```yaml
# group_vars/web_tier.yml
linux_vitals_heal_enabled: true
```

Everything else inherits the default (`false`), so only hosts in
`web_tier` are ever restarted.

## Large fleet (100+ hosts) with tighter concurrency

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck \
  --forks 25
```

Reporting tasks (`vitals_report`) are `delegate_to: localhost` and
`run_once: true`, so they execute exactly once regardless of fleet size or
fork count -- only the scan/heal stages parallelize across hosts.

## Scoped runs with tags

```bash
# Just kernel/reboot posture, skip the rest
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck --tags kernel,reporting

# Rebuild the dashboard and resend notifications from the last run's data,
# without re-scanning hosts
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck --tags reporting,notifications
```

`reporting` is required alongside any narrower tag if you still want a
dashboard out of the run -- see [troubleshooting.md](troubleshooting.md).

## Multiple maintenance windows in flight

Maintenance ids are just strings, so you can run independent
baseline/postcheck pairs for different windows without them colliding:

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
  -e linux_vitals_maintenance_id=db-cluster-2026-08-01

ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
  -e linux_vitals_maintenance_id=web-tier-2026-08-03
```

Each writes to its own `reports/snapshots/<maintenance_id>/` subtree.

## CI validation (this repo's own approach)

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Symlink repository as the sameeralam3127.linux_vitals collection
  run: |
    mkdir -p .dev-collections/ansible_collections/sameeralam3127
    ln -s "$GITHUB_WORKSPACE" .dev-collections/ansible_collections/sameeralam3127/linux_vitals
- run: ansible-playbook playbooks/healthcheck.yml --syntax-check
- run: ansible-lint roles/ playbooks/
- run: pytest -q
```

## Piping the JSON report into observability tooling

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck
jq '.hosts[] | select(.status == "Fail") | {hostname, findings}' \
  reports/linux_vitals_report.json
```

Or ship `reports/linux_vitals_report.json` directly with Filebeat/Fluent
Bit into ELK/OpenSearch, or scrape it from a CI/AAP job artifact for
downstream alerting on `summary.regressed_count` after a maintenance
window.

## Ansible Vault for notification secrets

Prefer Vault over `.env` when your inventory is itself encrypted or
version-controlled with the rest of your infra repo:

```yaml
# group_vars/all/vault.yml (encrypted with ansible-vault)
linux_vitals_slack_webhook_url: "https://hooks.slack.com/services/..."
linux_vitals_email_password: "..."
```

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck --ask-vault-pass
```

## Starting files to copy

Rather than writing these from scratch:

| File | What it gives you |
| --- | --- |
| [examples/inventory/hosts.example.ini](../examples/inventory/hosts.example.ini) | A four-host mixed fleet (RHEL, Ubuntu, Fedora, SLES) with `ansible_user`, `become`, and a key path already set |
| [examples/inventory/large-fleet.example.ini](../examples/inventory/large-fleet.example.ini) | Ten generated nodes, for exercising the dashboard's search and filter at a realistic host count |
| [examples/group_vars/all.yml.example](../examples/group_vars/all.yml.example) | Every tunable variable, commented out, with the `.env`-versus-inline guidance for secrets |
| [examples/playbooks/custom-thresholds.yml](../examples/playbooks/custom-thresholds.yml) | Overriding thresholds and enabling healing for one ad-hoc run without touching `group_vars` |

Addresses use the RFC 5737 documentation range (`192.0.2.0/24`), so nothing
resolves by accident -- replace them before running anything.
