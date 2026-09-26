# Collected state schema (`state_schema: 1`)

> **Status: specification, not yet implemented.** Nothing in the collection
> emits this document today. It is the contract the collection/evaluation
> refactor ([#98](https://github.com/sameeralam3127/linux-vitals/issues/98))
> builds against, written before the tasks that produce it, and it is what
> `tests/fixtures/state/` will encode. The shipped report keeps its own
> `schema_version: 2.0` — the two version independently, which is the point
> of separating them.

One JSON document per host, produced by the **collect** layer. It records
what was observed. It contains no thresholds, no pass/fail, no severity, and
no finding. Everything needed to decide those lives here; the deciding
happens in the **evaluate** layer, against
[`docs/internal/finding-inventory.md`](internal/finding-inventory.md).

## The rule that shapes everything else

**"The probe could not run" and "the probe found nothing" are different
states and must never collapse into the same JSON.**

Today they do collapse, and four findings silently read as a pass when their
input is missing (NOTES 1 in the finding inventory). Every probe below
therefore carries `ran`, `rc`, and `unsupported_reason` alongside its output.
That is what lets the evaluator return `unknown`
([#62](https://github.com/sameeralam3127/linux-vitals/issues/62)) without a
schema bump — the data is already there, nothing is judging it yet.

## Shape

```json
{
  "state_schema": 1,
  "collected_at": "2026-09-26T14:02:11Z",
  "host": {
    "inventory_hostname": "web-01",
    "hostname": "web-01",
    "ip_address": "10.0.3.11",
    "product_serial": "unavailable"
  },
  "platform": {
    "os_family": "Debian",
    "distribution": "Ubuntu",
    "distribution_version": "24.04",
    "kernel": "6.8.0-45-generic",
    "service_mgr": "systemd",
    "uptime_seconds": 184020,
    "virtualization_type": "docker",
    "virtualization_role": "guest"
  },
  "memory": {
    "total_mb": 7938.0,
    "available_mb": 5120.0,
    "free_mb": 3011.0
  },
  "mounts": [
    {"mount": "/boot", "size_available": 201326592, "size_total": 1063256064}
  ],
  "services": {
    "systemd-journald.service": {"state": "running", "status": "enabled"},
    "ssh.service": {"state": "running", "status": "enabled"}
  },
  "probes": {
    "logs": {
      "ran": true, "rc": 0,
      "window": "30 minutes ago",
      "stdout": "2026-09-26T13:58:02+0000 web-01 kernel: ..."
    },
    "audit_logs": {
      "ran": true, "rc": 0,
      "window": "7 days ago",
      "stdout": ""
    },
    "failed_logins":   {"ran": true, "rc": 0, "stdout_lines": []},
    "last_reboot":     {"ran": true, "rc": 0, "stdout": "system boot  2026-09-24 10:03"},
    "installed_kernels": {
      "ran": true, "rc": 0,
      "latest": "6.8.0-45-generic",
      "updated_at": "2026-09-01 04:11:07.000000000 +0000",
      "filtered": true
    },
    "bootloader": {
      "ran": true, "rc": 0,
      "supported": true, "source": "grub-editenv",
      "default_entry": "Ubuntu", "default_kernel": "6.8.0-45-generic",
      "status": "resolved"
    },
    "reboot_required": {
      "ran": true, "rc": 0,
      "supported": true, "detected": false,
      "source": "reboot-required-file", "detail": "", "packages": []
    },
    "selinux":  {"ran": true, "rc": 127, "stdout": "", "unsupported_reason": "getenforce not found"},
    "apparmor": {"ran": true, "rc": 0},
    "rescue_images": {"ran": true, "rc": 0, "stdout_lines": []}
  },
  "healing": null,
  "certificates": null
}
```

## Fields

### `host`, `platform`

Straight from `ansible.builtin.setup` (subsets `min`, `hardware`, `network`,
`virtual`). Copied verbatim; no defaulting, no normalisation.

| Field | Source fact | Consumed by |
| --- | --- | --- |
| `host.inventory_hostname` | Ansible inventory | report identity |
| `host.hostname` | `ansible_facts.hostname` | report identity |
| `host.ip_address` | `ansible_facts.default_ipv4.address` | report identity |
| `host.product_serial` | `ansible_facts.product_serial` | report identity |
| `platform.os_family` | `ansible_facts.os_family` | `selinux_disabled`, `apparmor_disabled`, reboot-probe selection |
| `platform.distribution`, `.distribution_version` | same-named facts | report identity |
| `platform.kernel` | `ansible_facts.kernel` | `kernel_not_latest`, `reboot_required` fallback |
| `platform.service_mgr` | `ansible_facts.service_mgr` | whether the log probes could run |
| `platform.uptime_seconds` | `ansible_facts.uptime_seconds` | report only |
| `platform.virtualization_type`, `.virtualization_role` | same-named facts | report only |

Note `ip_address`, `hostname` and `product_serial` are the only fields
carrying a per-host default today (`unavailable`, `inventory_hostname`).
Defaulting moves to the render layer; collect writes `null` when the fact is
absent.

### `memory`

Raw megabytes only. **`ram_used_pct` is not in this document** — it is
arithmetic the evaluator performs, and `ram_status` is a threshold decision
that has no business in collect.

| Field | Source fact |
| --- | --- |
| `memory.total_mb` | `ansible_facts.memtotal_mb` |
| `memory.available_mb` | `ansible_facts.memavailable_mb`, `null` when absent |
| `memory.free_mb` | `ansible_facts.memfree_mb` |

The current fallback (`memavailable_mb` defaulting to `memfree_mb`) is
evaluator policy, so both values are recorded and neither is chosen here.

### `mounts`

Entries from `ansible_facts.mounts` whose `mount` is `/boot` or `/boot/efi`,
**in the order the facts report them**, with only the three keys any finding
reads. The current preference for `/boot` over `/boot/efi`
(`discovery.yml:907`) is a policy and stays in the evaluator, so both are
kept when both exist. An empty list means neither is a separate mount — which
is a real observation, not a missing probe.

### `services`

`ansible_facts.services` reduced to `{state, status}` per unit, keys
unchanged (`sssd.service`, not `sssd`). The whole map is kept rather than the
three units the findings need: unit-name resolution (`sssd.service` vs
`sssd`, the nine time-sync candidates) is evaluator logic, and the heal layer
reads arbitrary units.

### `probes`

Every probe object carries:

| Key | Meaning |
| --- | --- |
| `ran` | `false` when the task was skipped — a `when:` excluded it, or the binary is absent. **`false` is not a pass.** |
| `rc` | Exit code. `null` when `ran` is `false`. |
| `unsupported_reason` | Free text for why `ran` is `false` or the tool could not answer. `null` otherwise. |

Then per probe:

| Probe | Payload | Backs |
| --- | --- | --- |
| `logs` | `window`, `stdout` | `log_errors` |
| `audit_logs` | `window`, `stdout` | `kernel_install_failures` |
| `failed_logins` | `stdout_lines` | `failed_logins` |
| `last_reboot` | `stdout` | report only |
| `installed_kernels` | `latest`, `updated_at`, `filtered` | `kernel_not_latest`, `bootloader_mismatch`, `reboot_required` fallback |
| `bootloader` | `supported`, `source`, `default_entry`, `default_kernel`, `status` | `bootloader_mismatch` |
| `reboot_required` | `supported`, `detected`, `source`, `detail`, `packages[]` | `reboot_required` |
| `selinux` | `stdout` | `selinux_disabled` |
| `apparmor` | `rc` only — the probe has no output, the exit code *is* the answer | `apparmor_disabled` |
| `rescue_images` | `stdout_lines` | report only |

Two deliberate choices:

- **Parsed, not raw text.** `installed_kernels`, `bootloader` and
  `reboot_required` are `key=value` blocks printed by shell scripts. The
  parse is mechanical (`regex_findall('(?m)^latest=(.*)$')` and friends) and
  carries no policy, so it stays in collect and the document holds typed
  fields. The alternative — shipping raw stdout and re-parsing in Python —
  moves shell-output handling into the evaluator for no gain.
- **`window` is recorded.** `linux_vitals_log_window` is a collection
  parameter, not a judgement threshold: it says what was looked at, and a
  finding's evidence is meaningless without it.

`reboot_required.packages` is a list here; the probe prints it
comma-separated and `reboot_facts.yml:41` splits it. Same reasoning as above.

### `healing`, `certificates`

Both `null` unless their opt-in role ran.

`certificates` is **reserved and undefined in `state_schema: 1`**.
`vitals_certs` is frozen for the duration of this refactor, so its 8 findings
stay on their current path and are not part of the phase-1 golden net.

`healing` is a genuine wrinkle, recorded here rather than solved:

```json
"healing": {
  "attempts": [{"service": "nginx.service", "restart_failed": false}],
  "services_after": {"nginx.service": {"state": "running", "status": "enabled"}}
}
```

`service_manual_followup` is the one finding that **cannot be evaluated from a
single state document**. `vitals_heal` restarts services between collection
and evaluation, so the finding depends on an action log plus a *second*
observation of the same host. Under the three-layer model that is two state
documents and a diff, not one document. Flagged for the phase-2 design; it
does not block phase 1.

## What is deliberately absent

Each of these exists in the current code and is excluded on purpose, because
each is a judgement:

| Excluded | Currently computed at | Belongs to |
| --- | --- | --- |
| `ram_used_pct`, `ram_status` | `discovery.yml:667`, `:704` | evaluate |
| `boot_free_pct`, `boot_space_status` | `discovery.yml:943`, `:955` | evaluate |
| `latest_kernel_selected` | `discovery.yml:757` | evaluate |
| `apparmor_status` (`enabled`/`disabled`) | `discovery.yml:829` | evaluate |
| `bootloader_default_matches_latest` | `discovery.yml:879` | evaluate |
| `reboot_required` (the decision, not the probe) | `reboot_facts.yml:58` | evaluate |
| `service_status` three-key map | `services.yml` | evaluate |
| every threshold and severity | `vitals_scan/defaults/main.yml` | rules file |
| `uptime_readable`, `platform_type`, `log_excerpt` | `discovery.yml:715`, `:724`, `:703` | render |

Excerpts are a render concern: the state document holds full `stdout`, and
truncation to five lines is presentation.

## Versioning

`state_schema` is an integer, bumped when a field is removed or its meaning
changes. Adding an optional field does not bump it. It is independent of the
report's `schema_version`, and neither implies the other.
