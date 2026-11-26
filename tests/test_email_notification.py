"""The email notification's own templates (#145).

The email used to be the Slack plain-text fallback: one long `|`-joined line
per host, hosts in inventory order, no reason a host failed unless the
finding was critical, and the same subject on every run. These tests render
email_message.html.j2, email_message.txt.j2 and email_subject.txt.j2 from a
small mixed fleet (tests/fixtures/email_fleet.yml) and check what an operator
reads in an inbox.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pytest

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "email_fleet.yml"


@dataclass
class Rendered:
    html: str
    text: str
    subject: str
    subject_override: str
    slack: str
    html_no_breakdown: str


def _render(tmp_path: Path, phase: str) -> Rendered:
    subprocess.run(
        [_ansible_playbook_bin(), str(PLAYBOOK), "-e", f"fixture_phase={phase}"],
        check=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )

    def read(name: str) -> str:
        return (tmp_path / name).read_text(encoding="utf-8")

    return Rendered(
        html=read("email.html"),
        text=read("email.txt"),
        # The template module keeps a trailing newline; notify.yml trims it.
        subject=read("subject.txt").rstrip("\n"),
        subject_override=read("subject_override.txt").rstrip("\n"),
        slack=read("slack.txt"),
        html_no_breakdown=read("email_no_breakdown.html"),
    )


@pytest.fixture(scope="module")
def adhoc(tmp_path_factory: pytest.TempPathFactory) -> Rendered:
    return _render(tmp_path_factory.mktemp("email-adhoc"), "adhoc")


@pytest.fixture(scope="module")
def postcheck(tmp_path_factory: pytest.TempPathFactory) -> Rendered:
    return _render(tmp_path_factory.mktemp("email-postcheck"), "postcheck")


class _Text(HTMLParser):
    """The text a reader sees, and every tag that was opened."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.chunks))


def _parse(html: str) -> _Text:
    parser = _Text()
    parser.feed(html)
    return parser


def _section(text: str, start: str, end: str) -> str:
    assert start in text, f"{start!r} not in email"
    after = text.split(start, 1)[1]
    return after.split(end, 1)[0] if end in after else after


# --- HTML body ---------------------------------------------------------------


def test_html_relies_on_nothing_mail_clients_strip(adhoc: Rendered) -> None:
    tags = {tag for tag, _ in _parse(adhoc.html).tags}

    assert "script" not in tags
    assert "style" not in tags
    assert "link" not in tags
    # Styling is inline, which is the one form Gmail and Outlook both keep.
    assert any("style" in attrs for _, attrs in _parse(adhoc.html).tags)


def test_html_states_the_counts_once(adhoc: Rendered) -> None:
    text = _parse(adhoc.html).text

    assert "FAIL" in text
    # The old email said this twice: once as counters and once as a summary.
    assert text.count("5 Servers Checked, 1 Auto-Fixed, 2 Failing Hosts") == 0
    assert len(re.findall(r"Failing hosts", text, flags=re.I)) == 1


def test_html_shows_why_each_failing_host_fails(adhoc: Rendered) -> None:
    attention = _section(_parse(adhoc.html).text, "Needs attention", "All hosts")

    # db-02 fails on warnings only. The old email never named them.
    assert "Time synchronisation is not active" in attention
    assert "sssd is not running" in attention
    assert "RAM usage is critical" in attention
    # A check that could not run is shown with its reason.
    assert "Failed logins could not be counted" in attention
    assert "lastb exited 1: permission denied" in attention


def test_html_orders_hosts_worst_first(adhoc: Rendered) -> None:
    attention = _section(_parse(adhoc.html).text, "Needs attention", "All hosts")
    table = _section(_parse(adhoc.html).text, "All hosts", "\x00")

    # debian12 is third in the inventory but the only critical host.
    assert attention.index("debian12") < attention.index("db-02") < attention.index("mail-05")
    assert "web-01" not in attention  # nothing to act on
    assert "app-04" not in attention  # info only, and passing
    positions = [table.index(name) for name in ["debian12", "db-02", "app-04", "mail-05", "web-01"]]
    assert positions == sorted(positions)


