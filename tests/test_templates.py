from __future__ import annotations

import os
import json
import re
import subprocess
from pathlib import Path
from shutil import which


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "render_templates.yml"
ARCHIVE_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "report_archiving.yml"
COMPARE_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "maintenance_compare.yml"
SLACK_FLEET_PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "slack_blockkit_fleet.yml"

# Slack's documented Block Kit limits. Exceeding any of them is rejected
# with a bare HTTP 400 that names no cause, so they are asserted here
# rather than discovered in a channel.
SLACK_MAX_BLOCKS = 50
SLACK_MAX_TEXT = 3000
SLACK_MAX_FIELDS = 10


def _ensure_dev_collection_symlink() -> None:
    # FQCN roles (sameeralam3127.linux_vitals.*) resolve via
    # ansible.cfg's collections_path, which points at this repo-local
    # symlink -- create it on demand so a fresh clone/CI needs no manual
    # setup step.
    link = REPO_ROOT / ".dev-collections" / "ansible_collections" / "sameeralam3127" / "linux_vitals"
    if link.is_symlink() or link.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(REPO_ROOT, target_is_directory=True)


def _ansible_playbook_bin() -> str:
    ansible_playbook = os.environ.get("ANSIBLE_PLAYBOOK_BIN") or which("ansible-playbook")
    assert ansible_playbook, "ansible-playbook must be installed and available on PATH"
    return ansible_playbook


def _base_env(tmp_path: Path) -> dict[str, str]:
    _ensure_dev_collection_symlink()
    env = os.environ.copy()
    env["TEST_OUTPUT_DIR"] = str(tmp_path)
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    env["ANSIBLE_LOCAL_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_REMOTE_TEMP"] = str(REPO_ROOT / ".ansible" / "tmp")
    env["ANSIBLE_HOME"] = str(REPO_ROOT / ".ansible")
    # Pin the collections path explicitly instead of letting ansible.cfg
    # supply it. An environment variable outranks the config file, and
    # pytest-ansible -- which is in requirements-dev.txt and therefore present
    # in every dev and CI environment -- sets ANSIBLE_COLLECTIONS_PATH to a
    # value that does not include .dev-collections. Roles kept resolving
    # anyway through roles_path, so this stayed invisible until a test needed
    # a *module* from the collection (linux_vitals_cert_facts) and got
    # "couldn't resolve module/action".
    env["ANSIBLE_COLLECTIONS_PATH"] = os.pathsep.join(
        [
            str(REPO_ROOT / ".dev-collections"),
            str(Path.home() / ".ansible" / "collections"),
        ]
    )
    return env


