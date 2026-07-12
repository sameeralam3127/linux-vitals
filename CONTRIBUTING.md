# Contributing

Thanks for considering a contribution to LinuxVitals
(`sameeralam3127.linux_vitals`).

## Development setup

```bash
git clone https://github.com/sameeralam3127/linux-vitals.git
cd linux-vitals
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ansible-galaxy collection install -r requirements.yml
pre-commit install
```

`pytest -q` creates the `.dev-collections` symlink automatically if it's
missing. To run playbooks by hand, create it yourself first:

```bash
mkdir -p .dev-collections/ansible_collections/sameeralam3127
ln -s "$(pwd)" .dev-collections/ansible_collections/sameeralam3127/linux_vitals
```

See [docs/architecture.md](docs/architecture.md) before making structural
changes -- in particular, why the three roles share one variable namespace
and why report/`.env` paths resolve from `inventory_dir`.

## Running the checks

```bash
pre-commit run --all-files
ansible-lint roles/ playbooks/
ansible-playbook playbooks/healthcheck.yml --syntax-check
pytest -q
```

All four run in CI ([.github/workflows/ci.yml](.github/workflows/ci.yml))
on every push and pull request; a change isn't done until all four pass
locally.

## Adding or changing a variable

1. Add the default to the owning role's `defaults/main.yml` (see
   [docs/architecture.md](docs/architecture.md) for which role owns what).
2. Document it in [docs/variable-reference.md](docs/variable-reference.md)
   and, if it's something most users would touch, in
   [docs/configuration-reference.md](docs/configuration-reference.md).
3. Add or update a fixture in `tests/fixtures/` if the change affects
   template rendering, and an assertion in `tests/test_templates.py`.
4. Add a `CHANGELOG.md` entry under `[Unreleased]`.

## Changing the dashboard template

`roles/vitals_report/templates/dashboard.html.j2` is self-contained by
design -- no external CSS/JS, no CDN links, since it needs to open offline
and survive being emailed or copied around. Keep it that way. After any
change:

1. Run `pytest -q` (renders the template with representative fixture
   data and asserts on the output).
2. Extract and syntax-check the embedded `<script>` block:
   `node --check` on its contents catches JS typos pytest won't.
3. Render a realistic multi-host sample (mixed pass/fail, a
   baseline/postcheck comparison) and read through the output for
   balanced tags and no leaked `{{ }}` / `None` artifacts -- there's no
   automated visual regression test, so this is a manual step.

## Commit and PR conventions

- Keep commits scoped and the message focused on *why*, not just what
  changed line-by-line.
- Run the full check suite above before opening a PR.
- Update `CHANGELOG.md` under `[Unreleased]` for any user-visible change.

## Publishing to Ansible Galaxy

1. Bump `version` in [galaxy.yml](galaxy.yml) (semantic versioning) and
   move the `CHANGELOG.md` `[Unreleased]` section under the new version
   heading.
2. Run the full check suite, plus a local build/install smoke test:

   ```bash
   ansible-galaxy collection build
   ansible-galaxy collection install sameeralam3127-linux_vitals-*.tar.gz --force
   ansible-playbook -i examples/inventory/hosts.example.ini sameeralam3127.linux_vitals.healthcheck --syntax-check
   ```

3. Tag the release (`git tag vX.Y.Z && git push --tags`) and publish:

   ```bash
   ansible-galaxy collection publish sameeralam3127-linux_vitals-X.Y.Z.tar.gz --api-key <your-galaxy-api-key>
   ```

4. Verify on the [Galaxy collection page](https://galaxy.ansible.com/ui/repo/published/sameeralam3127/linux_vitals/)
   that the README, tags, and version rendered as expected.

`galaxy.yml`'s `build_ignore` already excludes dev-only files (`.github/`,
`.dev-collections/`, `venv/`, `inventory/`, `ansible.cfg`,
`requirements-dev.txt`, test caches) from the shipped tarball.
