# vitals_scan

Read-only Linux host discovery and health-posture role, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

Gathers facts, journal/log posture, kernel and bootloader state,
boot-partition health, security controls (SELinux/AppArmor), and
failed-login data, then builds one `linux_vitals_result` fact per host with
a `final_status` (`Pass`/`Fail`) and a list of `findings`. Never changes
anything on the managed host.

Per-distro reboot detection, latest-kernel selection, bootloader default
resolution, and their known edge cases are documented in
[docs/kernel-reboot-detection.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/kernel-reboot-detection.md).

## Role Variables

See [docs/variable-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/variable-reference.md#vitals_scan----thresholds-and-windows)
in the parent collection for the full list (RAM/boot thresholds, journal
windows, priority and line cap).

## Example

```yaml
- hosts: linux_servers
  roles:
    - role: sameeralam3127.linux_vitals.vitals_scan
```

Typically run as part of `sameeralam3127.linux_vitals.healthcheck` (or
`.baseline` / `.postcheck`) rather than standalone, alongside `vitals_heal`
and `vitals_report`. See the collection's
[architecture doc](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/architecture.md)
for how the three roles compose.

## License

MIT
