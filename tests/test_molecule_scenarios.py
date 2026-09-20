"""Structural/consistency tests for the Molecule scenarios added by this PR.

These do not require Docker or Molecule itself -- they parse the YAML
configuration files under `molecule/` and the CI workflow and check that the
pieces which have to agree with each other (the CI matrix, the scenario
directories, the host_vars that `molecule/resources/verify.yml` reads, the
playbook paths each scenario points at) actually do, and that the release
metadata touched by this PR (`galaxy.yml`, `CHANGELOG.md`,
`requirements-dev.txt`) is internally consistent.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MOLECULE_DIR = REPO_ROOT / "molecule"
RESOURCES_DIR = MOLECULE_DIR / "resources"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Every host_vars key molecule/resources/verify.yml or prepare.yml reads from
# a scenario's inventory.
REQUIRED_HOST_VARS = {
    "ansible_python_interpreter",
    "vitals_python_interpreter",
    "vitals_python_package",
    "vitals_expected_os_family",
    "vitals_expected_package_manager",
    "vitals_expected_reboot_sources",
    "vitals_test_time_sync_service",
    "vitals_test_packages",
}


def _scenario_dirs() -> list[Path]:
    # Called during collection to parametrise, so it must not raise: a missing
    # molecule/ directory should fail one explicit test, not abort the run.
    if not MOLECULE_DIR.is_dir():
        return []
    return sorted(
        path
        for path in MOLECULE_DIR.iterdir()
        if path.is_dir() and path.name != "resources"
    )


def test_molecule_scenarios_are_present() -> None:
    assert _scenario_dirs(), f"no Molecule scenarios found under {MOLECULE_DIR}"


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ci_matrix_scenarios() -> list[str]:
    workflow = _load_yaml(CI_WORKFLOW)
    return workflow["jobs"]["molecule"]["strategy"]["matrix"]["scenario"]


def test_ci_matrix_covers_exactly_the_scenario_directories() -> None:
    scenario_names = {path.name for path in _scenario_dirs()}
    matrix_names = set(_ci_matrix_scenarios())

    assert matrix_names == scenario_names


def test_ci_matrix_has_no_duplicate_scenarios() -> None:
    matrix = _ci_matrix_scenarios()

    assert len(matrix) == len(set(matrix))


def test_validate_job_lints_the_molecule_directory() -> None:
    workflow = _load_yaml(CI_WORKFLOW)
    steps = workflow["jobs"]["validate"]["steps"]
    lint_step = next(step for step in steps if step.get("name") == "Run ansible-lint")

    assert "molecule/" in lint_step["run"]


def test_molecule_job_depends_on_the_validate_job() -> None:
    workflow = _load_yaml(CI_WORKFLOW)

    assert workflow["jobs"]["molecule"]["needs"] == "validate"


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_molecule_yml_is_well_formed(scenario_dir: Path) -> None:
    config = _load_yaml(scenario_dir / "molecule.yml")

    assert config["scenario"]["name"] == scenario_dir.name
    assert config["platforms"][0]["name"] == f"linux-vitals-{scenario_dir.name}"
    assert config["driver"]["name"] == "default"
    assert config["provisioner"]["name"] == "ansible"

    # Every declared playbook must resolve to a real file under
    # molecule/resources/.
    playbooks = config["provisioner"]["playbooks"]
    for phase, relative_path in playbooks.items():
        resolved = (scenario_dir / relative_path).resolve()
        assert resolved.exists(), f"{scenario_dir.name}: {phase} playbook {relative_path} is missing"
        assert resolved.parent == RESOURCES_DIR


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_test_sequence_creates_and_destroys(scenario_dir: Path) -> None:
    config = _load_yaml(scenario_dir / "molecule.yml")
    sequence = config["scenario"]["test_sequence"]

    assert sequence[0] == "dependency"
    assert "create" in sequence
    assert "converge" in sequence
    assert "verify" in sequence
    assert sequence.index("create") < sequence.index("converge") < sequence.index("verify")
    # Reports are freshly timestamped on every run, so idempotence is
    # deliberately not part of the sequence.
    assert "idempotence" not in sequence
    assert sequence.count("destroy") >= 1


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_declares_the_host_vars_verify_yml_depends_on(scenario_dir: Path) -> None:
    config = _load_yaml(scenario_dir / "molecule.yml")
    host_vars = config["provisioner"]["inventory"]["host_vars"]
    instance_name = f"linux-vitals-{scenario_dir.name}"

    assert instance_name in host_vars
    declared = set(host_vars[instance_name].keys())
    missing = REQUIRED_HOST_VARS - declared
    assert not missing, f"{scenario_dir.name} is missing host_vars: {missing}"

    assert isinstance(host_vars[instance_name]["vitals_expected_reboot_sources"], list)
    assert len(host_vars[instance_name]["vitals_expected_reboot_sources"]) >= 1


def test_shared_collections_file_pins_community_docker() -> None:
    # One shared file rather than one per scenario: CI installs the very same
    # file for both the lint job and the Molecule jobs, so the harness cannot
    # drift from what ansible-lint resolves against.
    config = _load_yaml(MOLECULE_DIR / "collections.yml")
    names = {c["name"] for c in config["collections"]}

    assert "community.docker" in names


@pytest.mark.parametrize("scenario_dir", _scenario_dirs(), ids=lambda p: p.name)
def test_scenario_points_its_galaxy_dependency_at_the_shared_file(scenario_dir: Path) -> None:
    config = _load_yaml(scenario_dir / "molecule.yml")
    options = config["dependency"]["options"]

    assert options["requirements-file"] == "molecule/collections.yml"
    assert (REPO_ROOT / options["requirements-file"]).exists()


def test_scenarios_cover_debian_redhat_and_suse_families() -> None:
    # Rocky and Fedora both stand in for the RedHat family by design (see
    # docs/testing.md); Ubuntu and openSUSE are the only Debian/Suse coverage.
    families_by_scenario = {}
    for scenario_dir in _scenario_dirs():
        config = _load_yaml(scenario_dir / "molecule.yml")
        instance_name = f"linux-vitals-{scenario_dir.name}"
        host_vars = config["provisioner"]["inventory"]["host_vars"][instance_name]
        families_by_scenario[scenario_dir.name] = host_vars["vitals_expected_os_family"]

    assert set(families_by_scenario.values()) == {"Debian", "RedHat", "Suse"}
    assert families_by_scenario["rocky"] == "RedHat"
    assert families_by_scenario["fedora"] == "RedHat"
    assert families_by_scenario["ubuntu"] == "Debian"
    assert families_by_scenario["opensuse"] == "Suse"


def test_reboot_sources_are_not_shared_across_incompatible_distros() -> None:
    # A regression that made every scenario silently accept the same reboot
    # source would defeat the point of running all four.
    per_scenario_sources = {}
    for scenario_dir in _scenario_dirs():
        config = _load_yaml(scenario_dir / "molecule.yml")
        instance_name = f"linux-vitals-{scenario_dir.name}"
        host_vars = config["provisioner"]["inventory"]["host_vars"][instance_name]
        per_scenario_sources[scenario_dir.name] = set(host_vars["vitals_expected_reboot_sources"])

    assert per_scenario_sources["opensuse"] == {"zypper-needs-rebooting"}
    assert "zypper-needs-rebooting" not in per_scenario_sources["ubuntu"]
    assert "zypper-needs-rebooting" not in per_scenario_sources["rocky"]
    assert "zypper-needs-rebooting" not in per_scenario_sources["fedora"]


def test_resources_playbooks_are_valid_yaml() -> None:
    for playbook in ("create.yml", "destroy.yml", "prepare.yml", "converge.yml", "verify.yml"):
        document = _load_yaml(RESOURCES_DIR / playbook)
        assert isinstance(document, list) and len(document) >= 1


def test_converge_playbook_runs_scan_then_heal_then_report_in_order() -> None:
    document = _load_yaml(RESOURCES_DIR / "converge.yml")
    roles = [entry["role"] for entry in document[0]["roles"]]

    assert roles == [
        "sameeralam3127.linux_vitals.vitals_scan",
        "sameeralam3127.linux_vitals.vitals_heal",
        "sameeralam3127.linux_vitals.vitals_report",
    ]


def test_converge_playbook_opts_into_self_healing() -> None:
    document = _load_yaml(RESOURCES_DIR / "converge.yml")

    assert document[0]["vars"]["linux_vitals_heal_enabled"] is True


def test_prepare_playbook_plants_both_a_healable_and_an_unfixable_unit() -> None:
    document = _load_yaml(RESOURCES_DIR / "prepare.yml")
    install_units_task = next(
        task for task in document[0]["tasks"] if task.get("name") == "Install the test units"
    )
    unit_names = {item["name"] for item in install_units_task["loop"]}

    assert unit_names == {"molecule-flaky.service", "molecule-broken.service"}

    broken = next(item for item in install_units_task["loop"] if item["name"] == "molecule-broken.service")
    assert broken["exec_start"] == "/bin/false"


def test_galaxy_version_matches_changelog_latest_entry() -> None:
    galaxy = _load_yaml(REPO_ROOT / "galaxy.yml")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    version = galaxy["version"]
    # Deliberately not pinned to a literal: this asserts the release bookkeeping
    # stays consistent, so a version bump with no changelog entry (or vice
    # versa) fails, while an ordinary bump does not.
    #
    # An "[Unreleased]" heading is skipped rather than compared: CONTRIBUTING.md
    # tells contributors to accumulate entries there between releases, and
    # publishing is what moves that section under a new version heading. What
    # must agree with galaxy.yml is the newest *released* heading.
    headings = re.findall(r"^## \[([^\]]+)\]", changelog, re.MULTILINE)
    assert headings, "CHANGELOG.md has no version headings"
    released = [h for h in headings if h.lower() != "unreleased"]
    assert released, "CHANGELOG.md has no released version headings"
    assert version == released[0], (
        f"galaxy.yml is {version} but the newest released CHANGELOG entry is {released[0]}"
    )


def test_galaxy_build_ignore_excludes_molecule_directory() -> None:
    galaxy = _load_yaml(REPO_ROOT / "galaxy.yml")

    assert "molecule" in galaxy["build_ignore"]
    assert "tests" in galaxy["build_ignore"]


def test_requirements_dev_pins_molecule_and_docker_sdk() -> None:
    requirements = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    assert re.search(r"^molecule>=", requirements, re.MULTILINE)
    assert re.search(r"^docker>=", requirements, re.MULTILINE)


def test_testing_doc_links_to_files_that_exist() -> None:
    testing_doc = (REPO_ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    for relative_link in re.findall(r"\]\((?!https?://)([^)]+)\)", testing_doc):
        target = (REPO_ROOT / "docs" / relative_link).resolve()
        assert target.exists(), f"docs/testing.md links to missing file: {relative_link}"


def test_readme_links_to_the_testing_doc() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/testing.md" in readme
    assert (REPO_ROOT / "docs" / "testing.md").exists()
