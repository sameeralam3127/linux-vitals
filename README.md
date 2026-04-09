# Smart OS Health Check & Self-Healing

Enterprise-focused Ansible automation for Linux VM fleets running RHEL, Fedora, Ubuntu, and SUSE. The playbook discovers platform facts, validates runtime health, attempts one-shot self-healing for enabled failed services, builds a centralized HTML dashboard, and can push a single maintenance summary to Slack.

## What This Repo Does

- Discovers each host with `ansible.builtin.setup` and `service_facts`
- Evaluates RAM health with enterprise thresholds:
  - `Warning` at `80%`
  - `Critical` at `95%`
- Hunts recent `journalctl` entries containing `Error` or `Failed` from the last 30 minutes
- Validates core processes:
  - `sssd`
  - `systemd-journald`
  - `chronyd` or `ntp`
- Attempts one restart for any service that is both `enabled` and currently `failed`
- Records healing results as:
  - `Fixed`
  - `Failed to Fix`
  - `Manual Intervention Required`
- Generates a CSS-styled HTML dashboard
- Sends one Slack webhook summary for the full run
- Handles distro differences with `ansible_os_family` and package-manager context

## Repo Naming

The project branding has been refactored to **Smart OS Health Check & Self-Healing**.

Current role name:

```text
roles/smart_os_health_check
```

If you also want the physical Git folder or remote repository name changed from `ansible-server-health-dashboard`, that needs to be done in GitHub and/or the parent directory outside the playbook files.

## Requirements

- Python 3.10+
- Ansible Core 2.16+
- Linux targets using `systemd`

Install local tooling:

```bash
pip install ansible-core ansible-lint pre-commit
```

## Inventory Example

Edit [inventory/hosts.ini](/Users/sameeralam/Documents/GitHub/ansible-server-health-dashboard/inventory/hosts.ini):

```ini
[linux_servers]
rhel01 ansible_host=192.168.1.10
ubuntu01 ansible_host=192.168.1.11
fedora01 ansible_host=192.168.1.12
sles01 ansible_host=192.168.1.13

[linux_servers:vars]
ansible_user=automation
ansible_become=true
```

## Optional Variables

You can override these defaults in inventory, `group_vars`, or extra vars:

```yaml
smart_os_health_check_output_path: "{{ playbook_dir }}/reports/smart_os_health_report.html"
smart_os_health_check_log_window: "30 minutes ago"
smart_os_health_check_ram_warning_threshold: 80
smart_os_health_check_ram_critical_threshold: 95
smart_os_health_check_slack_webhook_url: "{{ lookup('ansible.builtin.env', 'SLACK_WEBHOOK_URL') | default('', true) }}"
```

## Slack Webhook via `.env`

Create a local `.env` file from [.env.example](/Users/sameeralam/Documents/GitHub/ansible-server-health-dashboard/.env.example):

```bash
cp .env.example .env
```

Add your webhook:

```bash
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/your/team/webhook"
```

Load it into your shell before running Ansible:

```bash
set -a
source .env
set +a
ansible-playbook -i inventory/hosts.ini site.yml
ansible-playbook -i inventory/hosts.ini smart_os_health_check.yml
```

If `SLACK_WEBHOOK_URL` is not set, the Slack task is skipped automatically.

## Run The Playbook

```bash
ansible-playbook -i inventory/hosts.ini smart_os_health_check.yml
```

## Output

HTML dashboard:

```text
reports/smart_os_health_report.html
```

Dashboard table columns:

- Hostname
- OS
- RAM Status
- Log Errors
- Services Healed
- Final Status

Slack summary format:

```text
Maintenance Summary: 50 Servers Checked, 2 Auto-Fixed, 1 Critical Error
```

## Quality Checks

Install hooks:

```bash
pre-commit install
```

Run validation:

```bash
pre-commit run --all-files
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote ansible-lint smart_os_health_check.yml
ansible-playbook -i inventory/hosts.ini smart_os_health_check.yml --syntax-check
```

## License

MIT
