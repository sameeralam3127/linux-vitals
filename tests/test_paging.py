"""Paging: PagerDuty events and Opsgenie alerts (#65).

The real roles/vitals_report/tasks/config.yml and paging.yml run through
ansible-playbook, driven by tests/fixtures/paging.yml, against listeners that
this file runs on 127.0.0.1. Nothing here talks to PagerDuty or Opsgenie: a test
event sent to a real service would page someone, and there is no account to
send one from. What is checked instead is the thing that can be checked
locally -- that what is sent is what each service documents it accepts (field
names, enums, length limits) and that the run behaves correctly when a service
answers with 202, 429, 4xx or 5xx.

Every scenario is its own run with its own listener and its own inventory
directory (and so its own .env), started together and collected afterwards, so
the whole file costs about one scenario's wall-clock time rather than the sum.
"""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin, _base_env

PLAYBOOK = REPO_ROOT / "tests" / "fixtures" / "paging.yml"
MAIN_TASKS = REPO_ROOT / "roles" / "vitals_report" / "tasks" / "main.yml"

PD_KEY = "R0UTINGKEYFORTHETESTSXXXXXXXXXXXX"
OG_KEY = "0g3n13-4p1-k3y-f0r-th3-t3sts"
DOTENV_PD_KEY = "DOTENVROUTINGKEYXXXXXXXXXXXXXXXX"

PD_PATH = "/v2/enqueue"
OG_PATH = "/v2/alerts"


# --- What a scan leaves behind ----------------------------------------------


def _finding(
    id: str,
    severity: str,
    status: str = "fail",
    message: str | None = None,
    reason: str | None = None,
    subject: str | None = None,
) -> dict:
    finding = {"id": id, "severity": severity, "message": message or f"{id} message"}
    if status != "fail":
        finding["status"] = status
    if reason:
        finding["reason"] = reason
    if subject:
        finding["subject"] = subject
    return finding


def _result(hostname: str, ip: str, findings: list[dict]) -> dict:
    return {
        "hostname": hostname,
        "ip_address": ip,
        "os": "Ubuntu 24.04",
        "os_family": "Debian",
        "findings": findings,
    }


RESULTS = {
    # Listed warning-first on purpose: the event has to put the critical one
    # first regardless of the order the scan found them in.
    "critical-host": _result(
        "web-01",
        "10.0.0.1",
        [
            _finding("filesystem_space_low", "warning", message="/var is 91% full"),
            _finding("ram_critical", "critical", message="RAM usage is critical"),
            _finding(
                "failed_logins",
                "info",
                status="unknown",
                message="Failed-login history could not be inspected",
                reason="lastb exited 1: permission denied",
            ),
        ],
    ),
    "warning-host": _result(
        "web-02",
        "10.0.0.2",
        [_finding("sssd_inactive", "warning", message="sssd is not active")],
    ),
    # The case the issue singles out. Its severity is critical, and it must not
    # page: severity is a judgement about a problem, and an unknown finding is
    # not a known problem.
    "unknown-host": _result(
        "web-03",
        "10.0.0.3",
        [
            _finding(
                "firewall_inactive",
                "critical",
                status="unknown",
                message="Firewall state could not be read",
                reason="nft exited 1: operation not permitted",
            )
        ],
    ),
    "clean-host": _result("web-04", "10.0.0.4", []),
    # Enough text to blow every documented limit at once.
    "verbose-host": _result(
        "web-05",
        "10.0.0.5",
        [
            _finding(f"check_{n:02d}", "critical", message=f"finding number {n} " + "x" * 200)
            for n in range(40)
        ],
    ),
}


