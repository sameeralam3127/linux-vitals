# Installation

## Requirements

- Python 3.10+
- Ansible Core 2.16+ on the control node
- Linux targets using `systemd` (RHEL, Fedora, Ubuntu, SUSE families)
- SSH access from the control node to each managed host
- Privilege escalation (`become`) rights for checks that need root (journal
  reads, `getenforce`, boot partition stats, service restarts when
  self-healing is enabled)
- [`community.general`](https://galaxy.ansible.com/community/general)
  `>=9.0.0` (only needed if you enable email notifications, which use
  `community.general.mail`)

## From Ansible Galaxy

```bash
ansible-galaxy collection install sameeralam3127.linux_vitals
```

This installs the collection into your default collections path
(`~/.ansible/collections` unless overridden). From there you can run any of
the shipped playbooks by fully-qualified name from any project directory:

```bash
ansible-galaxy collection install -r requirements.yml   # community.general
ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck
```

Nothing about running it this way requires cloning this repository --
inventory, `group_vars`, and `.env` all live in *your* project directory
(see [Configuration reference](configuration-reference.md) for why paths
resolve relative to your inventory, not the installed package).

## From source, for local development

Clone the repo, then make it resolvable as
`sameeralam3127.linux_vitals` by symlinking it into a repo-local dev
collections root. `ansible.cfg`'s `collections_path` already points at
this location:

```bash
git clone https://github.com/sameeralam3127/linux-vitals.git
cd linux-vitals
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml

mkdir -p .dev-collections/ansible_collections/sameeralam3127
ln -s "$(pwd)" .dev-collections/ansible_collections/sameeralam3127/linux_vitals
```

`tests/test_templates.py` creates this symlink automatically if it's
missing, so `pytest -q` works on a fresh clone with no manual setup step --
the block above is for running playbooks by hand.

Why a repo-local symlink instead of one under `~/.ansible/collections`:
Ansible's `ANSIBLE_HOME` environment variable silently redirects where the
*default* collections path points (`$ANSIBLE_HOME/collections` instead of
`~/.ansible/collections`), which breaks FQCN role resolution if anything in
your shell or CI sets `ANSIBLE_HOME`. An explicit `collections_path` in
`ansible.cfg` sidesteps that entirely.

## Verify the install

```bash
ansible-doc -t collection -l | grep linux_vitals
ansible-playbook -i examples/inventory/hosts.example.ini playbooks/healthcheck.yml --syntax-check
```

## Building and installing a local tarball

To exercise the exact artifact that would ship to Galaxy:

```bash
ansible-galaxy collection build
ansible-galaxy collection install sameeralam3127-linux_vitals-*.tar.gz --force
```

See [Galaxy publishing](../CONTRIBUTING.md#publishing-to-ansible-galaxy)
for the full release process.
