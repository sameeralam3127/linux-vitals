#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Sameer Alam
# MIT (see LICENSE)
"""Collect TLS certificate facts from disk and from live TLS endpoints."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: linux_vitals_cert_facts
short_description: Collect TLS certificate facts from files and live endpoints
version_added: "1.4.0"
description:
  - Reads X.509 certificates from the filesystem and, optionally, from live
    TLS endpoints, and returns a normalised fact per certificate.
  - Deliberately has no Python dependency beyond the standard library. Parsing
    shells out to C(openssl), which is present on every distribution this
    collection supports; the TLS handshake uses C(ssl) and C(socket) from the
    standard library. Nothing is installed on the managed host.
  - Read-only. The module never writes, moves, or changes a certificate, and
    always reports C(changed=false).
options:
  paths:
    description:
      - Directories and files to search for certificates.
      - A directory is searched to C(max_depth); a file is read directly.
      - Missing paths are skipped silently, because a cert directory that does
        not exist on a given host is the normal case in a mixed fleet, not an
        error.
    type: list
    elements: path
    default: []
  file_patterns:
    description:
      - Filename glob patterns treated as certificates when searching a
        directory.
    type: list
    elements: str
    default: ["*.crt", "*.pem", "*.cer"]
  max_depth:
    description:
      - How far below each directory in O(paths) to descend.
    type: int
    default: 3
  endpoints:
    description:
      - Live TLS endpoints to inspect, as the certificate is actually
        presented in the handshake.
      - Each entry accepts C(host), C(port) (default 443), and C(server_name)
        for the SNI name when it differs from C(host).
    type: list
    elements: dict
    default: []
  timeout:
    description:
      - Seconds to wait for a TLS handshake before giving up on an endpoint.
    type: int
    default: 5
  openssl_path:
    description:
      - Path to the C(openssl) binary. Resolved from C(PATH) when unset.
    type: path
author:
  - Sameer Alam (@sameeralam3127)
"""

EXAMPLES = r"""
- name: Inspect certificates on disk and the cert nginx actually serves
  sameeralam3127.linux_vitals.linux_vitals_cert_facts:
    paths:
      - /etc/letsencrypt/live
      - /etc/nginx/ssl
    endpoints:
      - host: localhost
        port: 443
        server_name: www.example.com
  register: cert_facts

- name: Show certificates expiring within 30 days
  ansible.builtin.debug:
    msg: "{{ cert_facts.certificates | selectattr('days_remaining', 'lt', 30) | list }}"
"""

RETURN = r"""
certificates:
  description:
    - One entry per certificate found on disk.
    - Entries that could not be parsed carry C(error) and a null
      C(not_after); they are reported rather than dropped, so an unreadable
      certificate is visible instead of silently absent.
  returned: always
  type: list
  elements: dict
  sample:
    - source: file
      path: /etc/ssl/certs/example.crt
      subject: "CN=www.example.com"
      issuer: "CN=Example CA"
      not_after: "2027-01-01T00:00:00+00:00"
      days_remaining: 103
      signature_algorithm: sha256WithRSAEncryption
      self_signed: false
      fingerprint_sha256: "AA:BB:..."
endpoints:
  description:
    - One entry per endpoint in O(endpoints), describing the certificate
      actually presented in the handshake.
    - An endpoint that could not be reached carries C(error).
  returned: always
  type: list
  elements: dict
scanned_paths:
  description: The paths that existed and were searched.
  returned: always
  type: list
  elements: str
openssl_available:
  description:
    - Whether an C(openssl) binary was found. When false, no certificate can
      be parsed and both lists come back empty.
  returned: always
  type: bool
"""

import datetime
import fnmatch
import os
import socket
import ssl

from ansible.module_utils.basic import AnsibleModule


# openssl prints "notAfter=Jan  1 00:00:00 2027 GMT". %e is not portable, and
# the day is space-padded, so the string is normalised before parsing.
_OPENSSL_TIME_FORMAT = "%b %d %H:%M:%S %Y %Z"


