# Quick Start

This walks through the fastest path to a first HTML dashboard, then to a
full pre-maintenance / post-maintenance comparison.

## 1. Install and set up an inventory

```bash
ansible-galaxy collection install sameeralam3127.linux_vitals
ansible-galaxy collection install -r requirements.yml   # community.general, for email notifications
cp examples/inventory/hosts.example.ini inventory.ini
```

Edit `inventory.ini` with your real hosts:

```ini
[linux_servers]
web01 ansible_host=10.0.1.11
web02 ansible_host=10.0.1.12
db01 ansible_host=10.0.1.21

[linux_servers:vars]
ansible_user=automation
ansible_become=true
```

## 2. Run a one-shot health check

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck
```

Open `reports/linux_vitals_report.html` (created next to `inventory.ini`).
You now have a fleet-wide dashboard: a health-score ring, pass/fail counts,
and a searchable, sortable, expandable host table.

## 3. Turn on self-healing (optional)

By default nothing on managed hosts is changed. To let LinuxVitals attempt
one restart of any systemd-enabled service it finds `failed`:

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck \
  -e linux_vitals_heal_enabled=true
```

## 4. Run the pre/post-maintenance workflow

Before a maintenance window, capture a baseline:

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.baseline \
  -e linux_vitals_maintenance_id=2026-07-12-patch-window
```

Do your maintenance (patching, reboots, config changes -- outside
LinuxVitals). Then, using the **same** maintenance id, capture the
postcheck:

```bash
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.postcheck \
  -e linux_vitals_maintenance_id=2026-07-12-patch-window
```

The resulting `reports/linux_vitals_report.html` now includes a "Change"
column, Regressed/Improved/New-hosts filter chips, and a per-host
"Change vs. baseline" panel (status, RAM delta, kernel change,
reboot-required change, new/resolved findings). See the
[report guide](report-guide.md) for a full tour.

## 5. Turn on notifications (optional)

```bash
cp .env.example .env    # next to inventory.ini
```

Edit `.env` with a Slack webhook, generic webhook URL, and/or SMTP
credentials, then set the matching enable flags in `group_vars/all.yml`
(see [examples/group_vars/all.yml.example](../examples/group_vars/all.yml.example)).
Notifications send automatically on the next run.

## Next steps

- [Configuration reference](configuration-reference.md) -- every setting,
  grouped by what it controls
- [Variable reference](variable-reference.md) -- every `linux_vitals_*`
  variable, its default, and which role owns it
- [Report guide](report-guide.md) -- how to read the dashboard and JSON
  output
- [Troubleshooting](troubleshooting.md)
