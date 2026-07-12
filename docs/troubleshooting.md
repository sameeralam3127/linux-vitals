# Troubleshooting

**`ansible-playbook sameeralam3127.linux_vitals.healthcheck` can't find the
collection.**
Confirm it's installed (`ansible-galaxy collection list | grep linux_vitals`)
or, for local development, that `.dev-collections/ansible_collections/sameeralam3127/linux_vitals`
exists and symlinks to this repo (see
[installation.md](installation.md#from-source-for-local-development)). If
your shell or CI sets `ANSIBLE_HOME`, note that it silently redirects
Ansible's *default* collections path -- an explicit `collections_path` in
`ansible.cfg` (already set in this repo) avoids that, but a custom
`ANSIBLE_CONFIG` pointing elsewhere can still shadow it.

**`reports/` is missing after a run.**
Report files are generated next to your inventory (`inventory_dir`) and are
gitignored -- run the playbook once and look there, not in the collection's
own install path.

**A `baseline` or `postcheck` run fails with "linux_vitals_maintenance_id is
required".**
Both phases need `-e linux_vitals_maintenance_id=<id>`; the id has no
sensible default because it's what correlates a baseline with its
postcheck. Reuse the exact same id for both runs.

**The dashboard shows every `postcheck` host as "New" with no comparison.**
The baseline snapshot wasn't found. Check that
`linux_vitals_snapshot_dir/<maintenance_id>/baseline/<hostname>.json`
exists (default `reports/snapshots/...`) and that the maintenance id and
`inventory_hostname` match exactly between the two runs.

**Slack / generic webhook notifications don't send.**
Confirm the matching webhook URL resolves from inventory, `group_vars`,
extra vars, or `.env` (which must be next to your inventory, not this
repo, once you're running from an installed collection). A blank/unset URL
means that channel is silently skipped, not an error.

**Email doesn't send.**
Confirm `linux_vitals_email_enabled: true`, at least one entry in
`linux_vitals_email_to`, valid SMTP settings, and that
`community.general` is installed (`ansible-galaxy collection install -r
requirements.yml`).

**A tagged run skips expected output.**
Include `reporting` with your focused tags -- e.g.
`--tags discovery,kernel,reporting` -- since dashboard/JSON generation only
runs under the `reporting` tag. `include_tasks: ... apply: tags: [...]`
means most tasks inherit a broad tag automatically, but the config-loading
step is tagged `always` specifically so notification configuration still
resolves even on a narrow `--tags` run.

**Ansible writes temp-file permission errors.**
Run with writable temp paths, e.g.:

```bash
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote \
  ansible-playbook -i inventory.ini sameeralam3127.linux_vitals.healthcheck
```

**Bootloader validation shows "not available on this host".**
This is expected on hosts without GRUB (some cloud images boot via direct
kernel/EFI stub), or if none of `grubby`, `grub2-editenv`/`grub-editenv`,
or `/etc/default/grub` are present/readable. It degrades gracefully rather
than failing the run.

**A finding fires that you don't expect.**
See [report-guide.md#findings](report-guide.md#findings) for the exact
list of conditions and which threshold/variable controls each one.
