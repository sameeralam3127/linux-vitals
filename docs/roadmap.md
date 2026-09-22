# Roadmap

A twelve-month plan for `sameeralam3127.linux_vitals`, built from the open
issue backlog. Every line links to the issue that tracks it -- this document
orders and groups work, it never describes work that has no issue.

**Board:** [LinuxVitals Roadmap](https://github.com/users/sameeralam3127/projects/6)
-- the same 28 issues, grouped by a `Quarter` field. The board is the thing you
drag cards around on; this file is where the *reasoning* lives.

Quarters run from October 2026. The ordering within each quarter is a
dependency order, not a priority order: where a cheap enabler unblocks several
larger items, it comes first even when its own priority label is lower.

The ordering *between* quarters follows one rule:

```
correctness -> scalability -> detection coverage -> integrations -> compliance -> contributors
```

New dashboard features must not outrun the correctness of the health model
underneath them. A check that is wrong is worth less than no check at all,
because a missing check is visible in the report and a wrong one is not; and a
check that is right but cannot run across a real fleet is a demo. Everything
below is an application of that ordering, which is also why the two least
glamorous items in the project -- a CI matrix and a status enum -- lead the
year.

| Quarter | Theme | Issues |
| --- | --- | --- |
| [Q1](#q1--trust-and-stability) (Oct-Dec 2026) | Trust and stability, plus the highest-value missing check | 9 |
| [Q2](#q2--breadth-of-detection) (Jan-Mar 2027) | Breadth of detection, and of tested platforms | 7 |
| [Q3](#q3--integrations-exports-and-security-depth) (Apr-Jun 2027) | Integrations, exports, and security posture depth | 9 |
| [Q4](#q4--refactors-tech-debt-and-contributors) (Jul-Sep 2027) | Refactors, tech debt, and external contributors | 3 |

## Releases

Quarters are planning buckets; releases are what people install. The intended
mapping, from 1.3.1:

| Release | Quarter | What it is |
| --- | --- | --- |
| **1.4 -- Trust** | Q1 | The report can be believed. Nothing new on the dashboard except filesystem capacity. |
| **1.5 -- Coverage** | Q2 | The report is complete, and the task tree is one a contributor can navigate. |
| **1.6 -- Observability** | Q3 (exports) | The data leaves the HTML file: OpenMetrics, CSV, pipeline exit status. |
| **1.7 -- Posture** | Q3 (security) + Q4 | Security depth, rule identifiers, and the maintainability work. |

These are targets, not commitments, and a quarter may ship as more than one
release. Two Q3/Q4 items have already landed ahead of their quarter --
[#52](https://github.com/sameeralam3127/linux-vitals/issues/52), which was going to
carry the Block Kit half of 1.6, and
[#63](https://github.com/sameeralam3127/linux-vitals/issues/63) -- so both will ship
in 1.4 instead. Pulling work forward is fine; what is not fine is pulling it
forward *past* Q1, which is why neither of them displaced anything in the
trust bucket. 1.4 is the one that matters: it is the release that decides whether
the project's central claim holds, and no feature in 1.5 or later is worth
reordering ahead of it.

## Q1 -- Trust and stability

The tool's core claim is that its report is true. Everything here is a case
where the report can currently be confidently wrong, or where a run cannot be
trusted to be safe. Nothing new is added to the dashboard this quarter except
the one check whose absence is hardest to defend.

| Item | Issue | Priority |
| --- | --- | --- |
| CI never tests the declared minimum ansible-core | [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) | high |
| Promote PASS/FAIL/UNKNOWN to a collection-wide finding contract | [#62](https://github.com/sameeralam3127/linux-vitals/issues/62) | high |
| Race between service restart and `service_facts` can report a dead service as "Fixed" | [#24](https://github.com/sameeralam3127/linux-vitals/issues/24) | high |
| Journal scans are unbounded and ship whole-window logs to the control node | [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) | high |
| Running with `--check` fails immediately on every host | [#38](https://github.com/sameeralam3127/linux-vitals/issues/38) | high |
| Failed-login check reports a clean host when `lastb` cannot run | [#39](https://github.com/sameeralam3127/linux-vitals/issues/39) | high |
| Fact cache has no explicit expiry, so a run can report stale facts | [#25](https://github.com/sameeralam3127/linux-vitals/issues/25) | medium |
| `notify.yml` send path, skip conditions, and `.env` precedence are untested | [#29](https://github.com/sameeralam3127/linux-vitals/issues/29) | medium |
| Add filesystem capacity and inode checks for all mounts | [#30](https://github.com/sameeralam3127/linux-vitals/issues/30) | high |

Ordering notes:

- [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) **leads the
  entire roadmap.** It is not a feature and it is not glamorous, but it is the
  only item here with a demonstrated track record: two total-failure bugs on
  the declared floor of ansible-core 2.16 ([#45] and [#49], both shipped in
  1.3.0/1.3.1) reached users through a fully green CI, and both were found by
  someone running the collection by hand rather than by any test. Until the
  declared floor is exercised, every other guarantee in this document is
  conditional on a version nobody tests.
- [#62](https://github.com/sameeralam3127/linux-vitals/issues/62) is second because
  the two items under it are both consumers of it. Today a finding exists only
  when something is wrong and `final_status` is `Pass` or `Fail`, so there is
  nowhere to record that a check *could not run* -- which is why a missing
  `lastb` reads as a clean host. Fixing that per-check leaves the schema with
  the same hole and the next check free to fall into it; fixing it in the
  finding object makes "unknown" expressible once, for every check, and gives
  contributors a rule to follow.
- [#24](https://github.com/sameeralam3127/linux-vitals/issues/24) and
  [#39](https://github.com/sameeralam3127/linux-vitals/issues/39) are the two
  places where the report actively asserts something false -- a dead service
  shown as auto-fixed, and an unchecked security control shown as clean. Those
  are worse than a missing check, because a missing check is visible. Both are
  the detection- and remediation-side applications of
  [#62](https://github.com/sameeralam3127/linux-vitals/issues/62): `FIXED` /
  `STILL_FAILED` / `UNKNOWN` on one side, `pass` / `fail` / `unknown` on the
  other, and neither can express its third state until the contract lands.
- [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) is the
  fleet-scale ceiling; it should land before any quarter that adds per-host
  data to the result object, which is all of Q2. The fix is structural rather
  than a tighter filter: the scan should return an aggregate
  (`error_count`, `critical_count`, `top_units`) with raw evidence opt-in and
  capped, so per-host fact size is roughly constant instead of scaling with
  log volume. A quiet host and a host in a crash loop should not cost
  different amounts to scan. Its schema change should be bundled with
  [#62](https://github.com/sameeralam3127/linux-vitals/issues/62)'s rather than
  bumping `schema_version` twice.
- [#30](https://github.com/sameeralam3127/linux-vitals/issues/30) is the one
  breadth item that does not wait for Q2. A full filesystem is the most common
  way a Linux host falls over, the data is already in `ansible_facts['mounts']`,
  and the collection currently uses that data for `/boot` alone. Scope note:
  capacity is not the whole check. Inode exhaustion, a root filesystem
  remounted read-only, and a missing expected mount are each a total failure
  that a percent-full threshold reports as healthy.

## Q2 -- Breadth of detection

With the report trustworthy, this quarter is about it being complete -- both
in what it checks and in where those checks are known to work. Two refactors
come first, because every item below them adds tasks to `vitals_scan`, and
adding them to the current structure compounds a known problem.

| Item | Issue | Priority |
| --- | --- | --- |
| Split the 1028-line `discovery.yml` into focused task files | [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) | medium |
| De-duplicate the required-service status map | [#28](https://github.com/sameeralam3127/linux-vitals/issues/28) | medium |
| Report all failed systemd units; make the required-service list configurable | [#32](https://github.com/sameeralam3127/linux-vitals/issues/32) | medium |
| Report pending package updates and pending security updates, per distro | [#31](https://github.com/sameeralam3127/linux-vitals/issues/31) | high |
| Check time-sync quality (offset, synchronised state), not just daemon liveness | [#33](https://github.com/sameeralam3127/linux-vitals/issues/33) | medium |
| Add CPU saturation, PSI pressure, and swap activity checks | [#34](https://github.com/sameeralam3127/linux-vitals/issues/34) | medium |
| Add Molecule scenarios for Debian 12 and Amazon Linux 2023 | [#64](https://github.com/sameeralam3127/linux-vitals/issues/64) | medium |

Ordering notes:

- [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) is pulled
  forward from the tech-debt theme deliberately. Four of the five items below
  it add tasks to `discovery.yml`; doing them first would mean splitting a file
  substantially larger than 1028 lines, and the tag-coverage bug that issue
  describes gets likelier with every task added.
- [#28](https://github.com/sameeralam3127/linux-vitals/issues/28) is the stated
  prerequisite for the configurable required-service list in
  [#32](https://github.com/sameeralam3127/linux-vitals/issues/32), so it
  immediately precedes it.
- [#31](https://github.com/sameeralam3127/linux-vitals/issues/31) carries a
  high priority but sits mid-quarter: it is the largest item here, and it
  benefits from the split landing first.
- [#64](https://github.com/sameeralam3127/linux-vitals/issues/64) closes the
  quarter rather than opening it, for two reasons. It depends on
  [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) having reworked
  the CI matrix -- widening the distro axis first means reworking it twice,
  and the axes multiply. And it is most valuable *after* the per-distro items
  above have landed, since [#31](https://github.com/sameeralam3127/linux-vitals/issues/31)
  adds a package-manager branch per distro and is exactly the kind of change
  a Debian 12 or Amazon Linux 2023 scenario exists to catch.

## Q3 -- Integrations, exports, and security depth

The data is now broad and trustworthy. This quarter is about getting it out of
the HTML file and deepening what it covers.

| Item | Issue | Priority |
| --- | --- | --- |
| ~~Render the Slack summary with Block Kit instead of one plain-text blob~~ | [#52](https://github.com/sameeralam3127/linux-vitals/issues/52) | done (unreleased) |
| ~~Add severity-based finding classification and alert thresholds~~ | [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) | done (unreleased) |
| Export the fleet report as OpenMetrics and CSV | [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) | medium |
| Add an opt-in non-zero exit so an unhealthy fleet can gate a pipeline | [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) | medium |
| Extend security posture: firewall, SSH hardening, kernel taint, deleted libraries | [#36](https://github.com/sameeralam3127/linux-vitals/issues/36) | medium |
| Make report and snapshot file modes configurable | [#61](https://github.com/sameeralam3127/linux-vitals/issues/61) | medium |
| Upload reports and snapshots to object storage; PagerDuty/Opsgenie payloads | [#65](https://github.com/sameeralam3127/linux-vitals/issues/65) | low |
| ~~Add `vitals_certs` role: TLS certificate expiry and hardening checks~~ | [#15](https://github.com/sameeralam3127/linux-vitals/issues/15) | done (unreleased) |
| Map findings to CIS or STIG rule identifiers for audit evidence | [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) | low |

Ordering notes:

- [#52](https://github.com/sameeralam3127/linux-vitals/issues/52) is done, out of
  quarter and ahead of everything above it. It was supposed to come before
  [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) and did not, and the
  cost that note predicted was paid exactly as predicted: the severity line
  and the "Needs attention first" list had been built as plain text in
  `slack_message.txt.j2`, and #52 rewrote them rather than wrapping them.

  The debt was one template, which is what the original note judged it would
  be, so the call to let #8 go first was the right one -- it unblocked three
  other items, and redoing one template cost less than reworking all three
  against a finding shape that had not landed.

  Worth recording for the next time this trade-off comes up: the rewrite also
  turned out to be where a real bug was found. The old template looped over
  every host uncapped, so a fleet of roughly 175+ produced a message past
  Slack's 40,000-character limit, refused with a bare HTTP 400 that `no_log`
  made nearly undiagnosable. That was a live defect nobody had filed, found
  only because the formatting work forced someone to read the loop.
- [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) is done. It
  changed the shape of a finding to `{id, message, severity}`, and the `id` is
  the join key the three items that consume it
  ([#35](https://github.com/sameeralam3127/linux-vitals/issues/35),
  [#36](https://github.com/sameeralam3127/linux-vitals/issues/36),
  [#43](https://github.com/sameeralam3127/linux-vitals/issues/43)) were
  waiting for. Doing it last would have meant reworking all three.
- [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) pairs with
  [#35](https://github.com/sameeralam3127/linux-vitals/issues/35): together
  they are what make the collection usable from a pipeline rather than from a
  terminal.
- [#65](https://github.com/sameeralam3127/linux-vitals/issues/65) sits behind
  [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) deliberately.
  OpenMetrics is the higher-value export by some distance -- it is what turns
  a run from "produces an HTML file" into trending and alerting in a stack the
  team already has, and for many teams it removes the reason to archive the
  HTML at all. Object storage is for the teams that need the artefact itself
  as evidence, plus the case #35 does not cover: baseline and postcheck run
  from two different ephemeral control nodes, where the baseline snapshot has
  to outlive the pod that wrote it.
- [#61](https://github.com/sameeralam3127/linux-vitals/issues/61) is grouped with
  the security items rather than with the export items, because it is about
  the same report the exports move around. `docs/threat-model.md` already
  documents that reports are written `0644` and describes their contents as
  "a fleet inventory cross-referenced with an unpatched-kernel list" -- the
  most sensitive artefact the project produces currently has its loosest
  default. It is a small change; it is here rather than in Q1 because it
  concerns the report's confidentiality, not its truth, and Q1 is about
  truth.
- [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) closes the
  quarter because it extends the finding object #8 introduced -- adding a
  `rule_id` alongside the existing `id` is now an additive change -- and
  because the CSV export is where rule identifiers become useful.

## Q4 -- Refactors, tech debt, and contributors

What is left is the work that makes the project maintainable by people who did
not write it.

| Item | Issue | Priority |
| --- | --- | --- |
| Concurrent runs sharing an output directory can corrupt reports and snapshots | [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) | low |
| ~~Add production-grade examples, screenshots, and an operator runbook~~ | [#6](https://github.com/sameeralam3127/linux-vitals/issues/6) | done (unreleased) |
| Split `render.yml` and de-duplicate the HTML/JSON archive sequence | [#27 (comment)](https://github.com/sameeralam3127/linux-vitals/issues/27#issuecomment-5644135601) | -- |
| ~~`vitals_certs` has no role README, unlike the other three roles~~ | [#63](https://github.com/sameeralam3127/linux-vitals/issues/63) | done (unreleased) |

Ordering notes:

- [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) is low
  priority but lands before
  [#6](https://github.com/sameeralam3127/linux-vitals/issues/6), because the
  operator runbook should document the final concurrency contract rather than
  the current undefined one.
- [#63](https://github.com/sameeralam3127/linux-vitals/issues/63) is done, and is
  the first change in this project written by someone other than the
  maintainer. It was filed as a documentation gap -- `vitals_certs` shipped in
  [#15](https://github.com/sameeralam3127/linux-vitals/issues/15) without the README
  the other three roles have -- and labelled `good first issue` on the theory
  that it was a reasonable first pull request for someone new.

  That theory held, with one correction worth keeping: the submitted page
  documented a variable name that does not exist, which review caught before
  it merged. A wrong variable name in a doc fails the same way a wrong health
  check does -- Ansible silently accepts an undefined variable, the real
  default stays in force, and nothing errors -- so it is the class of
  documentation bug this project should treat as a bug, not a typo.
- The `render.yml` split is the second half of the refactor started in
  [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) and is
  tracked on that issue rather than separately; at 341 lines it is the second
  largest task file, and its archive/prune sequence is written twice.
- [#6](https://github.com/sameeralam3127/linux-vitals/issues/6) was placed at
  the end of the year deliberately, because screenshots and a runbook age
  badly and the dashboard would have absorbed a year of changes by then. It
  landed early instead, and the ageing problem is addressed rather than
  deferred: the screenshots are regenerated from a real run by
  `demo/screenshots.sh` in one command, and the runbook is written against
  finding **ids** rather than message text, so rewording a finding does not
  invalidate it. What still ages is the advice itself, which is worth a read
  each time a check changes.

## Shipped

Closed since this roadmap was first written, in release order.

| Item | Issue | Released |
| --- | --- | --- |
| Add `meta/argument_specs.yml` for `ansible-doc` and runtime validation | [#40](https://github.com/sameeralam3127/linux-vitals/issues/40) | 1.3.0 |
| Pin an upper bound on collection dependencies | [#42](https://github.com/sameeralam3127/linux-vitals/issues/42) | 1.3.0 |
| Scan failed at `Build per-host report object` on ansible-core 2.16 | [#45](https://github.com/sameeralam3127/linux-vitals/issues/45) | 1.3.0 |
| `vitals_report` failed on ansible-core 2.16: `.env` regexes unparseable | [#49](https://github.com/sameeralam3127/linux-vitals/issues/49) | 1.3.1 |

Both 2.16 failures are the evidence behind
[#47](https://github.com/sameeralam3127/linux-vitals/issues/47)'s position at
the top of Q1: each was a total failure on a supported version, each passed CI,
and each was found by a user rather than a test.

## Keeping this current

This file and the [board](https://github.com/users/sameeralam3127/projects/6)
are maintained by hand, not generated. When an issue closes, move it to
**Shipped** here and to `Done` on the board in the same pull request. When a
new issue is opened that belongs to a quarter, add it to both -- an issue that
exists but appears in neither is the signal that the roadmap has drifted.

The same applies in the other direction, and it has bitten once already:
`vitals_certs` shipped as a fourth role and `docs/architecture.md` went on
describing three of them, down to a diagram labelled with a superseded
`schema_version`. When a change adds a role, a finding field, or a schema
version, `docs/architecture.md` is part of that change, not a follow-up.
