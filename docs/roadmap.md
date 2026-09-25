# Roadmap

The plan for `sameeralam3127.linux_vitals` from October 2026 to the end of
January 2027, built from the open issue backlog. Every line links to the issue
that tracks it -- this document orders and groups work, it never describes
work that has no issue.

**Board:** [LinuxVitals Roadmap](https://github.com/users/sameeralam3127/projects/6)
-- the same issues as cards. The board is the thing you drag cards around on;
this file is where the *reasoning* lives.

The plan ends in January on purpose. It was a twelve-month plan until
September 2026, and a year-long plan for a project with one maintainer is
mostly a list of things that will not happen in the order written. Four
months is short enough to be honest about. What does not fit is not spread
thinner across the months -- it is listed under
[Not before February 2027](#not-before-february-2027), with the reason, and
revisited then.

The ordering within each month is a dependency order, not a priority order:
where a cheap enabler unblocks several larger items, it comes first even when
its own priority label is lower. The ordering *between* months follows one
rule:

```
correctness -> scalability -> detection coverage -> integrations -> compliance -> contributors
```

New dashboard features must not outrun the correctness of the health model
underneath them. A check that is wrong is worth less than no check at all,
because a missing check is visible in the report and a wrong one is not; and a
check that is right but cannot run across a real fleet is a demo. Everything
below is an application of that ordering. It is also why the cut falls where it
does: integrations and compliance are the last two steps, so they are what
waits for February.

| Month | Theme | Release | Issues |
| --- | --- | --- | --- |
| [October 2026](#october-2026-ship-what-is-done-then-the-finding-contract) | Ship what is done; the finding contract | **2.1.0** (early October) | 4 |
| [November 2026](#november-2026-finish-trust-scale-and-safety) | Finish Trust: scale and safety | **2.2.0 -- Trust** (end of November) | 5 |
| [December 2026](#december-2026-artefacts-and-the-task-tree) | Artefacts and the task tree | -- | 4 |
| [January 2027](#january-2027-coverage-and-adoption) | Coverage and adoption | **2.3.0 -- Coverage** (end of January) | 4 |
| [Any month](#any-month-community-issues) | `good first issue`s, for whoever picks them up | next release | 2 |
| [Not before February 2027](#not-before-february-2027) | Integrations, exports, compliance, further breadth | -- | 5 |

## Releases

| Release | When | What it is |
| --- | --- | --- |
| **2.1.0** | early October | What is already merged: CI on the ansible-core 2.16 floor, the two 2.16 fixes it found, configurable report modes, and one shared service-status task. |
| **2.2.0 -- Trust** | end of November | The report can be believed. Nothing new on the dashboard except filesystem capacity. |
| **2.3.0 -- Coverage** | end of January | The report is more complete, the task tree is one a contributor can navigate, and the fleet-size claim is measured. |

2.1.0 ships now rather than waiting for Trust because it carries two fixes
users on the declared floor need today -- on ansible-core 2.16 the generic
webhook had never sent at all
([#85](https://github.com/sameeralam3127/linux-vitals/issues/85)) -- and
because [#61](https://github.com/sameeralam3127/linux-vitals/issues/61) added
variables, which makes the next release a minor one by semver. Trust therefore
moves from 2.1 to 2.2. The constraint from 2.0.0 is unchanged:
[#62](https://github.com/sameeralam3127/linux-vitals/issues/62)'s check status
and [#23](https://github.com/sameeralam3127/linux-vitals/issues/23)'s journal
aggregate must change the schema *additively*, so that Trust ships as 2.2 and
not 3.0. Both land in 2.2.0, so `schema_version` moves once.

**If a month slips**, the rule is fixed in advance rather than argued at the
time:

- **Trust items never drop.** If one is late, 2.2.0 moves; it does not ship
  without it. A release that claims the report can be believed while one of
  the known false-assurance bugs is still open would be worse than a late one.
- **Coverage items drop from the bottom of January** into
  [Not before February 2027](#not-before-february-2027), in this order:
  [#64](https://github.com/sameeralam3127/linux-vitals/issues/64),
  [#33](https://github.com/sameeralam3127/linux-vitals/issues/33),
  [#32](https://github.com/sameeralam3127/linux-vitals/issues/32). 2.3.0 ships
  at the end of January with whatever has landed.

## October 2026: Ship what is done, then the finding contract

The tool's core claim is that its report is true. October and November are
the cases where the report can currently be confidently wrong, or where a run
cannot be trusted to be safe. October starts with the one that everything
else builds on.

| Item | Issue | Priority |
| --- | --- | --- |
| ~~CI never tests the declared minimum ansible-core~~ | [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) | done -- ships in 2.1.0 |
| ~~Comparison RAM fields were strings on ansible-core 2.16~~ | [#81](https://github.com/sameeralam3127/linux-vitals/issues/81) | done -- ships in 2.1.0 |
| ~~Generic webhook never sent on ansible-core 2.16~~ | [#85](https://github.com/sameeralam3127/linux-vitals/issues/85) | done -- ships in 2.1.0 |
| ~~De-duplicate the required-service status map~~ | [#28](https://github.com/sameeralam3127/linux-vitals/issues/28) | done -- ships in 2.1.0 |
| ~~Make report and snapshot file modes configurable~~ | [#61](https://github.com/sameeralam3127/linux-vitals/issues/61) | done -- ships in 2.1.0 |
| Promote PASS/FAIL/UNKNOWN to a collection-wide finding contract | [#62](https://github.com/sameeralam3127/linux-vitals/issues/62) | high |
| Failed-login check reports a clean host when `lastb` cannot run | [#39](https://github.com/sameeralam3127/linux-vitals/issues/39) | high |
| Race between service restart and `service_facts` can report a dead service as "Fixed" | [#24](https://github.com/sameeralam3127/linux-vitals/issues/24) | high |
| Add filesystem capacity and inode checks for all mounts | [#30](https://github.com/sameeralam3127/linux-vitals/issues/30) | high |

Ordering notes:

- **2.1.0 goes out first**, before any new work, because what is merged
  already fixes users on the declared floor (see [Releases](#releases)).
- [#47](https://github.com/sameeralam3127/linux-vitals/issues/47) is done, and
  it earned its place at the top of the old plan the first time it ran: the
  suite had never executed on ansible-core 2.16, and doing so found two more
  total failures ([#81](https://github.com/sameeralam3127/linux-vitals/issues/81),
  [#85](https://github.com/sameeralam3127/linux-vitals/issues/85)) and a
  dependency that does not support the floor at all
  ([#86](https://github.com/sameeralam3127/linux-vitals/issues/86)). Every
  change from here is tested on 2.16 as well as the newest core.
- [#62](https://github.com/sameeralam3127/linux-vitals/issues/62) leads the new
  work because the two items under it are both consumers of it. Today a
  finding exists only when something is wrong and `final_status` is `Pass` or
  `Fail`, so there is nowhere to record that a check *could not run* -- which
  is why a missing `lastb` reads as a clean host. Fixing that per-check leaves
  the schema with the same hole and the next check free to fall into it;
  fixing it in the finding object makes "unknown" expressible once, for every
  check, and gives contributors a rule to follow. `docs/compatibility.md` --
  what counts as a breaking change, and the deprecation policy -- lands with
  it, because #62 is the first schema change that has to be checked against
  one.
- [#24](https://github.com/sameeralam3127/linux-vitals/issues/24) and
  [#39](https://github.com/sameeralam3127/linux-vitals/issues/39) are the two
  places where the report actively asserts something false -- a dead service
  shown as auto-fixed, and an unchecked security control shown as clean. Those
  are worse than a missing check, because a missing check is visible. Both are
  the detection- and remediation-side applications of
  [#62](https://github.com/sameeralam3127/linux-vitals/issues/62): `FIXED` /
  `STILL_FAILED` / `UNKNOWN` on one side, `pass` / `fail` / `unknown` on the
  other, and neither can express its third state until the contract lands.
- [#30](https://github.com/sameeralam3127/linux-vitals/issues/30) is the one
  breadth item in the Trust release. A full filesystem is the most common way
  a Linux host falls over, the data is already in `ansible_facts['mounts']`,
  and the collection currently uses that data for `/boot` alone. Scope note:
  capacity is not the whole check. Inode exhaustion, a root filesystem
  remounted read-only, and a missing expected mount are each a total failure
  that a percent-full threshold reports as healthy. Per-mount findings must
  carry the mount as `subject`, or the baseline/postcheck comparison cannot
  tell a newly full `/home` from an already full `/var`
  ([#77](https://github.com/sameeralam3127/linux-vitals/issues/77)).

## November 2026: Finish Trust, scale and safety

The rest of Trust: the run must be safe to point at a real fleet, and the
parts of it that handle credentials must be tested. **2.2.0 -- Trust** ships at
the end of the month.

| Item | Issue | Priority |
| --- | --- | --- |
| Journal scans are unbounded and ship whole-window logs to the control node | [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) | high |
| Running with `--check` fails immediately on every host | [#38](https://github.com/sameeralam3127/linux-vitals/issues/38) | high |
| Fact cache has no explicit expiry, so a run can report stale facts | [#25](https://github.com/sameeralam3127/linux-vitals/issues/25) | medium |
| `notify.yml` send path, skip conditions, and `.env` precedence are untested | [#29](https://github.com/sameeralam3127/linux-vitals/issues/29) | medium |
| Add an opt-in non-zero exit so an unhealthy fleet can gate a pipeline | [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) | medium |

Ordering notes:

- [#23](https://github.com/sameeralam3127/linux-vitals/issues/23) is the
  fleet-scale ceiling; it lands before any month that adds per-host data to
  the result object. The fix is structural rather than a tighter filter: the
  scan should return an aggregate (`error_count`, `critical_count`,
  `top_units`) with raw evidence opt-in and capped, so per-host fact size is
  roughly constant instead of scaling with log volume. A quiet host and a host
  in a crash loop should not cost different amounts to scan. It ships in the
  same release as [#62](https://github.com/sameeralam3127/linux-vitals/issues/62),
  so `schema_version` moves once.
- [#38](https://github.com/sameeralam3127/linux-vitals/issues/38) is what
  makes a health check safe to try: a `--check` run is the first thing a
  cautious operator does against production, and today it fails on every
  host.
- [#29](https://github.com/sameeralam3127/linux-vitals/issues/29) is the only
  path in the collection that handles secrets, and it is untested. The
  redaction tests prove what it does not print; this proves what it sends.
- [#41](https://github.com/sameeralam3127/linux-vitals/issues/41) is pulled
  forward from the old Q3. It is small, and it is the prerequisite for anyone
  wiring the collection into CI or AWX: without a non-zero exit, an unhealthy
  fleet produces a green job. It comes after
  [#62](https://github.com/sameeralam3127/linux-vitals/issues/62) so it can
  gate on `unknown` too, and its variable needs a name that cannot be
  confused with the existing `linux_vitals_fail_on_severity`, which decides
  whether a *host* fails rather than whether the *play* does.

## December 2026: Artefacts and the task tree

December is short, so it carries nothing that changes the report's schema and
nothing a release waits on. It is the maintainability work that makes
January's detection items cheaper to add and easier for someone else to
review.

| Item | Issue | Priority |
| --- | --- | --- |
| Concurrent runs sharing an output directory can corrupt reports and snapshots | [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) | low |
| Split the 978-line `discovery.yml` into focused task files | [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) | medium |
| Static analysis raises ~40 findings; most are intentional and nothing records why | [#72](https://github.com/sameeralam3127/linux-vitals/issues/72) | medium |
| Report all failed systemd units; make the required-service list configurable | [#32](https://github.com/sameeralam3127/linux-vitals/issues/32) | medium |

Ordering notes:

- [#26](https://github.com/sameeralam3127/linux-vitals/issues/26) was planned
  to land before the operator runbook
  ([#6](https://github.com/sameeralam3127/linux-vitals/issues/6)) so the
  runbook would document the final concurrency contract. The runbook shipped
  first, in 2.0.0, so it currently describes the undefined behaviour. #26
  therefore includes updating `docs/runbook.md` with the contract it
  establishes -- a second run waits or fails clearly, and reports and
  snapshots are written atomically.
- [#27](https://github.com/sameeralam3127/linux-vitals/issues/27) comes before
  January deliberately. Both of January's detection items add tasks to
  `discovery.yml`; doing them first would mean splitting a larger file, and
  the tag-coverage bug that issue describes gets likelier with every task
  added. The `render.yml` split (363 lines, with its archive/prune sequence
  written twice) is the second half of the same refactor and is tracked on
  [that issue](https://github.com/sameeralam3127/linux-vitals/issues/27#issuecomment-5644135601)
  rather than separately. It is in scope here only if it stays cheap;
  otherwise it waits for February.
- [#72](https://github.com/sameeralam3127/linux-vitals/issues/72) records a
  decision for each static-analysis finding, so the next scan does not
  re-raise ones that were intentional. It pairs with
  [#74](https://github.com/sameeralam3127/linux-vitals/issues/74), whose
  `--only-binary` half is a `good first issue`.
- [#32](https://github.com/sameeralam3127/linux-vitals/issues/32) builds on
  [#28](https://github.com/sameeralam3127/linux-vitals/issues/28), which
  replaced the two copies of the required-service map with one shared
  `roles/vitals_scan/tasks/services.yml`. The configurable list is one change
  to that task instead of two.

## January 2027: Coverage and adoption

The report becomes more complete, the tested platforms wider, and the
fleet-size claim measured rather than asserted. **2.3.0 -- Coverage** ships at
the end of the month with whatever has landed.

| Item | Issue | Priority |
| --- | --- | --- |
| Report pending package updates and pending security updates, per distro | [#31](https://github.com/sameeralam3127/linux-vitals/issues/31) | high |
| Check time-sync quality (offset, synchronised state), not just daemon liveness | [#33](https://github.com/sameeralam3127/linux-vitals/issues/33) | medium |
| Fill in `docs/performance.md` with measured fleet-size results | [#84](https://github.com/sameeralam3127/linux-vitals/issues/84) | medium |
| Add Molecule scenarios for Debian 12 and Amazon Linux 2023 | [#64](https://github.com/sameeralam3127/linux-vitals/issues/64) | medium |

Ordering notes:

- [#31](https://github.com/sameeralam3127/linux-vitals/issues/31) is the
  largest item in the plan and leads the month: "is this host patched?" is
  one of the first questions an evaluator asks, and the baseline/postcheck
  workflow is built around patch windows. Stale package metadata must read as
  `unknown`, not as zero updates -- the #62 contract applies.
- [#33](https://github.com/sameeralam3127/linux-vitals/issues/33): a running
  time-sync daemon that is not synchronised passes today, and clock skew is
  exactly what breaks Kerberos, TLS and log correlation after a maintenance
  window changes firewall or NTP configuration.
- [#84](https://github.com/sameeralam3127/linux-vitals/issues/84) runs *after*
  [#23](https://github.com/sameeralam3127/linux-vitals/issues/23), which is
  expected to change journal cost the most, so the numbers describe the
  collection users will actually run. It is also what allows the README to
  state a tested fleet size at all. A real-fleet data point is the kind of
  contribution a user can make without writing code.
- [#64](https://github.com/sameeralam3127/linux-vitals/issues/64) closes the
  month rather than opening it. It is most valuable *after*
  [#31](https://github.com/sameeralam3127/linux-vitals/issues/31), which adds a
  package-manager branch per distribution and is exactly the kind of change a
  Debian 12 or Amazon Linux 2023 scenario exists to catch. It is also the first
  item to move to February if the month runs short.

## Any month: community issues

Labelled `good first issue`, each with a comment listing the files to change
and the test to add. They ship in whichever release is next. Both outside
contributions before these came from issues labelled this way, so the aim is
to keep two to four open at all times rather than to schedule them.

| Item | Issue | Size |
| --- | --- | --- |
| Tell users on ansible-core 2.16 to use `community.general` 11 | [#86](https://github.com/sameeralam3127/linux-vitals/issues/86) | small |
| Install CI tooling with `--only-binary` (the lockfile half stays with the maintainer) | [#74](https://github.com/sameeralam3127/linux-vitals/issues/74) | small |

## Not before February 2027

These are real and worth doing, but they are the integration and compliance
end of the ordering rule, and each is medium to large. Keeping them out is what
keeps the January date honest. They are revisited in February, in this order.

| Item | Issue | Priority |
| --- | --- | --- |
| Export the fleet report as OpenMetrics and CSV | [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) | medium |
| Extend security posture: firewall, SSH hardening, kernel taint, deleted libraries | [#36](https://github.com/sameeralam3127/linux-vitals/issues/36) | medium |
| Add CPU saturation, PSI pressure, and swap activity checks | [#34](https://github.com/sameeralam3127/linux-vitals/issues/34) | medium |
| Upload reports and snapshots to object storage; PagerDuty/Opsgenie payloads | [#65](https://github.com/sameeralam3127/linux-vitals/issues/65) | low |
| Map findings to CIS or STIG rule identifiers for audit evidence | [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) | low |

Notes for February:

- [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) is first in
  line. OpenMetrics is the higher-value export by some distance -- it turns a
  run from "produces an HTML file" into trending and alerting in a stack the
  team already has. It pairs with
  [#41](https://github.com/sameeralam3127/linux-vitals/issues/41), which lands
  in November: together they make the collection usable from a pipeline rather
  than from a terminal.
- [#34](https://github.com/sameeralam3127/linux-vitals/issues/34) is detection
  breadth, but after [#31](https://github.com/sameeralam3127/linux-vitals/issues/31)
  and [#33](https://github.com/sameeralam3127/linux-vitals/issues/33): pending
  updates and clock skew are the gaps evaluators notice first.
- [#65](https://github.com/sameeralam3127/linux-vitals/issues/65) sits behind
  [#35](https://github.com/sameeralam3127/linux-vitals/issues/35) deliberately.
  Object storage is for the teams that need the artefact itself as evidence,
  plus the case #35 does not cover: baseline and postcheck run from two
  different ephemeral control nodes, where the baseline snapshot has to
  outlive the pod that wrote it.
- [#43](https://github.com/sameeralam3127/linux-vitals/issues/43) comes last
  because it extends the finding object
  [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) introduced --
  adding a `rule_id` alongside the existing `id` is an additive change -- and
  because the CSV export is where rule identifiers become useful.
- Whether reports and snapshots should default to `0640`/`0750` rather than
  `0644`/`0755` -- the open half of
  [#61](https://github.com/sameeralam3127/linux-vitals/issues/61) -- is a
  breaking change, and is decided under `docs/compatibility.md` once #62 has
  written it.

## Shipped

Closed since this roadmap was first written, in release order.

| Item | Issue | Released |
| --- | --- | --- |
| Add `meta/argument_specs.yml` for `ansible-doc` and runtime validation | [#40](https://github.com/sameeralam3127/linux-vitals/issues/40) | 1.3.0 |
| Pin an upper bound on collection dependencies | [#42](https://github.com/sameeralam3127/linux-vitals/issues/42) | 1.3.0 |
| Scan failed at `Build per-host report object` on ansible-core 2.16 | [#45](https://github.com/sameeralam3127/linux-vitals/issues/45) | 1.3.0 |
| `vitals_report` failed on ansible-core 2.16: `.env` regexes unparseable | [#49](https://github.com/sameeralam3127/linux-vitals/issues/49) | 1.3.1 |
| Add severity-based finding classification and alert thresholds | [#8](https://github.com/sameeralam3127/linux-vitals/issues/8) | 2.0.0 |
| Add `vitals_certs` role: TLS certificate expiry and hardening checks | [#15](https://github.com/sameeralam3127/linux-vitals/issues/15) | 2.0.0 |
| Add production-grade examples, screenshots, and an operator runbook | [#6](https://github.com/sameeralam3127/linux-vitals/issues/6) | 2.0.0 |
| Render the Slack summary with Block Kit instead of one plain-text blob | [#52](https://github.com/sameeralam3127/linux-vitals/issues/52) | 2.0.0 |
| `vitals_certs` has no role README, unlike the other three roles | [#63](https://github.com/sameeralam3127/linux-vitals/issues/63) | 2.0.0 |
| Postcheck comparison hid newly failed services and mis-diffed 1.x baselines | [#77](https://github.com/sameeralam3127/linux-vitals/issues/77) | 2.0.0 |

Both 2.16 failures ([#45](https://github.com/sameeralam3127/linux-vitals/issues/45),
[#49](https://github.com/sameeralam3127/linux-vitals/issues/49)) are the
evidence behind [#47](https://github.com/sameeralam3127/linux-vitals/issues/47):
each was a total failure on a supported version, each passed CI, and each was
found by a user rather than a test.

Items marked *done* in the month tables above move here when the release that
carries them is published.

### Notes on shipped work

Kept because each records a trade-off worth remembering the next time it
comes up.

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

## Keeping this current

This file and the [board](https://github.com/users/sameeralam3127/projects/6)
are maintained by hand, not generated. When an issue closes, mark it done in
its month here and move it to `Done` on the board in the same pull request;
when its release is published, move it to **Shipped**. When a new issue is
opened, add it to a month or to
[Not before February 2027](#not-before-february-2027) -- an open issue that
appears nowhere in this file is the signal that the roadmap has drifted.
[#82](https://github.com/sameeralam3127/linux-vitals/issues/82) and
[#83](https://github.com/sameeralam3127/linux-vitals/issues/83) duplicate
[#31](https://github.com/sameeralam3127/linux-vitals/issues/31) and
[#33](https://github.com/sameeralam3127/linux-vitals/issues/33) and are
tracked there.

The same applies in the other direction, and it has bitten once already:
`vitals_certs` shipped as a fourth role and `docs/architecture.md` went on
describing three of them, down to a diagram labelled with a superseded
`schema_version`. When a change adds a role, a finding field, or a schema
version, `docs/architecture.md` is part of that change, not a follow-up.

In February, this plan is replaced by the next one rather than extended: what
is left over is re-ordered against whatever has been learned by then.