# --- A listener that answers as scripted ------------------------------------


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    text: str

    @property
    def json(self) -> dict:
        return json.loads(self.text)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        text = self.rfile.read(length).decode("utf-8") if length else ""
        status = self.server.answer(  # type: ignore[attr-defined]
            Received(
                path=self.path,
                headers={k.lower(): v for k, v in self.headers.items()},
                text=text,
            )
        )
        if status == 202:
            body = {"status": "success", "message": "Event processed"}
        else:
            body = {"status": "error", "message": f"scripted refusal {status}: Event object is invalid"}
        reply = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class Listener(ThreadingHTTPServer):
    """Records every POST and answers 202 unless a status was scripted for it."""

    def __init__(self, script: dict[str, list[int]]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.script = {path: list(statuses) for path, statuses in script.items()}
        self.received: list[Received] = []
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def answer(self, request: Received) -> int:
        with self._lock:
            self.received.append(request)
            queue = self.script.get(request.path, [])
            return queue.pop(0) if queue else 202

    def to(self, path: str) -> list[Received]:
        return [r for r in self.received if r.path == path]


# --- Scenarios --------------------------------------------------------------


@dataclass
class Scenario:
    hosts: list[str]
    group_vars: dict = field(default_factory=dict)
    dotenv: str | None = None
    script: dict[str, list[int]] = field(default_factory=dict)
    # no_log only matters at -v and above: at the default verbosity a task that
    # succeeded prints no arguments at all, so a send that lost its no_log would
    # look exactly as safe as one that kept it. The credential tests need a
    # run that would show the difference.
    verbosity: str = ""


FLEET = ["critical-host", "warning-host", "unknown-host", "clean-host"]


def _pd(**extra: object) -> dict:
    return {
        "linux_vitals_pagerduty_enabled": True,
        "linux_vitals_pagerduty_routing_key": PD_KEY,
        "linux_vitals_paging_retry_delay": 0,
        **extra,
    }


def _og(**extra: object) -> dict:
    return {
        "linux_vitals_opsgenie_enabled": True,
        "linux_vitals_opsgenie_api_key": OG_KEY,
        "linux_vitals_paging_retry_delay": 0,
        **extra,
    }


SCENARIOS: dict[str, Scenario] = {
    "pd-critical": Scenario(FLEET, _pd()),
    "pd-warning": Scenario(FLEET, _pd(linux_vitals_paging_min_severity="warning")),
    "pd-info": Scenario(FLEET, _pd(linux_vitals_paging_min_severity="info")),
    "pd-loud": Scenario(FLEET, _pd(), verbosity="-vvv"),
    "og-loud": Scenario(FLEET, _og(), verbosity="-vvv"),
    "refused-loud": Scenario(["critical-host"], _pd(), script={PD_PATH: [400]}, verbosity="-vvv"),
    "pd-verbose": Scenario(["verbose-host"], _pd()),
    "og-critical": Scenario(FLEET, _og()),
    "og-verbose": Scenario(["verbose-host"], _og()),
    "both": Scenario(FLEET, {**_pd(), **_og()}),
    "retry-429": Scenario(["critical-host"], _pd(), script={PD_PATH: [429, 202]}),
    "refused-400": Scenario(["critical-host"], _pd(), script={PD_PATH: [400]}),
    "down-500": Scenario(["critical-host"], _pd(), script={PD_PATH: [500, 500, 500, 500]}),
    "og-refused-401": Scenario(["critical-host"], _og(), script={OG_PATH: [401]}),
    "no-key": Scenario(
        FLEET,
        {"linux_vitals_pagerduty_enabled": True, "linux_vitals_paging_retry_delay": 0},
    ),
    "dotenv-key": Scenario(
        FLEET,
        {"linux_vitals_pagerduty_enabled": True, "linux_vitals_paging_retry_delay": 0},
        dotenv=f'PAGERDUTY_ROUTING_KEY="{DOTENV_PD_KEY}"  # the pager\n',
    ),
    "variable-beats-dotenv": Scenario(
        FLEET, _pd(), dotenv=f"PAGERDUTY_ROUTING_KEY={DOTENV_PD_KEY}\n"
    ),
    "disabled": Scenario(FLEET, {}),
    "bad-floor": Scenario(FLEET, _pd(linux_vitals_paging_min_severity="urgent")),
}


@dataclass
class Outcome:
    returncode: int
    output: str
    rendered: dict
    failure: dict | None
    listener: Listener


def _prepare(base: Path, name: str, scenario: Scenario, listener: Listener) -> tuple[list[str], dict]:
    work = base / name
    inventory = work / "inventory"
    inventory.mkdir(parents=True)
    group_vars = {
        "ansible_connection": "local",
        "ansible_python_interpreter": "{{ ansible_playbook_python }}",
        **scenario.group_vars,
    }
    if "linux_vitals_pagerduty_enabled" in group_vars:
        group_vars["linux_vitals_pagerduty_events_url"] = listener.base_url + PD_PATH
    if "linux_vitals_opsgenie_enabled" in group_vars:
        group_vars["linux_vitals_opsgenie_alerts_url"] = listener.base_url + OG_PATH
    (inventory / "hosts.yml").write_text(
        yaml.safe_dump(
            {
                "all": {
                    "children": {
                        "paging_fleet": {
                            "hosts": {host: {} for host in scenario.hosts},
                            "vars": group_vars,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    if scenario.dotenv is not None:
        (inventory / ".env").write_text(scenario.dotenv, encoding="utf-8")
    extra = work / "extra.json"
    extra.write_text(json.dumps({"lv_results": RESULTS}), encoding="utf-8")
    env = _base_env(work)
    command = [
        _ansible_playbook_bin(),
        "-i",
        str(inventory / "hosts.yml"),
        str(PLAYBOOK),
        "-e",
        f"@{extra}",
    ]
    if scenario.verbosity:
        command.append(scenario.verbosity)
    return command, env


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Outcome]:
    base = tmp_path_factory.mktemp("paging")
    listeners: dict[str, Listener] = {}
    started: dict[str, subprocess.Popen[str]] = {}
    threads: list[threading.Thread] = []
    try:
        for name, scenario in SCENARIOS.items():
            listener = Listener(scenario.script)
            thread = threading.Thread(
                target=listener.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
            )
            thread.start()
            threads.append(thread)
            listeners[name] = listener
            command, env = _prepare(base, name, scenario, listener)
            started[name] = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        collected: dict[str, Outcome] = {}
        for name, process in started.items():
            output, _ = process.communicate()
            work = base / name
            rendered_path = work / "rendered.json"
            failure_path = work / "failure.json"
            collected[name] = Outcome(
                returncode=process.returncode,
                output=output,
                rendered=json.loads(rendered_path.read_text()) if rendered_path.is_file() else {},
                failure=json.loads(failure_path.read_text()) if failure_path.is_file() else None,
                listener=listeners[name],
            )
        return collected
    finally:
        for listener in listeners.values():
            listener.shutdown()
            listener.server_close()


def _names(received: list[Received]) -> list[str]:
    return sorted(r.json["dedup_key"].removeprefix("linux-vitals:") for r in received)


# --- Who gets paged ---------------------------------------------------------


def test_every_scenario_ran_to_the_end(outcomes: dict[str, Outcome]) -> None:
    # A scenario that crashed would leave its assertions below passing on
    # empty data, so the ones that are meant to fail are named, and the rest
    # must have recorded what they rendered.
    meant_to_fail = {"refused-400", "refused-loud", "down-500", "og-refused-401", "no-key", "bad-floor"}
    for name, outcome in outcomes.items():
        assert outcome.rendered or name in meant_to_fail, f"{name}:\n{outcome.output[-3000:]}"
        if name not in meant_to_fail:
            assert outcome.failure is None, f"{name}: {outcome.failure}"


def test_a_host_with_a_critical_fail_finding_pages(outcomes: dict[str, Outcome]) -> None:
    sent = outcomes["pd-critical"].listener.to(PD_PATH)

    assert _names(sent) == ["critical-host"]


def test_the_event_is_what_pagerduty_documents(outcomes: dict[str, Outcome]) -> None:
    (request,) = outcomes["pd-critical"].listener.to(PD_PATH)
    event = request.json
    payload = event["payload"]

    assert request.headers["content-type"] == "application/json"
    assert event["event_action"] == "trigger"
    assert event["routing_key"] == PD_KEY
    # dedup_key is stable per host, so a scheduled run updates the open alert.
    assert event["dedup_key"] == "linux-vitals:critical-host"
    assert len(event["dedup_key"]) <= 255
    assert payload["severity"] in {"critical", "error", "warning", "info"}
    assert payload["severity"] == "critical"
    assert payload["source"] == "critical-host"
    assert 0 < len(payload["summary"]) <= 1024
    assert payload["summary"].startswith("critical-host: critical -- ")


def test_findings_are_listed_worst_first_whatever_order_the_scan_found_them(
    outcomes: dict[str, Outcome],
) -> None:
    (request,) = outcomes["pd-critical"].listener.to(PD_PATH)
    details = request.json["payload"]["custom_details"]

    # Only the critical one meets the default floor; the warning is carried as
    # context rather than dropped.
    assert [f["id"] for f in details["findings"]] == ["ram_critical"]
    assert details["other_findings"] == [{"id": "filesystem_space_low", "severity": "warning"}]


def test_the_details_say_where_and_when(outcomes: dict[str, Outcome]) -> None:
    (request,) = outcomes["pd-critical"].listener.to(PD_PATH)
    details = request.json["payload"]["custom_details"]

    assert details["hostname"] == "web-01"
    assert details["ip_address"] == "10.0.0.1"
    assert details["os"] == "Ubuntu 24.04"
    assert details["phase"] == "postcheck"
    assert details["maintenance_id"] == "paging-window"


def test_lowering_the_floor_pages_a_warning_and_orders_the_summary(
    outcomes: dict[str, Outcome],
) -> None:
    sent = outcomes["pd-warning"].listener.to(PD_PATH)
    by_name = {r.json["dedup_key"].removeprefix("linux-vitals:"): r.json for r in sent}

    assert sorted(by_name) == ["critical-host", "warning-host"]
    assert by_name["warning-host"]["payload"]["severity"] == "warning"
    # The host with both is still a critical page, with the critical finding
    # first in its summary even though the scan listed the warning first.
    critical = by_name["critical-host"]["payload"]
    assert critical["severity"] == "critical"
    assert [f["id"] for f in critical["custom_details"]["findings"]] == [
        "ram_critical",
        "filesystem_space_low",
    ]
    assert critical["summary"].index("RAM usage is critical") < critical["summary"].index("/var is 91%")


# --- What an unknown finding does -------------------------------------------


def test_an_unknown_finding_never_pages_whatever_severity_it_carries(
    outcomes: dict[str, Outcome],
) -> None:
    # unknown-host's only finding is critical-severity but unknown. Even with
    # the floor at info, the lowest there is, it must stay unpaged.
    for scenario in ("pd-critical", "pd-warning", "pd-info", "og-critical", "both"):
        names = _names(outcomes[scenario].listener.to(PD_PATH)) if scenario != "og-critical" else []
        assert "unknown-host" not in names, scenario
    og_names = sorted(r.json["alias"] for r in outcomes["og-critical"].listener.to(OG_PATH))
    assert "linux-vitals:unknown-host" not in og_names


def test_a_host_with_only_unknown_findings_is_named_not_silently_dropped(
    outcomes: dict[str, Outcome],
) -> None:
    outcome = outcomes["pd-critical"]

    assert outcome.rendered["unpaged_unknown"] == ["unknown-host"]
    assert "unknown-host" in outcome.output
    assert "no page was sent" in outcome.output


def test_an_unknown_finding_rides_along_on_a_page_sent_for_the_same_host(
    outcomes: dict[str, Outcome],
) -> None:
    (request,) = outcomes["pd-critical"].listener.to(PD_PATH)
    details = request.json["payload"]["custom_details"]

    assert details["unknown_checks"] == [
        {
            "id": "failed_logins",
            "severity": "info",
            "message": "Failed-login history could not be inspected",
            "reason": "lastb exited 1: permission denied",
        }
    ]
    # And it did not raise the page's severity or add itself to its findings.
    assert request.json["payload"]["severity"] == "critical"
    assert "failed_logins" not in [f["id"] for f in details["findings"]]


def test_a_clean_host_is_neither_paged_nor_mentioned(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["pd-info"]

    assert "clean-host" not in _names(outcome.listener.to(PD_PATH))
    assert "clean-host" not in outcome.rendered["unpaged_unknown"]


# --- Documented limits ------------------------------------------------------


def test_a_flood_of_findings_stays_inside_pagerduty_limits(outcomes: dict[str, Outcome]) -> None:
    (request,) = outcomes["pd-verbose"].listener.to(PD_PATH)
    event = request.json

    assert len(event["payload"]["summary"]) <= 1024
    assert event["payload"]["summary"].endswith("…")
    assert len(event["dedup_key"]) <= 255
    # The summary is clipped; the details are not, so nothing is lost.
    assert len(event["payload"]["custom_details"]["findings"]) == 40


def test_the_opsgenie_alert_is_what_opsgenie_documents(outcomes: dict[str, Outcome]) -> None:
    (request,) = outcomes["og-critical"].listener.to(OG_PATH)
    alert = request.json

    assert request.headers["authorization"] == f"GenieKey {OG_KEY}"
    assert "routing_key" not in alert
    assert len(alert["message"]) <= 130
    assert alert["message"].startswith("critical-host: critical -- ")
    assert alert["alias"] == "linux-vitals:critical-host"
    assert alert["priority"] == "P1"
    assert alert["entity"] == "critical-host"
    assert alert["source"] == "LinuxVitals"
    assert "ram_critical [critical]: RAM usage is critical" in alert["description"]
    assert "failed_logins: lastb exited 1: permission denied" in alert["description"]
    # Every details value is a string, and unknown checks ride along.
    assert all(isinstance(value, str) for value in alert["details"].values())
    assert alert["details"]["unknown_checks"] == "failed_logins: lastb exited 1: permission denied"
    assert alert["details"]["maintenance_id"] == "paging-window"


def test_a_flood_of_findings_stays_inside_opsgenie_limits(outcomes: dict[str, Outcome]) -> None:
    (request,) = outcomes["og-verbose"].listener.to(OG_PATH)
    alert = request.json

    assert len(alert["message"]) <= 130
    assert len(alert["alias"]) <= 512
    assert len(alert["description"]) <= 15000
    assert sum(len(k) + len(v) for k, v in alert["details"].items()) <= 8000
    assert len(alert["tags"]) <= 20 and all(len(tag) <= 50 for tag in alert["tags"])
    assert len(alert["source"]) <= 100


@pytest.mark.parametrize(
    ("severity", "priority"), [("critical", "P1"), ("warning", "P3"), ("info", "P5")]
)
def test_opsgenie_priority_follows_the_worst_finding(
    outcomes: dict[str, Outcome], severity: str, priority: str
) -> None:
    # critical-host is P1 above; warning-host is the warning case.
    if severity == "critical":
        alert = outcomes["og-critical"].listener.to(OG_PATH)[0].json
        assert alert["priority"] == priority
    else:
        template = (REPO_ROOT / "roles/vitals_report/templates/opsgenie_alerts.json.j2").read_text()
        assert f"'{severity}': '{priority}'" in template


def test_both_services_can_be_paged_in_one_run(outcomes: dict[str, Outcome]) -> None:
    both = outcomes["both"].listener

    assert _names(both.to(PD_PATH)) == ["critical-host"]
    assert [r.json["alias"] for r in both.to(OG_PATH)] == ["linux-vitals:critical-host"]


# --- Delivery ---------------------------------------------------------------


def test_a_429_is_retried_and_then_succeeds(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["retry-429"]

    assert len(outcome.listener.to(PD_PATH)) == 2
    assert {r.json["dedup_key"] for r in outcome.listener.to(PD_PATH)} == {"linux-vitals:critical-host"}
    assert outcome.failure is None


def test_a_refusal_is_not_retried_and_fails_the_run_naming_the_host(
    outcomes: dict[str, Outcome],
) -> None:
    outcome = outcomes["refused-400"]

    assert len(outcome.listener.to(PD_PATH)) == 1
    assert outcome.failure is not None
    message = outcome.failure["msg"]
    assert "did not accept 1 of 1 event(s)" in message
    assert "linux-vitals:critical-host (HTTP 400)" in message
    # The listener's reply says "Event object is invalid". The run does not
    # quote a response: the events URL is operator-set, and an endpoint that
    # echoed the request back would put the routing key in the log. The same
    # rule the Slack, email and webhook failures already follow.
    assert "Event object is invalid" not in message
    assert "scripted refusal" not in message


def test_a_service_that_stays_down_is_tried_four_times_then_fails(
    outcomes: dict[str, Outcome],
) -> None:
    outcome = outcomes["down-500"]

    assert len(outcome.listener.to(PD_PATH)) == 4
    assert outcome.failure is not None
    assert "HTTP 500" in outcome.failure["msg"]


def test_an_opsgenie_refusal_fails_the_run_and_is_not_retried(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["og-refused-401"]

    assert len(outcome.listener.to(OG_PATH)) == 1
    assert outcome.failure is not None
    assert "Opsgenie did not accept 1 of 1 alert(s)" in outcome.failure["msg"]
    assert "linux-vitals:critical-host (HTTP 401)" in outcome.failure["msg"]
    assert "scripted refusal" not in outcome.failure["msg"]


# --- Credentials ------------------------------------------------------------


def test_no_credential_reaches_output_or_a_rendered_event_or_an_error(
    outcomes: dict[str, Outcome],
) -> None:
    # The -vvv scenarios are the ones with teeth: they print every task's
    # arguments, so they are the ones that show a send that lost its no_log.
    for name in (
        "pd-critical",
        "refused-400",
        "down-500",
        "og-critical",
        "og-refused-401",
        "both",
        "pd-loud",
        "og-loud",
        "refused-loud",
    ):
        outcome = outcomes[name]
        visible = outcome.output + json.dumps(outcome.rendered["pagerduty"] if outcome.rendered else [])
        visible += json.dumps(outcome.rendered["opsgenie"] if outcome.rendered else [])
        visible += json.dumps(outcome.failure or {})
        for secret in (PD_KEY, OG_KEY):
            assert secret not in visible, f"{name} leaked a credential"


def test_the_loud_runs_really_do_print_arguments_so_the_credential_test_has_teeth(
    outcomes: dict[str, Outcome],
) -> None:
    # Guards the guard: if -vvv stopped printing task arguments, the credential
    # test above would pass for the wrong reason, whatever no_log did.
    output = outcomes["pd-loud"].output

    assert "invocation" in output
    assert "linux-vitals:critical-host" in output or "censored due to no_log" in output


def test_a_switched_on_pager_with_no_key_fails_before_sending_anything(
    outcomes: dict[str, Outcome],
) -> None:
    outcome = outcomes["no-key"]

    assert outcome.listener.received == []
    assert outcome.failure is not None
    assert "PAGERDUTY_ROUTING_KEY" in outcome.failure["msg"]
    assert "linux_vitals_pagerduty_routing_key" in outcome.failure["msg"]


def test_the_key_can_come_from_dotenv_next_to_the_inventory(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["dotenv-key"]

    assert outcome.rendered["effective_pagerduty_key"] == DOTENV_PD_KEY
    assert [r.json["routing_key"] for r in outcome.listener.to(PD_PATH)] == [DOTENV_PD_KEY]
    assert DOTENV_PD_KEY not in outcome.output


def test_a_variable_wins_over_dotenv(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["variable-beats-dotenv"]

    assert outcome.rendered["effective_pagerduty_key"] == PD_KEY
    assert [r.json["routing_key"] for r in outcome.listener.to(PD_PATH)] == [PD_KEY]


# --- Off by default, and misconfiguration -----------------------------------


def test_nothing_is_sent_unless_an_integration_is_switched_on(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["disabled"]

    assert outcome.listener.received == []
    assert outcome.failure is None


def test_an_unusable_floor_fails_the_run_before_anything_is_sent(outcomes: dict[str, Outcome]) -> None:
    outcome = outcomes["bad-floor"]

    assert outcome.listener.received == []
    assert outcome.failure is not None
    assert "must be info, warning or critical" in outcome.failure["msg"]
    assert '"urgent"' in outcome.failure["msg"]


def test_the_role_only_pages_when_an_integration_is_switched_on() -> None:
    tasks = yaml.safe_load(MAIN_TASKS.read_text(encoding="utf-8"))
    paging = next(t for t in tasks if t["name"].startswith("Page for hosts"))
    names = [t["name"] for t in tasks]

    assert paging["ansible.builtin.include_tasks"]["file"] == "paging.yml"
    assert paging["when"] == (
        "linux_vitals_pagerduty_enabled | bool or linux_vitals_opsgenie_enabled | bool"
    )
    # Before the gate, which must stay last so it never hides a failed page.
    assert names.index(paging["name"]) == len(names) - 2
    assert tasks[-1]["name"].startswith("Apply optional fleet health pipeline gate")