def test_templates_render_with_representative_health_data(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    slack = (tmp_path / "slack.txt").read_text(encoding="utf-8")
    generic_webhook = json.loads((tmp_path / "generic_webhook.json").read_text(encoding="utf-8"))
    slack_blocks = json.loads((tmp_path / "slack.json").read_text(encoding="utf-8"))
    json_report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert "LinuxVitals Test Dashboard" in report
    assert "localhost" in report
    assert "Default boot entry selects the latest installed kernel" in report
    assert "chronyd.service: Fixed" in report
    assert "Standard Maintenance Summary" in slack
    assert "Overall Status: PASS" in slack
    assert "Bootloader: 6.8.0-test (latest selected)" in slack
    assert "Host Breakdown:" in slack
    assert generic_webhook["summary"]["overall_status"] == "PASS"
    assert generic_webhook["hosts"][0]["hostname"] == "localhost"
    assert "Standard Maintenance Summary" in generic_webhook["message"]
    assert json_report["schema_version"] == "2.0"
    assert json_report["summary"]["health_score_pct"] == 100.0
    assert json_report["hosts"][0]["asset_serial"] == "TEST-SERIAL-0001"
    assert json_report["hosts"][0]["comparison"]["baseline_available"] is False
    assert json_report["generated_at"] == "20260429T120000Z"
    assert json_report["summary"]["overall_status"] == "PASS"
    assert json_report["hosts"][0]["kernel"]["running"] == "6.8.0-test"
    assert json_report["hosts"][0]["reboot"]["required"] is False
    assert json_report["hosts"][0]["reboot"]["source"] == "reboot-required-file"
    assert json_report["hosts"][0]["reboot"]["detection_supported"] is True
    assert json_report["hosts"][0]["reboot"]["pending_packages"] == []
    assert generic_webhook["hosts"][0]["reboot_required_source"] == "reboot-required-file"
    assert "Reboot: No (reboot-required-file)" in slack
    assert json_report["hosts"][0]["security"]["apparmor_status"] == "enabled"

    # Slack renders the top-level `text` ABOVE the attachment, so it must be
    # one short line. Putting the full plain-text summary there printed the
    # entire old-style message above the new card, duplicated.
    assert slack_blocks["text"] == "LinuxVitals: PASS — 1 host(s) checked, 0 critical, 1 auto-fixed"
    assert "\n" not in slack_blocks["text"]
    assert len(slack_blocks["text"]) < 200
    # The plain-text message itself is unchanged and still carried by the
    # email body and the generic webhook.
    assert "Host Breakdown:" in slack
    attachment = slack_blocks["attachments"][0]
    blocks = attachment["blocks"]
    assert attachment["color"] == "#ecb22e"  # PASS, but a warning-severity host
    assert blocks[0] == {
        "type": "header",
        "text": {"type": "plain_text", "text": "Standard Maintenance Summary", "emoji": True},
    }
    assert ":warning: *Overall status: PASS*" in blocks[1]["text"]["text"]
    counters = {f["text"].split("\n")[0]: f["text"].split("\n")[1] for f in blocks[2]["fields"]}
    assert counters["*Servers checked*"] == "1"
    assert counters["*Auto-fixed*"] == "1"
    assert counters["*Critical errors*"] == "0"
    table = _host_table(blocks)
    # The whole point of the issue: this was one `|`-joined run-on line.
    assert table[0].split() == ["HOST", "STATUS", "SEV", "KERNEL", "BOOTLDR", "REBOOT", "/BOOT", "LOGINS"]
    assert table[2].split() == ["localhost", "Pass", "WARN", "6.8.0-test", "latest", "no", "Healthy", "0"]
    # Every row is padded to the same width, which is what makes the columns
    # line up in Slack's monospace code block.
    assert len({len(line) for line in table[1:]}) == 1
    # The footer names the project even though the header is customised here.
    context = " ".join(e["text"] for b in blocks if b["type"] == "context" for e in b["elements"])
    assert "LinuxVitals" in context
    _assert_block_kit_within_slack_limits(slack_blocks)


def test_reporting_archives_timestamped_outputs_and_prunes_old_reports(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(ARCHIVE_PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    latest_report = tmp_path / "latest" / "linux_vitals_report.html"
    latest_json_report = tmp_path / "latest" / "linux_vitals_report.json"
    archived_html = sorted((tmp_path / "archive").glob("linux_vitals_report-*.html"))
    archived_json = sorted((tmp_path / "archive").glob("linux_vitals_report-*.json"))

    assert latest_report.exists()
    assert latest_json_report.exists()
    assert json.loads(latest_json_report.read_text(encoding="utf-8"))["summary"]["overall_status"] == "PASS"
    assert [path.name for path in archived_html] == [
        "linux_vitals_report-20260428T120000Z.html",
        "linux_vitals_report-20260429T120000Z.html",
    ]
    assert [path.name for path in archived_json] == [
        "linux_vitals_report-20260428T120000Z.json",
        "linux_vitals_report-20260429T120000Z.json",
    ]


def test_baseline_postcheck_comparison_detects_improvement_and_regression(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    subprocess.run(
        [
            _ansible_playbook_bin(),
            str(COMPARE_PLAYBOOK),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    comparisons = json.loads((tmp_path / "comparisons.json").read_text(encoding="utf-8"))

    assert comparisons["host-a"]["baseline_available"] is True
    assert comparisons["host-a"]["status_improved"] is True
    assert comparisons["host-a"]["status_regressed"] is False
    assert comparisons["host-a"]["kernel_changed"] is True
    assert comparisons["host-a"]["ram_used_pct_delta"] == -36.0
    # host-a's baseline was written by 1.x, so its findings are strings. They
    # come back translated to the ids a 2.x run would have given them, with
    # the original wording kept as the message.
    host_a_resolved = comparisons["host-a"]["resolved_findings"]
    assert [f["id"] for f in host_a_resolved] == ["ram_critical", "reboot_required"]
    assert host_a_resolved[0]["message"] == "RAM usage is critical"

    assert comparisons["host-b"]["baseline_available"] is True
    assert comparisons["host-b"]["status_regressed"] is True
    assert comparisons["host-b"]["status_improved"] is False
    assert [f["id"] for f in comparisons["host-b"]["new_findings"]] == ["ram_critical"]

    assert comparisons["host-c"]["baseline_available"] is False

    # host-d carries the post-severity finding shape. The diff is on finding
    # identity (id and subject), so `reboot_required` -- present in both runs but reworded and
    # retuned from warning to critical -- is neither new nor resolved. A
    # whole-object difference() would report it as both.
    host_d = comparisons["host-d"]
    assert host_d["baseline_available"] is True
    assert [f["id"] for f in host_d["new_findings"]] == ["boot_space_low"]
    assert [f["id"] for f in host_d["resolved_findings"]] == ["log_errors"]
    # The object carried through is the current run's, so the dashboard shows
    # current wording and current severity rather than the baseline's.
    assert host_d["severity_before"] == "warning"
    assert host_d["severity_after"] == "critical"

    # host-e is a window spanning the upgrade: a 1.x string baseline against
    # a 2.x postcheck. The two findings that persisted -- one per-host, one
    # per-unit -- are neither new nor resolved; before #77 both were reported
    # as both. A string no release ever emitted keeps its message as its id.
    host_e = comparisons["host-e"]
    assert host_e["new_findings"] == []
    assert [f["id"] for f in host_e["resolved_findings"]] == ["A finding no release of LinuxVitals ever emitted"]

    # host-f: one id, told apart by subject. redis recovered and postgresql
    # failed during the window; an id-only diff reported neither (#77).
    host_f = comparisons["host-f"]
    assert [f["subject"] for f in host_f["new_findings"]] == ["postgresql.service"]
    assert [f["subject"] for f in host_f["resolved_findings"]] == ["redis.service"]


def _host_table(blocks: list) -> list[str]:
    """The host breakdown as its raw table lines, code fence stripped."""
    sections = [
        b["text"]["text"]
        for b in blocks
        if b["type"] == "section" and b.get("text", {}).get("text", "").startswith("*Host breakdown*")
    ]
    assert len(sections) == 1, "expected exactly one host breakdown block"
    body = sections[0].split("```")
    assert len(body) == 3, "host breakdown is not wrapped in a single code fence"
    return body[1].strip("\n").split("\n")


def _assert_block_kit_within_slack_limits(payload: dict) -> None:
    """Structural validity, the way the generic webhook payload is checked.

    Not a schema validator -- it asserts the invariants that actually break a
    real send: the limits Slack enforces, and the shape it requires.
    """
    assert isinstance(payload.get("text"), str) and payload["text"].strip()

    for attachment in payload["attachments"]:
        blocks = attachment["blocks"]
        assert len(blocks) <= SLACK_MAX_BLOCKS, f"{len(blocks)} blocks exceeds Slack's limit"
        assert attachment["color"].startswith("#")

        for block in blocks:
            assert block["type"] in {"header", "section", "divider", "context"}

            if "text" in block:
                text = block["text"]
                assert text["type"] in {"plain_text", "mrkdwn"}
                assert len(text["text"]) <= SLACK_MAX_TEXT
                if block["type"] == "header":
                    # Slack renders no markup in a header and caps it at 150.
                    assert text["type"] == "plain_text"
                    assert len(text["text"]) <= 150

            if "fields" in block:
                assert len(block["fields"]) <= SLACK_MAX_FIELDS
                for field in block["fields"]:
                    assert field["type"] == "mrkdwn"
                    assert 0 < len(field["text"]) <= 2000

            if block["type"] == "context":
                assert 0 < len(block["elements"]) <= 10

            # Every block has to render something; an empty section is a
            # silently blank line in the channel.
            assert "text" in block or "fields" in block or "elements" in block or block["type"] == "divider"


def test_slack_block_kit_caps_hosts_and_orders_worst_first(tmp_path: Path) -> None:
    """A 25-host fleet against a cap of 10.

    Covers what the single-host fixture cannot: the cap, the ordering that
    decides which hosts survive it, the "+ N more" note, and the fact that a
    large fleet still produces a message Slack will accept. Before this
    template existed, ~175 hosts produced a message over Slack's 40,000
    character limit and the send failed with an unexplained HTTP 400.
    """
    env = _base_env(tmp_path)

    subprocess.run(
        [_ansible_playbook_bin(), str(SLACK_FLEET_PLAYBOOK)],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    payload = json.loads((tmp_path / "slack_fleet.json").read_text(encoding="utf-8"))
    _assert_block_kit_within_slack_limits(payload)

    attachment = payload["attachments"][0]
    blocks = attachment["blocks"]
    assert attachment["color"] == "#e01e5a"  # critical errors present

    table = _host_table(blocks)
    rows = table[2:]  # heading, rule, then one line per host
    assert len(rows) == 10, "linux_vitals_slack_max_hosts was not honoured"
    # One block per host would grow with the fleet; one table does not, which
    # is what keeps a large fleet inside the 50-block limit.
    assert len(blocks) <= 12

    shown = [row.split()[0] for row in rows]
    # 01-03 are critical and 04-08 warning, so a worst-first ordering shows
    # exactly those eight before it reaches any info host.
    assert shown[:3] == ["synthetic-01", "synthetic-02", "synthetic-03"]
    assert shown[:8] == [f"synthetic-{n:02d}" for n in range(1, 9)]
    # The ten "none" hosts are the least interesting, so none of them survive.
    assert not any(host in shown for host in (f"synthetic-{n:02d}" for n in range(16, 26)))

    context_text = " ".join(
        element["text"] for block in blocks if block["type"] == "context" for element in block["elements"]
    )
    assert "+ 15 more host(s) not shown" in context_text

    attention = [b for b in blocks if "Needs attention first" in b.get("text", {}).get("text", "")]
    assert len(attention) == 1
    assert "synthetic-01" in attention[0]["text"]["text"]

    # Host-supplied text reaches the message, so Slack mrkdwn escaping has to
    # happen -- and the payload has to stay valid JSON afterwards.
    rendered = json.dumps(payload)
    assert "&amp;" in rendered and "&lt;" in rendered
    assert " & " not in rendered and "</boot>" not in rendered
    # A backtick in host-supplied text would break out of the code fence and
    # spill the rest of the table into the message as plain text.
    assert rendered.count("```") == 2
