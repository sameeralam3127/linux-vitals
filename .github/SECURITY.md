# Security Policy

## Supported versions

LinuxVitals is released from `main` as a single line; fixes land in the next
release rather than being backported.

| Version | Supported |
| --- | --- |
| Latest release on [Ansible Galaxy](https://galaxy.ansible.com/ui/repo/published/sameeralam3127/linux_vitals/) | Yes |
| Anything older | No -- please upgrade before reporting |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/sameeralam3127/linux-vitals/security/advisories/new).
That opens a private advisory visible only to the maintainer. If you cannot
use it, email <sameeralam3127@gmail.com> with `linux-vitals security` in the
subject.

Please include:

- the collection version (`ansible-galaxy collection list sameeralam3127.linux_vitals`)
  and Ansible Core version;
- the target distribution, and whether the finding needs `become`;
- what an attacker gains, and the smallest reproduction you have.

What to expect:

- acknowledgement within 5 working days;
- an assessment, and a fix or a documented mitigation, within 30 days for
  anything confirmed as exploitable;
- credit in the advisory and `CHANGELOG.md` unless you ask otherwise.

This is a small, single-maintainer project. Those are honest targets, not an
SLA.

## What is in scope

LinuxVitals is an agentless Ansible collection. It runs read-only discovery
commands over SSH, optionally restarts already-enabled failed services, and
writes a report on the control node. Reports worth a private disclosure:

- **Command injection or privilege escalation on a managed host** -- anything
  where inventory data, facts, or variables reach a shell in a way a
  lower-privileged user on that host could influence.
- **Secret leakage.** Slack/webhook URLs, SMTP credentials, and `.env`
  contents must never reach a report, a log line, or a notification body.
  Notification config is loaded with `no_log`; a path that defeats that is a
  vulnerability.
- **Self-healing acting outside its contract** -- restarting a service that is
  not both enabled and failed, or acting at all when
  `linux_vitals_heal_enabled` is `false` (the default).
- **Report output that executes as code**, for example unescaped host-supplied
  data breaking out of the HTML dashboard into script context.
- **Supply-chain issues** in how the collection is built or published.

## What is out of scope

- Findings that require a compromised Ansible control node or an already-root
  attacker on the managed host -- LinuxVitals trusts both by design.
- The health findings themselves being wrong or noisy (a false "reboot
  required", a missed `needs-restarting`). Those are ordinary bugs: please
  open a normal issue. See
  [docs/kernel-reboot-detection.md](../docs/kernel-reboot-detection.md#known-edge-cases)
  for edge cases that are already documented.
- Vulnerabilities in Ansible Core, `community.general`, or the target
  distribution's own tooling. Report those upstream.
- The harnesses under `molecule/` and `demo/`, which run privileged containers
  on purpose and are shipped in neither the published collection nor any
  production path.

## Threat model

[docs/threat-model.md](../docs/threat-model.md) is the design-level companion to
this policy: trust boundaries, what `become` actually needs (and a narrow
sudoers rule that covers it), the exact contract self-healing operates under,
how the four credentials are handled, and what a generated report discloses
about your fleet. Read it before enabling self-healing or putting reports
somewhere shared.

## Security properties worth knowing

- `vitals_scan` is read-only. Every probe runs with `changed_when: false` and
  degrades to a documented "unavailable" answer rather than failing a run.
- `vitals_heal` is opt-in (`linux_vitals_heal_enabled: false` by default) and
  attempts at most one restart per service, only for units that are both
  enabled at boot and in a failed state.
- Reports and notifications are rendered on the control node, not on managed
  hosts. Managed hosts never receive credentials.
- The generated dashboard is self-contained by design: no CDN links, no
  external requests, so opening a report cannot phone home.
