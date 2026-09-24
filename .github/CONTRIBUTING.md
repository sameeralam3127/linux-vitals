# Contributing

Thanks for considering a contribution to LinuxVitals
(`sameeralam3127.linux_vitals`).

## Your first pull request

You do not need Docker, a lab, or any Linux hosts to make a useful first
change. Most of the test suite runs locally in about a minute, and CI does the
heavy part for you.

1. Pick an issue labelled
   [`good first issue`](https://github.com/sameeralam3127/linux-vitals/issues?q=is%3Aopen+label%3A%22good+first+issue%22).
   Each one has a comment listing the files to change and the test to add.
   Comment on the issue to claim it, and ask anything there.
2. Set up and run the quick loop:

   ```bash
   git clone https://github.com/<you>/linux-vitals.git && cd linux-vitals
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   ansible-galaxy collection install -r requirements.yml
   pytest -q                     # ~200 tests, no hosts involved
   pre-commit run --all-files    # lint, YAML, whitespace, shellcheck
   ```

3. Open the pull request. CI then runs what you could not run locally:
   Molecule against live systemd containers for Ubuntu, Rocky, Fedora, and
   openSUSE, and the whole suite again on the oldest ansible-core this
   collection supports. If one of those fails and the reason is not obvious,
   say so in the PR -- that is a normal part of review, not a failure on
   your part.

Add a line to `CHANGELOG.md` under `[Unreleased]` for anything a user would
notice. The rest of this document is reference for when you need it.

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

See [docs/architecture.md](../docs/architecture.md) before making structural
changes -- in particular, why the roles share one variable namespace
and why report/`.env` paths resolve from `inventory_dir`.

## Running the checks

```bash
pre-commit run --all-files
ansible-lint roles/ playbooks/ molecule/ demo/
ansible-playbook playbooks/healthcheck.yml --syntax-check
pytest -q
```

All four run in CI ([.github/workflows/ci.yml](workflows/ci.yml))
on every pull request; a change isn't done until all four pass locally.
CI runs them twice: on the newest ansible-core, and on 2.16, the minimum
declared in `meta/runtime.yml`. A change can pass locally on a new core and
still break 2.16 -- see
[docs/testing.md](../docs/testing.md#ansible-core-versions) for what that
usually looks like and how to run the 2.16 suite yourself.

On top of those, CI runs the Molecule scenarios -- one live systemd
container per supported distribution (Ubuntu, Rocky, Fedora, openSUSE) --
which are what prove the roles' runtime behaviour rather than just their
syntax. They need a Docker daemon, so they are not part of the quick loop
above:

```bash
molecule test -s ubuntu    # one distribution
molecule test --all        # all four
```

See [docs/testing.md](../docs/testing.md) for what each scenario covers, how to
debug a failing one, and what containers can't prove. Any change to
`vitals_scan` discovery, `vitals_heal`, or the report pipeline should be
validated with at least one scenario locally before pushing.

## Adding or changing a variable

1. Add the default to the owning role's `defaults/main.yml` (see
   [docs/architecture.md](../docs/architecture.md) for which role owns what).
2. Document it in that role's `meta/argument_specs.yml` with a `type`, a
   `default`, and a `description` -- this is what `ansible-doc -t role`
   renders and what validates an operator's override at role entry.
   `tests/test_argument_specs.py` fails if the spec and the defaults disagree.
   Do not mark it `required`: every variable must have a working default.
3. Document it in [docs/variable-reference.md](../docs/variable-reference.md)
   and, if it's something most users would touch, in
   [docs/configuration-reference.md](../docs/configuration-reference.md).
4. Add or update a fixture in `tests/fixtures/` if the change affects
   template rendering, and an assertion in `tests/test_templates.py`.
5. Add a `CHANGELOG.md` entry under `[Unreleased]`.

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

1. Bump `version` in [galaxy.yml](../galaxy.yml) (semantic versioning) and
   move the `CHANGELOG.md` `[Unreleased]` section under the new version
   heading.
2. Run the full check suite, plus a local build/install smoke test:

   ```bash
   ansible-galaxy collection build
   ansible-galaxy collection install sameeralam3127-linux_vitals-*.tar.gz --force
   ansible-playbook -i examples/inventory/hosts.example.ini sameeralam3127.linux_vitals.healthcheck --syntax-check
   ```

3. After the release PR is merged, tag the merge commit on `main` and push
   the tag:

   ```bash
   git tag -a vX.Y.Z -m "LinuxVitals X.Y.Z"
   git push origin vX.Y.Z
   ```

   The tag starts [.github/workflows/release.yml](workflows/release.yml),
   which refuses a tag that does not match `galaxy.yml`, re-runs the fast
   checks, builds, publishes to Galaxy, and confirms the version is live.
   There is no manual `ansible-galaxy collection publish` step and no API key
   on anyone's machine; the key is the repository's `API_KEY` secret.

4. Verify on the [Galaxy collection page](https://galaxy.ansible.com/ui/repo/published/sameeralam3127/linux_vitals/)
   that the README, tags, and version rendered as expected.

`galaxy.yml`'s `build_ignore` already excludes dev-only files (`.github/`,
`.dev-collections/`, `venv/`, `inventory/`, `ansible.cfg`,
`requirements-dev.txt`, test caches) from the shipped tarball.
