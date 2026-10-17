"""notify.yml and config.yml, end to end, against listeners on 127.0.0.1 (#29).

The 1.0.2 `.env` regression left every channel silently skipped while the
suite stayed green, because nothing ever ran the task files that decide
whether to send, where, and with what. These tests run the real `config.yml`
and `notify.yml` through `ansible-playbook` and assert on what actually
arrives: an HTTP listener stands in for Slack and the generic webhook, and a
minimal SMTP sink for the mail server.

Each scenario is one host in its own generated inventory directory, because
`config.yml` reads `{{ inventory_dir }}/.env`. All of them run as serial
batches of a single `ansible-playbook` invocation, so the suite pays for
Ansible's start-up once (plus once more for extra-vars, which apply to every
host and so need their own run).

**Hermeticity.** A developer checkout usually holds a `.env` with real webhook
and SMTP credentials. The playbook therefore never runs from the checkout: it
runs from a copy of the collection made from an allowlist that cannot include
a `.env`, with every `ANSIBLE_*` and proxy variable dropped from its
environment. The copy is then seeded with decoy `.env` files -- at its root
(the working directory and collection root), next to the playbook, in the role
directory, and above the inventory directories -- all pointing at a second
listener. Any change that made `config.yml` read a `.env` other than the one
next to the inventory would post to the decoy, and the decoy must receive
nothing. Every URL and mail server is on 127.0.0.1.
"""
from __future__ import annotations

import base64
import email
import email.policy
import json
import os
import shutil
import socketserver
import subprocess
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

import pytest
import yaml

from test_templates import REPO_ROOT, _ansible_playbook_bin

FIXTURE = Path("tests") / "fixtures" / "notification_delivery.yml"

# What the sandbox copies from the checkout. An allowlist rather than a copy
# with exclusions, so a .env -- or anything else nobody thought of -- in the
# real checkout can never reach the run.
SANDBOX_ALLOWLIST = ("ansible.cfg", "galaxy.yml", "meta", "plugins", "roles")

HEADER = "LinuxVitals Delivery Fixture"
MAIL_FROM = "linux-vitals-fixture@example.com"
URL_CHANNELS = ("slack", "webhook")
EFFECTIVE_URL = {"slack": "slack_webhook_url", "webhook": "generic_webhook_url"}


# --- Listeners ---------------------------------------------------------------


@dataclass
class HttpRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def scenario(self) -> str | None:
        parts = self.path.strip("/").split("/")
        return parts[0] if len(parts) == 3 else None

    @property
    def channel(self) -> str | None:
        parts = self.path.strip("/").split("/")
        return parts[2] if len(parts) == 3 else None