def _parse_openssl_time(value):
    """Return an aware UTC datetime for an openssl date string, or None."""
    cleaned = " ".join(value.strip().split())
    for suffix in ("GMT", "UTC"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            try:
                parsed = datetime.datetime.strptime(cleaned, "%b %d %H:%M:%S %Y")
            except ValueError:
                return None
            return parsed.replace(tzinfo=datetime.timezone.utc)
    return None


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class CertificateReader(object):
    """Parses certificates by shelling out to openssl.

    openssl is used rather than a Python X.509 library because it is present
    everywhere this collection runs, and requiring `cryptography` on every
    managed host would undo the collection's agentless promise for the sake of
    one role.
    """

    def __init__(self, module, openssl_path):
        self.module = module
        self.openssl_path = openssl_path

    def available(self):
        return bool(self.openssl_path)

    def _run(self, args, data=None):
        rc, stdout, stderr = self.module.run_command(
            [self.openssl_path] + args,
            data=data,
            binary_data=False,
        )
        return rc, stdout, stderr

    def parse(self, pem_text):
        """Return a dict of normalised fields for one PEM certificate."""
        fields = {}
        rc, stdout, stderr = self._run(
            [
                "x509",
                "-noout",
                "-subject",
                "-issuer",
                "-enddate",
                "-startdate",
                "-fingerprint",
                "-sha256",
            ],
            data=pem_text,
        )
        if rc != 0:
            return {"error": (stderr or "openssl could not parse the certificate").strip()}

        for line in stdout.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "subject":
                fields["subject"] = value
            elif key == "issuer":
                fields["issuer"] = value
            elif key == "notAfter":
                fields["not_after_raw"] = value
            elif key == "notBefore":
                fields["not_before_raw"] = value
            elif key.startswith("sha256 Fingerprint") or key == "SHA256 Fingerprint":
                fields["fingerprint_sha256"] = value

        # Signature algorithm only appears in the full text dump. The first
        # occurrence is the one in the certificate body; a second identical
        # line appears in the signature block.
        rc, stdout, _ = self._run(["x509", "-noout", "-text"], data=pem_text)
        if rc == 0:
            for line in stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("Signature Algorithm:"):
                    fields["signature_algorithm"] = stripped.split(":", 1)[1].strip()
                    break

        not_after = _parse_openssl_time(fields.pop("not_after_raw", ""))
        not_before = _parse_openssl_time(fields.pop("not_before_raw", ""))

        fields["not_after"] = not_after.isoformat() if not_after else None
        fields["not_before"] = not_before.isoformat() if not_before else None
        if not_after:
            # Whole days remaining, floored, and negative once expired -- so a
            # caller can threshold on it without special-casing expiry.
            fields["days_remaining"] = (not_after - _now()).days
            fields["expired"] = not_after <= _now()
        else:
            fields["days_remaining"] = None
            fields["expired"] = None

        subject = fields.get("subject")
        issuer = fields.get("issuer")
        fields["self_signed"] = bool(subject and issuer and subject == issuer)
        return fields


def _iter_candidate_files(root, patterns, max_depth):
    """Yield files under root matching patterns, to max_depth."""
    if os.path.isfile(root):
        yield root
        return
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= max_depth:
            # Prune rather than continue, so a deep tree is not walked in full
            # only to have its results discarded.
            dirnames[:] = []
        for filename in filenames:
            if any(fnmatch.fnmatch(filename, pattern) for pattern in patterns):
                yield os.path.join(dirpath, filename)


def _read_first_certificate(path):
    """Return the first PEM block in a file, or None if there is not one.

    Only the first is read on purpose: a fullchain.pem holds the leaf followed
    by its intermediates, and the leaf is the one whose expiry matters.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError:
        return None

    begin = content.find("-----BEGIN CERTIFICATE-----")
    if begin == -1:
        return None
    end = content.find("-----END CERTIFICATE-----", begin)
    if end == -1:
        return None
    return content[begin : end + len("-----END CERTIFICATE-----")] + "\n"


def _fetch_endpoint_certificate(host, port, server_name, timeout):
    """Return the PEM the endpoint actually presents, or raise OSError."""
    # Verification is deliberately disabled: the job is to report what is
    # being served, including a cert that is expired, self-signed, or for the
    # wrong name. Verifying would turn exactly the cases worth reporting into
    # a handshake failure with no detail.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as tls:
            der = tls.getpeercert(binary_form=True)
            negotiated = {
                "tls_version": tls.version(),
                "cipher": tls.cipher()[0] if tls.cipher() else None,
            }
    if not der:
        raise OSError("the endpoint completed a handshake but presented no certificate")
    return ssl.DER_cert_to_PEM_cert(der), negotiated


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            paths=dict(type="list", elements="path", default=[]),
            file_patterns=dict(
                type="list", elements="str", default=["*.crt", "*.pem", "*.cer"]
            ),
            max_depth=dict(type="int", default=3),
            endpoints=dict(type="list", elements="dict", default=[]),
            timeout=dict(type="int", default=5),
            openssl_path=dict(type="path"),
        ),
        supports_check_mode=True,
    )

    openssl_path = module.params["openssl_path"] or module.get_bin_path("openssl")
    reader = CertificateReader(module, openssl_path)

    certificates = []
    endpoints = []
    scanned_paths = []

    if reader.available():
        seen = set()
        for root in module.params["paths"]:
            if not os.path.exists(root):
                continue
            scanned_paths.append(root)
            for path in _iter_candidate_files(
                root, module.params["file_patterns"], module.params["max_depth"]
            ):
                real = os.path.realpath(path)
                # letsencrypt's live/ directory is symlinks into archive/, so
                # the same certificate is reachable by several paths. Report it
                # once, under the path the operator configured.
                if real in seen:
                    continue
                seen.add(real)

                pem = _read_first_certificate(path)
                if pem is None:
                    # Not a certificate. The default patterns match *.pem, and
                    # a letsencrypt live/ directory is mostly privkey.pem --
                    # reporting those as broken certificates would manufacture
                    # a finding per host per renewal directory. A file that
                    # holds no certificate is not a certificate this module has
                    # an opinion about, so it is skipped rather than reported.
                    continue

                entry = {"source": "file", "path": path}
                entry.update(reader.parse(pem))
                certificates.append(entry)

        for spec in module.params["endpoints"]:
            host = spec.get("host")
            port = int(spec.get("port", 443) or 443)
            server_name = spec.get("server_name") or host
            entry = {
                "source": "endpoint",
                "host": host,
                "port": port,
                "server_name": server_name,
            }
            if not host:
                entry.update({"error": "endpoint has no host", "not_after": None})
                endpoints.append(entry)
                continue
            try:
                pem, negotiated = _fetch_endpoint_certificate(
                    host, port, server_name, module.params["timeout"]
                )
            except (OSError, ssl.SSLError) as exc:
                entry.update({"error": str(exc) or exc.__class__.__name__, "not_after": None})
            else:
                entry.update(negotiated)
                entry.update(reader.parse(pem))
            endpoints.append(entry)

    module.exit_json(
        changed=False,
        certificates=certificates,
        endpoints=endpoints,
        scanned_paths=scanned_paths,
        openssl_available=reader.available(),
    )


def main():
    run_module()


if __name__ == "__main__":
    main()
