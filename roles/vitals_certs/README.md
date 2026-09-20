# vitals_certs

Opt-in TLS certificate expiry and hardening checks, part of the
[LinuxVitals](https://github.com/sameeralam3127/linux-vitals) collection
(`sameeralam3127.linux_vitals`).

This is the only role in the collection that can open an outbound network
connection. It is gated by `linux_vitals_certs_enabled` (default `false`)
-- with it left at the default, this role's tasks are skipped and nothing
on managed hosts is read or contacted.

## Purpose

When enabled, the role:

- Walks configured filesystem paths for PEM certificates and inspects
  subject, issuer, validity dates, signature algorithm, and a SHA-256
  fingerprint of the *certificate*.
- Optionally opens a TLS handshake to an explicit list of endpoints
  (`linux_vitals_cert_endpoints`, empty by default) from the *managed
  host*, records the served certificate, and compares its fingerprint
  against the on-disk inventory.
- Emits findings for expiry (and near-expiry), weak signatures, obsolete
  negotiated TLS versions, self-signed served certificates, and served
  certificates that do not appear on disk.

Findings are merged into the collection result so `vitals_report` can
render them. Run it after `vitals_scan` / `vitals_heal` and before
`vitals_report`, typically as part of `sameeralam3127.linux_vitals.healthcheck`
rather than standalone.

## What it reads

- PEM files under `linux_vitals_cert_fs_paths` that match
  `linux_vitals_cert_file_patterns`, to a maximum depth of
  `linux_vitals_cert_max_depth`. Default paths include directories that
  often hold private keys next to certificates (`/etc/letsencrypt/live`,
  `/etc/nginx/ssl`); reading those usually needs `become`.
- Only the first PEM `CERTIFICATE` block of each file. A file with no
  certificate block (for example `privkey.pem`) is skipped; its contents
  never enter a variable, a fact, or a report.
- Live TLS endpoints named in `linux_vitals_cert_endpoints`. Connections
  originate on the managed host, not the control node. Certificate
  verification is disabled for the handshake so expired, self-signed, or
  name-mismatched certificates can still be reported.

The system CA trust store paths in `linux_vitals_cert_ca_store_paths` are
still inspected, but only produce a finding when a certificate is already
expired, so hundreds of third-party roots do not bury real findings.

## What it never changes

- No files are written, rotated, or deleted on the managed host.
- No services are reloaded or restarted.
- No private key material is parsed, stored, or reported. Report fields
  are subject, issuer, validity dates, signature algorithm, and the
  certificate fingerprint -- public data.
- Enabling the role does not scan the network. The endpoint list is
  explicit and empty by default; nothing is contacted until you name a
  target.
- The module reports `changed=false`. Missing paths and unreachable
  endpoints come back as data, not task failures.

This is a reporting tool, not a trust decision. Do not treat its output
as evidence that a certificate chain validates.

## Role Variables

Do not duplicate the defaults here. The authoritative list -- types,
defaults, and descriptions -- is
[`meta/argument_specs.yml`](meta/argument_specs.yml).

The gate is `linux_vitals_certs_enabled` (default `false`). Paths,
patterns, depth, endpoints, handshake timeout, weak-signature list, and
minimum TLS version are all defined there.

Collection-level context is in
[docs/variable-reference.md](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/variable-reference.md).

## Outbound connections

Read [the threat-model section on this role](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/threat-model.md#vitals_certs-the-only-role-that-opens-a-connection)
before enabling it or pointing `linux_vitals_cert_endpoints` at anything
other than `localhost`. In short:

- Every host in the play opens a connection to every configured endpoint.
- Nothing is sent beyond the handshake; the socket is closed after the
  peer certificate is read.
- Granting `become` so the role can read a key directory is a real
  escalation. If that is not acceptable, restrict `linux_vitals_cert_fs_paths`
  to public certificate paths, or run endpoints alone.

## Example

```yaml
- hosts: linux_servers
  vars:
    linux_vitals_certs_enabled: true
    linux_vitals_cert_endpoints:
      - host: localhost
        port: 443
  roles:
    - role: sameeralam3127.linux_vitals.vitals_scan
    - role: sameeralam3127.linux_vitals.vitals_heal
    - role: sameeralam3127.linux_vitals.vitals_certs
    - role: sameeralam3127.linux_vitals.vitals_report
```

`localhost` means the service that host itself serves. The endpoint list
is empty by default on purpose -- enabling the role must not start
scanning the network.

See the collection's
[architecture doc](https://github.com/sameeralam3127/linux-vitals/blob/main/docs/architecture.md)
for how the four roles compose.

## License

MIT