class _HttpHandler(BaseHTTPRequestHandler):
    def _record(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.record(  # type: ignore[attr-defined]
            HttpRequest(
                method=self.command,
                path=self.path,
                headers={key.lower(): value for key, value in self.headers.items()},
                body=body,
            )
        )
        reply = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _record

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class HttpListener(ThreadingHTTPServer):
    """Records every request and answers 200, as Slack does for a good post."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _HttpHandler)
        self.requests: list[HttpRequest] = []
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def record(self, request: HttpRequest) -> None:
        with self._lock:
            self.requests.append(request)


@dataclass
class SmtpSession:
    commands: list[str] = field(default_factory=list)
    auth: tuple[str, str] | None = None
    mail_from: str | None = None
    rcpt_to: list[str] = field(default_factory=list)
    data: bytes | None = None

    @property
    def scenario(self) -> str | None:
        # Every scenario gives its SMTP user and recipient its own name, so a
        # session can be traced to the scenario that opened it even when it
        # never got as far as a recipient.
        names = {rcpt.split("@", 1)[0] for rcpt in self.rcpt_to}
        if self.auth:
            names.add(self.auth[0].split(".", 1)[0])
        return names.pop() if len(names) == 1 else None

    @property
    def message(self) -> email.message.EmailMessage:
        assert self.data is not None, "the session never sent DATA"
        return email.message_from_bytes(self.data, policy=email.policy.default)  # type: ignore[return-value]


def _address(argument: str) -> str:
    # "FROM:<a@b>" / "TO:<a@b>", optionally followed by ESMTP parameters.
    return argument.split(":", 1)[1].strip().split(" ", 1)[0].strip("<>")


class _SmtpHandler(socketserver.StreamRequestHandler):
    """Just enough SMTP for smtplib: EHLO, AUTH PLAIN/LOGIN, MAIL, RCPT, DATA."""

    timeout = 30

    def _reply(self, *lines: str) -> None:
        self.wfile.write("".join(f"{line}\r\n" for line in lines).encode("ascii"))

    def _line(self) -> str:
        return self.rfile.readline(65536).decode("utf-8", "replace").rstrip("\r\n")

    def _auth(self, argument: str) -> tuple[str, str]:
        mechanism, _, initial = argument.partition(" ")
        if mechanism.upper() == "PLAIN":
            if not initial:
                self._reply("334 ")
                initial = self._line()
            _, user, password = base64.b64decode(initial).decode("utf-8").split("\0")
            return user, password
        # LOGIN
        if not initial:
            self._reply("334 VXNlcm5hbWU6")
            initial = self._line()
        self._reply("334 UGFzc3dvcmQ6")
        password = self._line()
        return (
            base64.b64decode(initial).decode("utf-8"),
            base64.b64decode(password).decode("utf-8"),
        )

    def _data(self) -> bytes:
        lines = []
        while True:
            raw = self.rfile.readline(65536)
            if raw in (b".\r\n", b".\n", b""):
                return b"".join(lines)
            lines.append(raw[1:] if raw.startswith(b"..") else raw)

    def handle(self) -> None:
        session = SmtpSession()
        self.server.record(session)  # type: ignore[attr-defined]
        try:
            self._reply("220 linux-vitals-test-sink ESMTP")
            while True:
                line = self._line()
                if not line:
                    return
                verb, _, argument = line.partition(" ")
                verb = verb.upper()
                session.commands.append(verb)
                if verb == "EHLO":
                    self._reply("250-linux-vitals-test-sink", "250-AUTH PLAIN LOGIN", "250 8BITMIME")
                elif verb == "HELO":
                    self._reply("250 linux-vitals-test-sink")
                elif verb == "AUTH":
                    session.auth = self._auth(argument)
                    self._reply("235 2.7.0 Authentication successful")
                elif verb == "MAIL":
                    session.mail_from = _address(argument)
                    self._reply("250 2.1.0 OK")
                elif verb == "RCPT":
                    session.rcpt_to.append(_address(argument))
                    self._reply("250 2.1.5 OK")
                elif verb == "DATA":
                    self._reply("354 End data with <CR><LF>.<CR><LF>")
                    session.data = self._data()
                    self._reply("250 2.0.0 Queued")
                elif verb in ("RSET", "NOOP"):
                    self._reply("250 2.0.0 OK")
                elif verb == "QUIT":
                    self._reply("221 2.0.0 Bye")
                    return
                else:
                    self._reply("502 5.5.2 Command not recognised")
        except OSError:
            return


class SmtpSink(socketserver.ThreadingTCPServer):
    """Accepts and records every message. Python 3.12 removed smtpd."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _SmtpHandler)
        self._sessions: list[SmtpSession] = []
        self._lock = threading.Lock()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def record(self, session: SmtpSession) -> None:
        with self._lock:
            self._sessions.append(session)

    @property
    def sessions(self) -> list[SmtpSession]:
        # smtplib.SMTP(host, port) connects, and community.general.mail then
        # calls connect() again, so each message leaves one connection that
        # never sent a command. Only connections that said something count.
        with self._lock:
            return [session for session in self._sessions if session.commands]


@contextmanager
def _serving(server: socketserver.BaseServer) -> Iterator[Any]:
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- Scenarios ---------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    name: str
    inventory: dict[str, Any]
    dotenv: str | None  # None: no .env file at all


def _url(base: str, scenario: str, source: str, channel: str) -> str:
    return f"{base}/{scenario}/{source}/{channel}"


def _user(scenario: str, source: str) -> str:
    return f"{scenario}.{source}-user"


def _password(scenario: str, source: str) -> str:
    return f"{scenario}.{source}-password"


def _dotenv(base: str, scenario: str, *, smtp_host: str) -> str:
    return (
        f"SLACK_WEBHOOK_URL={_url(base, scenario, 'dotenv', 'slack')}\n"
        f"GENERIC_WEBHOOK_URL={_url(base, scenario, 'dotenv', 'webhook')}\n"
        f"EMAIL_SMTP_HOST={smtp_host}\n"
        f"EMAIL_SMTP_USERNAME={_user(scenario, 'dotenv')}\n"
        f"EMAIL_SMTP_PASSWORD={_password(scenario, 'dotenv')}\n"
    )


def _email(scenario: str, source: str | None = "inventory", **overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "linux_vitals_email_enabled": True,
        "linux_vitals_email_to": [f"{scenario}@example.com"],
    }
    if source:
        settings.update(
            linux_vitals_email_host="127.0.0.1",
            linux_vitals_email_username=_user(scenario, source),
            linux_vitals_email_password=_password(scenario, source),
        )
    settings.update(overrides)
    return settings


def _main_scenarios(base: str, decoy: str) -> list[Scenario]:
    no_webhook = {"linux_vitals_generic_webhook_enabled": False}
    no_email = {"linux_vitals_email_enabled": False}
    return [
        # Every channel set in inventory *and* .env: inventory must win. The
        # .env mail host is "localhost" so that a flipped precedence is visible
        # in the resolved host while still only ever reaching loopback.
        Scenario(
            "inventory-wins",
            {
                "linux_vitals_slack_webhook_url": _url(base, "inventory-wins", "inventory", "slack"),
                "linux_vitals_generic_webhook_enabled": True,
                "linux_vitals_generic_webhook_url": _url(base, "inventory-wins", "inventory", "webhook"),
                "linux_vitals_generic_webhook_headers": {"Authorization": "Bearer inventory-wins.token"},
                **_email("inventory-wins"),
            },
            _dotenv(base, "inventory-wins", smtp_host="localhost"),
        ),
        # The 1.0.2 regression: nothing in inventory but the on/off switches,
        # so every URL and SMTP setting has to come from .env. Quoted values
        # and a trailing comment, as people actually write them.
        Scenario(
            "dotenv-fallback",
            {"linux_vitals_generic_webhook_enabled": True, **_email("dotenv-fallback", None)},
            (
                f'SLACK_WEBHOOK_URL="{_url(base, "dotenv-fallback", "dotenv", "slack")}"\n'
                f"GENERIC_WEBHOOK_URL='{_url(base, 'dotenv-fallback', 'dotenv', 'webhook')}'  # ops bot\n"
                "EMAIL_SMTP_HOST=127.0.0.1\n"
                f'EMAIL_SMTP_USERNAME="{_user("dotenv-fallback", "dotenv")}"\n'
                f"EMAIL_SMTP_PASSWORD={_password('dotenv-fallback', 'dotenv')}\n"
            ),
        ),
        # No URL or credential anywhere and no .env file: both webhooks skip,
        # and mail goes out without logging in.
        Scenario(
            "neither-set",
            {
                "linux_vitals_generic_webhook_enabled": True,
                **_email("neither-set", None, linux_vitals_email_host="127.0.0.1"),
            },
            None,
        ),
        # .env.example copied as-is (every key empty), plus the shapes a parser
        # could wrongly pick up -- a commented-out key and a longer key ending
        # in the same name -- pointed at the decoy.
        Scenario(
            "dotenv-keys-empty",
            {
                "linux_vitals_generic_webhook_enabled": True,
                **_email("dotenv-keys-empty", None, linux_vitals_email_host="127.0.0.1"),
            },
            (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
            + f"\n# SLACK_WEBHOOK_URL={decoy}/decoy/slack\n"
            + f"OLD_GENERIC_WEBHOOK_URL={decoy}/decoy/webhook\n"
            + "#EMAIL_SMTP_USERNAME=decoy-user\n",
        ),
        # One scenario per skip condition. Everything except the gate is
        # configured, and another channel sends in the same scenario, so
        # "nothing arrived" cannot be explained by a dead listener.
        Scenario(
            "skip-slack-url-empty",
            {
                "linux_vitals_slack_webhook_url": "   ",
                "linux_vitals_generic_webhook_enabled": True,
                "linux_vitals_generic_webhook_url": _url(base, "skip-slack-url-empty", "inventory", "webhook"),
                **no_email,
            },
            None,
        ),
        Scenario(
            "skip-generic-disabled",
            {
                "linux_vitals_slack_webhook_url": _url(base, "skip-generic-disabled", "inventory", "slack"),
                "linux_vitals_generic_webhook_enabled": False,
                "linux_vitals_generic_webhook_url": _url(base, "skip-generic-disabled", "inventory", "webhook"),
                "linux_vitals_generic_webhook_headers": {"Authorization": "Bearer skip-generic-disabled.token"},
                **no_email,
            },
            _dotenv(base, "skip-generic-disabled", smtp_host="127.0.0.1"),
        ),
        Scenario(
            "skip-email-disabled",
            {
                "linux_vitals_slack_webhook_url": _url(base, "skip-email-disabled", "inventory", "slack"),
                **no_webhook,
                **_email("skip-email-disabled", linux_vitals_email_enabled=False),
            },
            None,
        ),
        Scenario(
            "skip-email-no-recipients",
            {
                "linux_vitals_slack_webhook_url": _url(base, "skip-email-no-recipients", "inventory", "slack"),
                **no_webhook,
                **_email("skip-email-no-recipients", linux_vitals_email_to=[]),
            },
            None,
        ),
    ]


def _extra_vars_scenarios(base: str) -> tuple[list[Scenario], dict[str, Any]]:
    # Extra vars apply to every host in the run, so this one gets a run of its own.
    scenario = Scenario(
        "extra-vars-win",
        {"linux_vitals_generic_webhook_enabled": True, **_email("extra-vars-win", None)},
        _dotenv(base, "extra-vars-win", smtp_host="localhost"),
    )
    extra_vars = {
        "linux_vitals_slack_webhook_url": _url(base, "extra-vars-win", "extra", "slack"),
        "linux_vitals_generic_webhook_url": _url(base, "extra-vars-win", "extra", "webhook"),
        "linux_vitals_email_host": "127.0.0.1",
        "linux_vitals_email_username": _user("extra-vars-win", "extra"),
        "linux_vitals_email_password": _password("extra-vars-win", "extra"),
    }
    return [scenario], extra_vars


# --- Running the playbook ----------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    record_path: Path
    inventory_dir: Path
    requests: list[HttpRequest]
    sessions: list[SmtpSession]

    @property
    def raw_record(self) -> dict[str, Any]:
        """The scenario's record, whether or not its sends succeeded."""
        assert self.record_path.exists(), f"{self.name}: the playbook never reached this scenario"
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    @property
    def record(self) -> dict[str, Any]:
        record = self.raw_record
        assert record["failed"] is False, f"{self.name}: {record.get('task')!r} failed: {record.get('msg')}"
        return record

    @property
    def effective(self) -> dict[str, str]:
        return self.record["effective"]

    def expected_json(self, name: str) -> Any:
        rendered = self.record["expected"][name]
        # ansible-core 2.16's template lookup has already parsed JSON output.
        return rendered if isinstance(rendered, (dict, list)) else json.loads(rendered)

    def expected_text(self, name: str) -> str:
        return self.record["expected"][name]

    def received(self, channel: str) -> list[Any]:
        if channel == "email":
            return list(self.sessions)
        return [request for request in self.requests if request.channel == channel]

    def received_paths(self, channel: str) -> list[str]:
        return [request.path for request in self.received(channel)]

    def effective_path(self, channel: str) -> str:
        return urlsplit(self.effective[EFFECTIVE_URL[channel]]).path


@dataclass
class Delivery:
    returncode: int
    output: str
    output_dir: Path
    sandbox: Path
    env: dict[str, str]
    decoys: list[Path]
    scenarios: dict[str, ScenarioResult]
    requests: list[HttpRequest]
    sessions: list[SmtpSession]
    decoy_requests: list[HttpRequest]

    def __getitem__(self, name: str) -> ScenarioResult:
        return self.scenarios[name]


def _build_sandbox(work: Path) -> Path:
    sandbox = work / "checkout"
    sandbox.mkdir()
    for name in SANDBOX_ALLOWLIST:
        source = REPO_ROOT / name
        if source.is_dir():
            shutil.copytree(source, sandbox / name, ignore=shutil.ignore_patterns(".env", "__pycache__"))
        elif source.exists():
            shutil.copy2(source, sandbox / name)
    (sandbox / FIXTURE).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / FIXTURE, sandbox / FIXTURE)
    link = sandbox / ".dev-collections" / "ansible_collections" / "sameeralam3127" / "linux_vitals"
    link.parent.mkdir(parents=True)
    link.symlink_to(sandbox, target_is_directory=True)
    return sandbox


def _hermetic_env(sandbox: Path, work: Path) -> dict[str, str]:
    inherited = os.environ
    # The sandbox comes first, so sameeralam3127.linux_vitals resolves to the
    # copy. The rest is only where community.general may be installed: CI
    # installs it into the checkout's .dev-collections (ansible.cfg's first
    # collections_path entry).
    collection_paths = [
        str(sandbox / ".dev-collections"),
        str(REPO_ROOT / ".dev-collections"),
        str(REPO_ROOT / ".ansible" / "collections"),
        str(Path.home() / ".ansible" / "collections"),
    ]
    for name in ("ANSIBLE_COLLECTIONS_PATH", "ANSIBLE_COLLECTIONS_PATHS"):
        collection_paths += [p for p in inherited.get(name, "").split(os.pathsep) if p]

    # Drop every ANSIBLE_* variable -- ANSIBLE_INVENTORY could add a real
    # inventory, and with it a real .env -- and every proxy, so a post to
    # 127.0.0.1 cannot be routed anywhere else.
    env = {
        key: value
        for key, value in inherited.items()
        if not key.upper().startswith("ANSIBLE_") and not key.upper().endswith("_PROXY")
    }
    env.update(
        ANSIBLE_CONFIG=str(sandbox / "ansible.cfg"),
        ANSIBLE_HOME=str(work / "ansible-home"),
        ANSIBLE_LOCAL_TEMP=str(work / "ansible-tmp"),
        ANSIBLE_REMOTE_TEMP=str(work / "ansible-tmp"),
        ANSIBLE_CACHE_PLUGIN_CONNECTION=str(work / "facts"),
        ANSIBLE_COLLECTIONS_PATH=os.pathsep.join(collection_paths),
        ANSIBLE_RETRY_FILES_ENABLED="false",
        ANSIBLE_NOCOLOR="1",
        NO_PROXY="*",
        no_proxy="*",
        TEST_OUTPUT_DIR=str(work / "out"),
    )
    return env


def _write_inventory(inventories: Path, scenario: Scenario, smtp_port: int) -> Path:
    directory = inventories / scenario.name
    directory.mkdir(parents=True)
    host_vars = {
        "ansible_connection": "local",
        "ansible_python_interpreter": "{{ ansible_playbook_python }}",
        "linux_vitals_email_port": smtp_port,
        **scenario.inventory,
    }
    inventory = {
        "all": {"children": {"lv_delivery_scenarios": {"hosts": {scenario.name: host_vars}}}}
    }
    (directory / "hosts.yml").write_text(yaml.safe_dump(inventory, sort_keys=False), encoding="utf-8")
    if scenario.dotenv is not None:
        (directory / ".env").write_text(scenario.dotenv, encoding="utf-8")
    return directory


def _decoy_dotenv(decoy: str) -> str:
    return (
        f"SLACK_WEBHOOK_URL={decoy}/decoy/slack\n"
        f"GENERIC_WEBHOOK_URL={decoy}/decoy/webhook\n"
        "EMAIL_SMTP_HOST=localhost\n"
        "EMAIL_SMTP_USERNAME=decoy-user\n"
        "EMAIL_SMTP_PASSWORD=decoy-password\n"
    )


def _deliver(work: Path, build: Any) -> Delivery:
    with ExitStack() as stack:
        listener: HttpListener = stack.enter_context(_serving(HttpListener()))
        decoy: HttpListener = stack.enter_context(_serving(HttpListener()))
        sink: SmtpSink = stack.enter_context(_serving(SmtpSink()))
        scenarios, extra_vars = build(listener.base_url, decoy.base_url)

        sandbox = _build_sandbox(work)
        (work / "out").mkdir()
        inventories = work / "inventories"
        inventory_dirs = {
            scenario.name: _write_inventory(inventories, scenario, sink.port) for scenario in scenarios
        }
        decoys = [
            sandbox / ".env",
            sandbox / FIXTURE.parent / ".env",
            sandbox / "roles" / "vitals_report" / ".env",
            inventories / ".env",
        ]
        for path in decoys:
            path.write_text(_decoy_dotenv(decoy.base_url), encoding="utf-8")

        command = [_ansible_playbook_bin(), str(sandbox / FIXTURE)]
        for directory in inventory_dirs.values():
            command += ["-i", str(directory / "hosts.yml")]
        if extra_vars:
            extra_vars_file = work / "extra-vars.json"
            extra_vars_file.write_text(json.dumps(extra_vars), encoding="utf-8")
            command += ["-e", f"@{extra_vars_file}"]

        env = _hermetic_env(sandbox, work)
        completed = subprocess.run(
            command, cwd=sandbox, env=env, capture_output=True, text=True, timeout=600
        )
        requests = list(listener.requests)
        sessions = sink.sessions
        decoy_requests = list(decoy.requests)

    return Delivery(
        returncode=completed.returncode,
        output=completed.stdout + completed.stderr,
        output_dir=work / "out",
        sandbox=sandbox,
        env=env,
        decoys=decoys,
        scenarios={
            scenario.name: ScenarioResult(
                name=scenario.name,
                record_path=work / "out" / f"{scenario.name}.json",
                inventory_dir=inventory_dirs[scenario.name],
                requests=[r for r in requests if r.scenario == scenario.name],
                sessions=[s for s in sessions if s.scenario == scenario.name],
            )
            for scenario in scenarios
        },
        requests=requests,
        sessions=sessions,
        decoy_requests=decoy_requests,
    )


@pytest.fixture(scope="module")
def delivery(tmp_path_factory: pytest.TempPathFactory) -> Delivery:
    return _deliver(
        tmp_path_factory.mktemp("notification-delivery"),
        lambda base, decoy: (_main_scenarios(base, decoy), None),
    )


@pytest.fixture(scope="module")
def extra_vars_delivery(tmp_path_factory: pytest.TempPathFactory) -> Delivery:
    return _deliver(
        tmp_path_factory.mktemp("notification-delivery-extra-vars"),
        lambda base, decoy: _extra_vars_scenarios(base),
    )


@pytest.fixture(scope="module", params=["main", "extra-vars"])
def every_run(request: pytest.FixtureRequest) -> Delivery:
    return request.getfixturevalue("delivery" if request.param == "main" else "extra_vars_delivery")


def _normalise(text: str) -> str:
    # The mail module appends two newlines and SMTP carries CRLF; neither is
    # part of what the template rendered.
    return text.replace("\r\n", "\n").rstrip()


# --- The runs themselves -----------------------------------------------------


def test_every_scenario_ran_and_none_failed(every_run: Delivery) -> None:
    assert every_run.returncode == 0, every_run.output[-4000:]
    # Exactly the generated hosts ran: no inventory but the generated ones
    # reached the play.
    recorded = sorted(path.stem for path in every_run.output_dir.glob("*.json"))
    assert recorded == sorted(every_run.scenarios)
    for result in every_run.scenarios.values():
        # .record names the failing task and its message if the scenario's
        # block was rescued.
        assert result.record["failed"] is False


def test_nothing_arrived_that_no_scenario_sent(every_run: Delivery) -> None:
    known = set(every_run.scenarios)
    stray_requests = [r.path for r in every_run.requests if r.scenario not in known]
    stray_sessions = [(s.auth, s.rcpt_to, s.commands) for s in every_run.sessions if s.scenario not in known]

    assert not stray_requests, f"requests no scenario accounts for: {stray_requests}"
    assert not stray_sessions, f"SMTP sessions no scenario accounts for: {stray_sessions}"


def test_no_dotenv_but_the_one_next_to_the_inventory_is_read(every_run: Delivery) -> None:
    # The decoys sit at every other place a .env could plausibly be looked
    # for. Reading any of them would post to the decoy listener or log in
    # with the decoy user.
    assert every_run.decoy_requests == [], [r.path for r in every_run.decoy_requests]
    assert not [s for s in every_run.sessions if s.auth and "decoy" in s.auth[0]]
    for result in every_run.scenarios.values():
        record = result.raw_record
        assert not [key for key, value in record["effective"].items() if "decoy" in value], record["effective"]
        assert Path(record["inventory_dir"]) == result.inventory_dir


def test_the_run_cannot_see_the_real_checkout(every_run: Delivery) -> None:
    # The checkout may hold a .env with real credentials. Nothing the run is
    # pointed at -- working directory, playbook, config, inventories -- may be
    # inside it, and every .env in the copy must be one of the decoys.
    repo = REPO_ROOT.resolve()
    assert not every_run.sandbox.resolve().is_relative_to(repo)
    assert not Path(every_run.env["ANSIBLE_CONFIG"]).resolve().is_relative_to(repo)
    assert not every_run.env["ANSIBLE_COLLECTIONS_PATH"].startswith(str(repo))
    assert not [key for key in every_run.env if key.upper() == "ANSIBLE_INVENTORY"]
    for result in every_run.scenarios.values():
        assert not result.inventory_dir.resolve().is_relative_to(repo)
        assert Path(result.raw_record["playbook_dir"]).resolve().is_relative_to(every_run.sandbox.resolve())

    sandbox = every_run.sandbox
    found = sorted(p for p in sandbox.rglob(".env") if ".dev-collections" not in p.relative_to(sandbox).parts)
    assert found == sorted(p for p in every_run.decoys if p.is_relative_to(sandbox))


# --- .env precedence ---------------------------------------------------------


@pytest.mark.parametrize("channel", URL_CHANNELS)
def test_an_inventory_url_wins_over_dotenv(delivery: Delivery, channel: str) -> None:
    result = delivery["inventory-wins"]

    assert result.effective_path(channel) == f"/inventory-wins/inventory/{channel}"
    assert result.received_paths(channel) == [f"/inventory-wins/inventory/{channel}"]


@pytest.mark.parametrize("channel", URL_CHANNELS)
def test_an_extra_var_url_wins_over_dotenv(extra_vars_delivery: Delivery, channel: str) -> None:
    result = extra_vars_delivery["extra-vars-win"]

    assert result.effective_path(channel) == f"/extra-vars-win/extra/{channel}"
    assert result.received_paths(channel) == [f"/extra-vars-win/extra/{channel}"]


@pytest.mark.parametrize("channel", URL_CHANNELS)
def test_the_dotenv_url_is_used_when_inventory_is_unset(delivery: Delivery, channel: str) -> None:
    # The 1.0.2 regression: this channel skipped silently and the suite stayed green.
    result = delivery["dotenv-fallback"]

    assert result.effective_path(channel) == f"/dotenv-fallback/dotenv/{channel}"
    assert result.received_paths(channel) == [f"/dotenv-fallback/dotenv/{channel}"]


@pytest.mark.parametrize("scenario", ["neither-set", "dotenv-keys-empty"])
@pytest.mark.parametrize("channel", URL_CHANNELS)
def test_a_channel_with_no_url_anywhere_is_skipped(delivery: Delivery, scenario: str, channel: str) -> None:
    result = delivery[scenario]

    assert result.effective[EFFECTIVE_URL[channel]] == ""
    assert result.record[channel]["skipped"] is True
    assert result.received(channel) == []


@pytest.mark.parametrize(
    ("run", "scenario", "source", "host"),
    [
        ("delivery", "inventory-wins", "inventory", "127.0.0.1"),
        ("extra_vars_delivery", "extra-vars-win", "extra", "127.0.0.1"),
        # The inventory host is left at its default, "localhost", which
        # config.yml treats as unset, so .env's host is used.
        ("delivery", "dotenv-fallback", "dotenv", "127.0.0.1"),
    ],
    ids=["inventory-wins", "extra-vars-win", "dotenv-fallback"],
)
def test_smtp_settings_resolve_in_precedence_order(
    request: pytest.FixtureRequest, run: str, scenario: str, source: str, host: str
) -> None:
    result = request.getfixturevalue(run)[scenario]

    assert result.effective["email_host"] == host
    assert result.effective["email_username"] == _user(scenario, source)
    assert result.effective["email_password"] == _password(scenario, source)
    assert [session.auth for session in result.received("email")] == [
        (_user(scenario, source), _password(scenario, source))
    ]


@pytest.mark.parametrize("scenario", ["neither-set", "dotenv-keys-empty"])
def test_mail_is_sent_without_login_when_no_credentials_are_set(delivery: Delivery, scenario: str) -> None:
    result = delivery[scenario]

    assert result.effective["email_username"] == ""
    assert result.effective["email_password"] == ""
    sessions = result.received("email")
    assert len(sessions) == 1
    assert sessions[0].auth is None
    assert "AUTH" not in sessions[0].commands


# --- The send path -----------------------------------------------------------

SENDING = ["inventory-wins", "dotenv-fallback"]


@pytest.mark.parametrize("scenario", SENDING)
def test_slack_receives_the_rendered_block_kit_payload(delivery: Delivery, scenario: str) -> None:
    result = delivery[scenario]
    (post,) = result.received("slack")

    assert post.method == "POST"
    assert post.headers["content-type"] == "application/json"
    body = json.loads(post.body)
    assert body == result.expected_json("slack")
    # Anchors that do not depend on the expected render, so a template that
    # renders nothing useful cannot pass by agreeing with itself.
    assert body["text"] == "LinuxVitals: PASS — 1 host(s) checked, 0 failing hosts, 0 auto-fixed"
    blocks = body["attachments"][0]["blocks"]
    assert blocks[0]["text"]["text"] == HEADER
    assert any(scenario in block.get("text", {}).get("text", "") for block in blocks)


@pytest.mark.parametrize("scenario", SENDING)
def test_the_generic_webhook_receives_the_rendered_payload(delivery: Delivery, scenario: str) -> None:
    result = delivery[scenario]
    (post,) = result.received("webhook")

    assert post.method == "POST"
    assert post.headers["content-type"] == "application/json"
    body = json.loads(post.body)
    assert body == result.expected_json("webhook")
    assert body["message"] == result.expected_text("message")
    assert body["summary"]["header"] == HEADER
    assert [host["hostname"] for host in body["hosts"]] == [scenario]


def test_the_generic_webhook_sends_the_configured_headers(delivery: Delivery) -> None:
    (with_header,) = delivery["inventory-wins"].received("webhook")
    (without,) = delivery["dotenv-fallback"].received("webhook")

    assert with_header.headers["authorization"] == "Bearer inventory-wins.token"
    assert "authorization" not in without.headers


@pytest.mark.parametrize("scenario", SENDING)
def test_email_carries_the_rendered_summary(delivery: Delivery, scenario: str) -> None:
    result = delivery[scenario]
    (session,) = result.received("email")

    assert session.mail_from == MAIL_FROM
    assert session.rcpt_to == [f"{scenario}@example.com"]
    message = session.message
    assert message["Subject"] == f"LinuxVitals delivery fixture: {scenario}"
    assert message["To"] == f"{scenario}@example.com"
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert _normalise(body) == _normalise(result.expected_text("message"))
    assert body.startswith(f"{HEADER}\nOverall Status: PASS\n")
    assert f"- {scenario} (127.0.0.1) | Status: Pass" in body


@pytest.mark.parametrize("scenario", SENDING)
def test_a_delivered_email_is_not_reported_as_a_failure(delivery: Delivery, scenario: str) -> None:
    # Until #29 notify.yml took `changed` as the mail module's success signal.
    # community.general.mail never sets it, so every delivered email failed
    # the run, and the generic webhook queued after it was never sent.
    result = delivery[scenario]

    assert len(result.received("email")) == 1
    assert result.record["email"]["msg"] == "Mail sent successfully"
    assert result.record["failed"] is False
    assert len(result.received("webhook")) == 1


# --- Skip conditions ---------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "channel", "control"),
    [
        pytest.param("skip-slack-url-empty", "slack", "webhook", id="slack-url-empty"),
        pytest.param("skip-generic-disabled", "webhook", "slack", id="generic-webhook-disabled"),
        pytest.param("skip-email-disabled", "email", "slack", id="email-disabled"),
        pytest.param("skip-email-no-recipients", "email", "slack", id="email-no-recipients"),
    ],
)
def test_a_skip_condition_skips_the_send_and_nothing_arrives(
    delivery: Delivery, scenario: str, channel: str, control: str
) -> None:
    result = delivery[scenario]

    assert result.record[channel]["skipped"] is True, result.record
    assert result.received(channel) == []
    # Another channel in the same scenario did arrive, so the listener was up
    # and notify.yml ran; the silence above is the skip, not a dead endpoint.
    assert result.record[control]["skipped"] is False, result.record
    assert len(result.received(control)) == 1