def test_html_table_shows_inventory_name_and_address(adhoc: Rendered) -> None:
    table = _section(_parse(adhoc.html).text, "All hosts", "\x00")

    for name in ["web-01", "db-02", "debian12", "app-04", "mail-05"]:
        assert name in table
    assert "10.0.0.13" in table  # debian12
    assert "6.1.0-22-amd64" in table  # debian12's kernel
    # The inventory name, not the hostname the host reports about itself.
    assert ".lab.example" not in table


def test_html_escapes_finding_text(adhoc: Rendered) -> None:
    assert "</boot>" not in adhoc.html
    assert "&lt;/boot&gt; is low on space &amp; needs attention" in adhoc.html


def test_html_names_hosts_that_were_not_checked(adhoc: Rendered) -> None:
    text = _parse(adhoc.html).text

    assert "lost-06" in text
    assert "unreachable" in text


def test_html_points_at_the_attached_dashboard(adhoc: Rendered) -> None:
    assert "linux_vitals_report.html" in _parse(adhoc.html).text


def test_html_has_no_comparison_outside_a_postcheck(adhoc: Rendered) -> None:
    assert "Since the baseline" not in _parse(adhoc.html).text


def test_html_postcheck_shows_what_changed_since_the_baseline(postcheck: Rendered) -> None:
    changes = _section(_parse(postcheck.html).text, "Since the baseline", "All hosts")

    assert re.search(r"Regressed.*db-02", changes)
    assert re.search(r"Improved.*app-04", changes)
    assert re.search(r"No baseline.*mail-05", changes)
    assert "debian12" not in changes  # failing before and after: unchanged
    assert "lab-2026-10-16" in _parse(postcheck.html).text


def test_html_drops_the_host_table_when_the_breakdown_is_off(adhoc: Rendered) -> None:
    # linux_vitals_slack_include_host_breakdown is the documented switch for
    # keeping per-host detail out of notifications (docs/threat-model.md).
    text = _parse(adhoc.html_no_breakdown).text

    assert "All hosts" not in text
    assert "web-01" not in text
    assert "6.1.0-20-amd64" not in text


# --- Plain-text body ---------------------------------------------------------


def test_text_has_no_long_multi_field_lines(adhoc: Rendered) -> None:
    long_lines = [line for line in adhoc.text.splitlines() if len(line) > 78]

    assert long_lines == []
    assert not [line for line in adhoc.text.splitlines() if line.count("|") > 1]


def test_text_shows_findings_worst_first(adhoc: Rendered) -> None:
    text = adhoc.text

    assert "Time synchronisation is not active" in text
    assert "lastb exited 1: permission denied" in text
    assert text.index("debian12") < text.index("db-02") < text.index("mail-05")
    assert "lost-06" in text


def test_text_postcheck_shows_what_changed(postcheck: Rendered) -> None:
    changes = _section(postcheck.text, "Since the baseline", "All hosts")

    assert re.search(r"Regressed.*db-02", changes, flags=re.S)
    assert re.search(r"Improved.*app-04", changes, flags=re.S)


# --- Subject ----------------------------------------------------------------


def test_subject_carries_the_result(adhoc: Rendered, postcheck: Rendered) -> None:
    assert adhoc.subject == "[LinuxVitals] FAIL · 5 hosts · 2 failing · 1 critical · 1 not checked · adhoc"
    assert postcheck.subject == (
        "[LinuxVitals] FAIL · 5 hosts · 2 failing · 1 critical · 1 not checked · postcheck lab-2026-10-16"
    )


def test_subject_override_wins_and_cannot_inject_a_header(adhoc: Rendered) -> None:
    assert adhoc.subject_override == "Weekly patching Bcc: someone@example.com"
    assert "\n" not in adhoc.subject_override


# --- The Slack fallback stays as it was -------------------------------------


def test_slack_plain_text_fallback_is_unchanged(adhoc: Rendered) -> None:
    # The generic webhook's `message` and the Slack fallback are documented
    # payloads; the email getting its own templates must not touch them.
    assert adhoc.slack.startswith("LinuxVitals Health Check\nOverall Status: FAIL\n")
    assert "Host Breakdown:" in adhoc.slack
    assert "- web-01.lab.example (10.0.0.11) | Status: Pass" in adhoc.slack
