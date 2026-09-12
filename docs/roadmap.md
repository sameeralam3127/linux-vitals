# Roadmap

A twelve-month plan for `sameeralam3127.linux_vitals`, built from the open
issue backlog. Every line links to the issue that tracks it -- this document
orders and groups work, it never describes work that has no issue.

**Board:** [LinuxVitals Roadmap](https://github.com/users/sameeralam3127/projects/6)
-- the same 23 issues, grouped by a `Quarter` field. The board is the thing you
drag cards around on; this file is where the *reasoning* lives.

Quarters run from October 2026. The ordering within each quarter is a
dependency order, not a priority order: where a cheap enabler unblocks several
larger items, it comes first even when its own priority label is lower.

| Quarter | Theme | Issues |
| --- | --- | --- |
| [Q1](#q1--trust-and-stability) (Oct-Dec 2026) | Trust and stability, plus the highest-value missing check | 8 |
| [Q2](#q2--breadth-of-detection) (Jan-Mar 2027) | Breadth of detection | 6 |
| [Q3](#q3--integrations-exports-and-security-depth) (Apr-Jun 2027) | Integrations, exports, and security posture depth | 7 |
| [Q4](#q4--refactors-tech-debt-and-contributors) (Jul-Sep 2027) | Refactors, tech debt, and external contributors | 2 |

## Q1 -- Trust and stability

The tool's core claim is that its report is true. Everything here is a case
where the report can currently be confidently wrong, or where a run cannot be
trusted to be safe. Nothing new is added to the dashboard this quarter except
the one check whose absence is hardest to defend.

| Item | Issue | Priority |
| --- | --- | --- |
| CI never tests the declared minimum ansible-core | [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) | high |
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
- [#24](https://github.com/sameeralam3127/linux-vitals/issues/24) and
  [#39](https://github.com/sameeralam3127/linux-vitals/issues/39) are the two
  places where the report actively asserts something false -- a dead service
  shown as auto-fixed, and an unchecked security control shown as clean. Those
  are worse than a missing check, because a missing check is visible.
- [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) is the
  fleet-scale ceiling; it should land before any quarter that adds per-host
  data to the result object, which is all of Q2.
- [#30](https://github.com/sameeralam3127/linux-vitals/issues/30) is the one
  breadth item that does not wait for Q2. A full filesystem is the most common
  way a Linux host falls over, the data is already in `ansible_facts['mounts']`,
  and the collection currently uses that data for `/boot` alone.

## Q2 -- Breadth of detection

With the report trustworthy, this quarter is about it being complete. Two
refactors come first, because every item below them adds tasks to
`vitals_scan`, and adding them to the current structure compounds a known
problem.

| Item | Issue | Priority |
| --- | --- | --- |
| Split the 1028-line `discovery.yml` into focused task files | [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) | medium |
| De-duplicate the required-service status map | [#28](https://github.com/sameeralam3127/linux-vitals/issues/28) | medium |
| Report all failed systemd units; make the required-service list configurable | [#32](https://github.com/sameeralam3127/linux-vitals/issues/32) | medium |
| Report pending package updates and pending security updates, per distro | [#31](https://github.com/sameeralam3127/linux-vitals/issues/31) | high |
| Check time-sync quality (offset, synchronised state), not just daemon liveness | [#33](https://github.com/sameeralam3127/linux-vitals/issues/33) | medium |
| Add CPU saturation, PSI pressure, and swap activity checks | [#34](https://github.com/sameeralam3127/linux-vitals/issues/34) | medium |

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

## Q3 -- Integrations, exports, and security depth

The data is now broad and trustworthy. This quarter is about getting it out of
the HTML file and deepening what it covers.

| Item | Issue | Priority |
| --- | --- | --- |
| Render the Slack summary with Block Kit instead of one plain-text blob | [#52](https://github.com/sameeralam3127/linux-vitals/issues/52) | medium |
| Add severity-based finding classification and alert thresholds | [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) | medium |
| Export the fleet report as OpenMetrics and CSV | [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) | medium |
| Add an opt-in non-zero exit so an unhealthy fleet can gate a pipeline | [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) | medium |
| Extend security posture: firewall, SSH hardening, kernel taint, deleted libraries | [#36](https://github.com/sameeralam3127/linux-vitals/issues/36) | medium |
| Add `vitals_certs` role: TLS certificate expiry and hardening checks | [#15](https://github.com/sameeralam3127/linux-vitals/issues/15) | -- |
| Map findings to CIS or STIG rule identifiers for audit evidence | [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) | low |

Ordering notes:

- [#52](https://github.com/sameeralam3127/linux-vitals/issues/52) comes before
  [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) on purpose.
  Severity classification says it should be "reflected in HTML and Slack", but
  the Slack message is currently one plain-text blob with nowhere to put it.
  Building the Block Kit structure first gives severity somewhere to land;
  doing it second means rewriting the message twice.
- [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) then leads the
  rest, because it changes the shape of a finding and three later items
  ([#35](https://github.com/sameeralam3127/linux-vitals/issues/35),
  [#36](https://github.com/sameeralam3127/linux-vitals/issues/36),
  [#43](https://github.com/sameeralam3127/linux-vitals/issues/43)) consume that
  shape. Doing it last would mean reworking all three.
- [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) pairs with
  [#35](https://github.com/sameeralam3127/linux-vitals/issues/35): together
  they are what make the collection usable from a pipeline rather than from a
  terminal.
- [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) closes the
  quarter because it extends the finding object #8 introduces, and because the
  CSV export is where rule identifiers become useful.

## Q4 -- Refactors, tech debt, and contributors

What is left is the work that makes the project maintainable by people who did
not write it.

| Item | Issue | Priority |
| --- | --- | --- |
| Concurrent runs sharing an output directory can corrupt reports and snapshots | [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) | low |
| Add production-grade examples, screenshots, and an operator runbook | [#6](https://github.com/sameeralam3127/linux-vitals/issues/6) | medium |
| Split `render.yml` and de-duplicate the HTML/JSON archive sequence | [#27 (comment)](https://github.com/sameeralam3127/linux-vitals/issues/27#issuecomment-5644135601) | -- |

Ordering notes:

- [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) is low
  priority but lands before
  [#6](https://github.com/sameeralam3127/linux-vitals/issues/6), because the
  operator runbook should document the final concurrency contract rather than
  the current undefined one.
- The `render.yml` split is the second half of the refactor started in
  [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) and is
  tracked on that issue rather than separately; at 341 lines it is the second
  largest task file, and its archive/prune sequence is written twice.
- [#6](https://github.com/sameeralam3127/linux-vitals/issues/6) closes the year
  deliberately: screenshots and a runbook age badly, and by this point the
  dashboard has absorbed a year of changes.

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
