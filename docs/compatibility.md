# Compatibility

What `sameeralam3127.linux_vitals` promises not to break, how a release says
when it does, and how something is retired. It applies to every change from
2.2.0 on. What counts as breaking is how earlier releases were already
judged, written down so the next decision is checked rather than argued; the
deprecation steps are new with this document.

## Versions

The collection follows [semantic versioning](https://semver.org/):

- **Major** (`3.0.0`): something below changes in a way an existing user
  has to act on. The CHANGELOG entry opens with who is affected and the
  step each takes before upgrading, and names the `requirements.yml` pin
  that keeps them on the previous major -- as
  [2.0.0](../CHANGELOG.md#200---2026-09-24) did.
- **Minor** (`2.2.0`): new behaviour that is off by default or does not
  change any existing outcome -- a new variable whose default keeps the old
  behaviour, a new report field, a new finding.
- **Patch** (`2.1.1`): fixes only.

The JSON report carries its own `schema_version`, versioned the same way and
independently of the collection. An additive schema change moves the minor
(`2.0` to `2.1`); a breaking one moves the major, and the collection's major
moves with it.

## The public interface

These are what a user or a downstream system builds on.

| Interface | Where it is defined |
| --- | --- |
| Role variables: names, accepted values, and what their defaults do | each role's `meta/argument_specs.yml`; [variable-reference.md](variable-reference.md) |
| The JSON report, the generic webhook payload, and the `linux_vitals_result` host fact | [report-guide.md](report-guide.md) |
| Finding `id`s, and the finding contract (`status`, `reason`) | [report-guide.md](report-guide.md#findings); [architecture.md](architecture.md#the-finding-object-and-the-finding-contract) |
| Playbook names and the role names, by FQCN | `playbooks/`, `roles/` |
| Supported ansible-core versions | `meta/runtime.yml` |

Not part of it: the HTML dashboard's layout, the wording of a finding's
`message`, the text of the Slack and email messages, task names, and internal
facts other than `linux_vitals_result`. These can change in any release.

## What counts as breaking

A change is breaking when an existing user, changing nothing, gets a
different outcome they did not opt into, or a consumer reading the outputs
misreads them. In particular:

- **Removing or renaming** a variable, a report field, a finding `id`, a
  playbook, or a role.
- **Changing the type or meaning of a field.** 2.0.0's findings changing
  from strings to objects was breaking for that reason.
- **Adding a value to an existing enumerated field**, such as a third
  `final_status`. A consumer that branches on the values it knows -- `if
  status == "Fail"` -- silently misreads the new one, which is worse than a
  missing field. This is why #62 added `unknown_count` alongside
  `final_status` rather than an `Unknown` status.
- **Changing a default so that the outcome changes** for anyone who has not
  set the variable -- for example tightening report file modes from
  `0644`/`0755` to `0640`/`0750`, which can lock out a reader that works
  today ([#61](https://github.com/sameeralam3127/linux-vitals/issues/61)).
- **Raising the ansible-core floor** in `meta/runtime.yml`
  ([#86](https://github.com/sameeralam3127/linux-vitals/issues/86)).

Not breaking:

- **Adding** a variable whose default keeps the existing behaviour, a field,
  a finding `id`, or a role that is off by default.
- **A new check firing on a host it did not fire on before.** Finding
  problems is the collection's job, and a host that newly fails because a new
  check found something is the release working. It is listed under *Added*.
- **Fixing behaviour that never worked**, such as `vitals_scan` refusing
  `--check`, which had always failed on every host (#38).
- **Making a field's type consistent across ansible-core versions** when one
  core already returned the documented type, as #81 did for the comparison's
  RAM fields. The CHANGELOG still says so at the top of the entry, because a
  consumer may have adapted to the wrong type.

When a change is borderline, the CHANGELOG entry says who could notice and
what they would do, whichever way it is classified.

## Deprecation

Removing something follows three steps, so nobody meets a removal they were
not warned about:

1. **Deprecate in a minor release.** The CHANGELOG lists it under
   *Deprecated*, with what to use instead. A variable's `argument_specs.yml`
   description starts with `Deprecated:`, and a replacement, where there is
   one, works from the same release.
2. **Keep it working for at least one further minor release.**
3. **Remove it only in a major release**, listed with its upgrade step at
   the top of that release's CHANGELOG entry.
