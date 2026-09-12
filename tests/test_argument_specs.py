"""Every role's `meta/argument_specs.yml` must match its `defaults/main.yml`.

The argument spec is what `ansible-doc -t role` renders and what validates an
operator's overrides at role entry. It is only useful while it stays in step
with the defaults it documents, and nothing about editing one file forces you
to edit the other -- so that agreement is asserted here rather than trusted.

These tests read the shipped YAML directly; they need no hosts, no Docker, and
no collection install.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO_ROOT / "roles"

# Variables a role reads but does not own, so they are documented by the role
# whose defaults/main.yml defines them rather than being duplicated here.
ROLE_NAMES = ("vitals_scan", "vitals_heal", "vitals_report")


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _spec_options(role: str) -> dict:
    spec = _load(ROLES_DIR / role / "meta" / "argument_specs.yml")
    entrypoints = spec["argument_specs"]
    assert "main" in entrypoints, f"{role} argument spec has no 'main' entry point"
    return entrypoints["main"].get("options") or {}


def _defaults(role: str) -> dict:
    return _load(ROLES_DIR / role / "defaults" / "main.yml")


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_every_role_has_an_argument_spec(role: str) -> None:
    assert (ROLES_DIR / role / "meta" / "argument_specs.yml").is_file()


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_spec_documents_exactly_the_role_defaults(role: str) -> None:
    # Both directions matter: an undocumented default is invisible to
    # `ansible-doc`, and a documented variable with no default is a spec
    # describing a variable the role no longer owns.
    documented = set(_spec_options(role))
    defined = set(_defaults(role))

    assert documented == defined, (
        f"{role}: undocumented in argument_specs.yml: {sorted(defined - documented)}; "
        f"documented but absent from defaults/main.yml: {sorted(documented - defined)}"
    )


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_spec_defaults_match_the_actual_defaults(role: str) -> None:
    options = _spec_options(role)
    defaults = _defaults(role)

    mismatched = {
        name: (option.get("default"), defaults[name])
        for name, option in options.items()
        if name in defaults and option.get("default") != defaults[name]
    }

    assert not mismatched, f"{role}: spec default != defaults/main.yml for {mismatched}"


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_every_option_has_a_type_and_a_description(role: str) -> None:
    missing = {
        name: [
            field
            for field in ("type", "description")
            if not option.get(field)
        ]
        for name, option in _spec_options(role).items()
        if not option.get("type") or not option.get("description")
    }

    assert not missing, f"{role}: options missing type/description: {missing}"


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_no_option_is_required(role: str) -> None:
    # Every variable has a working default and the roles must stay runnable
    # with no configuration at all. linux_vitals_maintenance_id is the one
    # conditionally-required variable, and vitals_report's snapshot.yml asserts
    # it with a better message than an argspec could give.
    required = [
        name
        for name, option in _spec_options(role).items()
        if option.get("required")
    ]

    assert not required, f"{role}: options must not be required: {required}"


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_spec_declares_the_role_short_description_and_author(role: str) -> None:
    main = _load(ROLES_DIR / role / "meta" / "argument_specs.yml")["argument_specs"]["main"]

    assert main.get("short_description")
    assert main.get("description")
    assert main.get("author")


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_choices_include_the_default(role: str) -> None:
    offenders = {
        name: (option["default"], option["choices"])
        for name, option in _spec_options(role).items()
        if option.get("choices") and option.get("default") not in option["choices"]
    }

    assert not offenders, f"{role}: default not among choices for {offenders}"


@pytest.mark.parametrize("role", ROLE_NAMES)
def test_every_documented_variable_uses_the_collection_prefix(role: str) -> None:
    # The three roles deliberately share one flat linux_vitals_* namespace --
    # see docs/architecture.md and the var-naming[no-role-prefix] skip in
    # .ansible-lint.
    offenders = [
        name for name in _spec_options(role) if not name.startswith("linux_vitals_")
    ]

    assert not offenders, f"{role}: variables outside the namespace: {offenders}"
