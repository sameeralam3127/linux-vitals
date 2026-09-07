"""A failed notification must never print the credential it was sent with.

An incoming-webhook URL is itself the bearer token for that channel, and
`ansible.builtin.uri` does not treat `url` or `headers` as secret, so an
unguarded task publishes them the moment a post fails. These tests drive the
real `notify.yml` at a dead endpoint and assert on what reaches the operator.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "notification_redaction.yml"
NOTIFY_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks" / "notify.yml"
SECRET = "S3CRET-TOKEN-MUST-NOT-APPEAR"
SMTP_USER = "S3CRET-SMTP-USER-MUST-NOT-APPEAR"

# The modules that actually carry credentials out of the collection.
SENDING_MODULES = {"ansible.builtin.uri", "community.general.mail"}


def _run_channel(tmp_path: Path, channel: str) -> tuple[int, str]:
    # -vv because verbosity is one of the ways the arguments leak: the check has
    # to hold when someone is debugging, not just on a quiet run.
    completed = subprocess.run(
        [
            _ansible_playbook_bin(),
            str(FIXTURE),
            "-vv",
            "-e",
            f"lv_test_channel={channel}",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
    )
    return completed.returncode, completed.stdout + completed.stderr


@pytest.mark.parametrize("channel", ["slack", "webhook", "email"])
def test_failed_notification_does_not_print_the_credential(
    tmp_path: Path, channel: str
) -> None:
    returncode, output = _run_channel(tmp_path, channel)

    # The endpoint is closed, so the run must fail -- otherwise this test would
    # pass simply because nothing was ever sent.
    assert returncode != 0, f"expected the {channel} notification to fail:\n{output}"
    assert SECRET not in output, (
        f"the {channel} notification leaked its credential into the output"
    )
    assert SMTP_USER not in output, (
        f"the {channel} notification leaked the SMTP username into the output"
    )


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("slack", "Slack notification failed"),
        ("webhook", "Generic webhook notification failed"),
        ("email", "Email notification failed"),
    ],
)
def test_failure_is_still_actionable(tmp_path: Path, channel: str, expected: str) -> None:
    # Redaction must not cost the operator the ability to see what broke.
    _, output = _run_channel(tmp_path, channel)

    assert expected in output
    if channel != "email":
        assert "HTTP status -1" in output, "the status code should reach the operator"


def test_a_successful_run_is_not_reported_as_a_failure(tmp_path: Path) -> None:
    # With every channel disabled, the sends skip and no failure task fires.
    returncode, output = _run_channel(tmp_path, "none")

    assert returncode == 0, output
    assert "notification failed" not in output


def test_every_sending_task_is_no_log() -> None:
    # Guards the next channel somebody adds: a send without no_log is exactly
    # the bug this file exists to prevent.
    tasks = yaml.safe_load(NOTIFY_TASKS.read_text(encoding="utf-8"))

    sending = [t for t in tasks if SENDING_MODULES & set(t)]
    assert len(sending) == 3, f"expected 3 sending tasks, found {len(sending)}"

    for task in sending:
        assert task.get("no_log") is True, f"{task['name']!r} must set no_log"
        # return_content pulls the remote response into a result that is then
        # one careless debug away from being printed; nothing consumes it.
        for module in SENDING_MODULES & set(task):
            assert "return_content" not in task[module], (
                f"{task['name']!r} should not capture the response body"
            )
