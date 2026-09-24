"""Guards for constructs ansible-core 2.16 cannot parse.

2.16 is the floor declared in `meta/runtime.yml`, but CI runs only on a much
newer core (see issue #47), so nothing in the normal suite exercises it. These
are static checks on the source, because a runtime test passes on the core it
happens to run on and would not catch the problem on a newer one.

The construct that bit us: a Jinja string literal containing both a double and
a single quote. 2.16's templating cannot lex it and fails the whole task with
"unexpected char" before the expression ever runs -- which took out every
`vitals_report` run on 2.16, with `no_log` hiding the reason.

Deliberately narrow. An escaped backslash alone is fine: `'\\.service$'` in
`vitals_heal` and `'^\\s*system boot\\s+'` in `vitals_scan` were both checked
against a real 2.16.3 and evaluate correctly, so flagging them would mean
changing working code for no reason. It is the mixed quotes that break.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(
    [*(REPO_ROOT / "roles").glob("*/tasks/*.yml"), *(REPO_ROOT / "roles").glob("*/templates/*.j2")]
)

# Jinja string literals: '...' or "...", including backslash escapes.
STRING_LITERAL = re.compile(r"""'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*\"""", re.VERBOSE)
JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.DOTALL)


def _bad_literals(text: str) -> list[str]:
    bad = []
    for expr in JINJA_EXPR.findall(text):
        for lit in STRING_LITERAL.findall(expr):
            body = lit[1:-1]
            # A literal that carries both quote characters is the shape 2.16
            # cannot lex, however it is escaped.
            if '"' in body and "'" in body:
                bad.append(lit)
    return bad


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: f"{p.parts[-3]}/{p.name}")
def test_no_jinja_literal_breaks_core_216(path: Path) -> None:
    bad = _bad_literals(path.read_text(encoding="utf-8"))

    assert not bad, (
        f"{path.relative_to(REPO_ROOT)}: Jinja string literal(s) ansible-core 2.16 "
        f"cannot parse: {bad}. Avoid mixing \" and ' (and \\\\) inside one literal -- "
        f"capture loosely and clean up with filters instead."
    )


def test_env_regexes_contain_no_quote_characters() -> None:
    # The specific regression, pinned: config.yml's .env patterns must stay
    # quote-free so they remain expressible on 2.16.
    config = (REPO_ROOT / "roles" / "vitals_report" / "tasks" / "config.yml").read_text(
        encoding="utf-8"
    )
    patterns = re.findall(r"regex_findall\((.*?)\)", config)

    assert patterns, "expected regex_findall patterns in config.yml"
    for pattern in patterns:
        body = pattern.strip()[1:-1]
        assert '"' not in body and "\\\\" not in body, (
            f"config.yml .env pattern is not 2.16-safe: {pattern}"
        )


def test_the_guard_catches_the_original_shape() -> None:
    # Prove the detector works, so it cannot silently stop matching.
    original = """{{ x | regex_findall("(?m)^K=[\\"']?([^\\"'\\\\n#]+)[\\"']?$") }}"""
    assert _bad_literals(original), "guard failed to flag the pre-fix pattern"
    fixed = """{{ x | regex_findall('(?m)^K=(.*)$') | trim('"') }}"""
    assert not _bad_literals(fixed), "guard false-positives on the fixed pattern"


# `lookup('ansible.builtin.template', ...) | from_json`: on 2.16 the lookup
# has already turned JSON-looking output into a dict, and from_json raises on
# it. On newer cores the lookup returns a string and the pipe works, so only a
# static check sees it. This took out every generic webhook send on 2.16 (#85).
TEMPLATE_LOOKUP_INTO_FROM_JSON = re.compile(
    r"lookup\(\s*['\"]ansible\.builtin\.template['\"][^)]*\)\s*\|\s*from_json"
)


@pytest.mark.parametrize(
    "path", sorted((REPO_ROOT / "roles").glob("*/tasks/*.yml")), ids=lambda p: f"{p.parts[-3]}/{p.name}"
)
def test_no_template_lookup_is_piped_into_from_json(path: Path) -> None:
    offenders = TEMPLATE_LOOKUP_INTO_FROM_JSON.findall(path.read_text(encoding="utf-8"))

    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)}: {offenders} -- on ansible-core 2.16 the template "
        f"lookup already returns a dict here, so from_json fails. Parse only a string: "
        f"`payload if payload is mapping else payload | from_json`."
    )


def test_the_from_json_guard_catches_the_original_shape() -> None:
    original = "body: {{ lookup('ansible.builtin.template', 'generic_webhook_payload.json.j2') | from_json }}"
    assert TEMPLATE_LOOKUP_INTO_FROM_JSON.search(original), "guard failed to flag the pre-fix shape"
    fixed = "{{ payload if payload is mapping else payload | from_json }}"
    assert not TEMPLATE_LOOKUP_INTO_FROM_JSON.search(fixed), "guard false-positives on the fixed shape"
