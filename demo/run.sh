#!/usr/bin/env bash
#
# One-command LinuxVitals demo: three distros, real faults, a real dashboard.
#
#   ./run.sh              full walkthrough: up -> scan -> break -> scan -> heal
#   ./run.sh up           start and provision the containers (healthy)
#   ./run.sh scan         read-only health check, opens the dashboard
#   ./run.sh break        inject the faults
#   ./run.sh heal         re-run with self-healing enabled
#   ./run.sh repair       undo the faults, keep the containers
#   ./run.sh clean        remove containers, network, and demo output
#
# Everything is written under demo/ and removed by `clean`. Nothing touches
# your real inventory, and nothing outside Docker is modified.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DEMO_DIR}/.." && pwd)"
COMPOSE_FILE="${DEMO_DIR}/docker-compose.yml"
INVENTORY="${DEMO_DIR}/inventory.ini"
REPORT="${DEMO_DIR}/reports/linux_vitals_report.html"

# ansible.cfg's collections_path starts with the repo-local .dev-collections
# symlink, which is what makes this repo resolve as sameeralam3127.linux_vitals
# without installing it from Galaxy first.
export ANSIBLE_CONFIG="${REPO_DIR}/ansible.cfg"

# Stop Ansible logging every module invocation into the target's journal.
#
# Without this the demo scans a host Ansible has just been busy on, and the
# dashboard's "Recent log errors" panel fills with Ansible's own argv records --
# which match the scan's error filter, because a line reading
# `argv=['systemctl', 'is-failed', ...]` contains the word "failed". The
# injected faults are then buried in the scanner's own footprint.
#
# Worth knowing outside the demo too: on a real fleet this is a genuine
# false-positive source in the log-error count, and `no_target_syslog` is the
# switch that removes it.
export ANSIBLE_NO_TARGET_SYSLOG=True

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m    %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed."
  docker info >/dev/null 2>&1 || die "the Docker daemon is not running. Start Docker Desktop (or dockerd) and try again."
}

require_ansible() {
  command -v ansible-playbook >/dev/null 2>&1 \
    || die "ansible-playbook is not on PATH. See the Quick Start in the top-level README."
}

ensure_collection_link() {
  # Same symlink molecule/resources/create.yml maintains, for the same reason:
  # FQCN role names have to resolve to this working tree, not to whatever
  # version of the collection happens to be installed.
  local link="${REPO_DIR}/.dev-collections/ansible_collections/sameeralam3127/linux_vitals"
  mkdir -p "$(dirname "${link}")"
  [ -L "${link}" ] || ln -sfn "${REPO_DIR}" "${link}"
}

ensure_requirements() {
  ansible-galaxy collection list community.docker >/dev/null 2>&1 && return 0
  say "Installing the demo's collection dependencies"
  ansible-galaxy collection install -r "${DEMO_DIR}/requirements.yml"
  ansible-galaxy collection install -r "${REPO_DIR}/requirements.yml"
}

play() {
  local playbook="$1"; shift
  ansible-playbook -i "${INVENTORY}" "${playbook}" "$@"
}

wait_for_systemd() {
  local container="$1" tries=45
  while [ "${tries}" -gt 0 ]; do
    # "degraded" is the normal end state in a container -- units that need real
    # hardware fail -- so anything that has finished initialising will do.
    case "$(docker exec "${container}" systemctl is-system-running 2>/dev/null || true)" in
      running|degraded) return 0 ;;
    esac
    tries=$((tries - 1))
    sleep 2
  done
  die "systemd did not finish booting in ${container}."
}

open_report() {
  [ -f "${REPORT}" ] || { warn "No report at ${REPORT} yet."; return 0; }
  say "Dashboard: ${REPORT}"
  case "$(uname -s)" in
    Darwin) open "${REPORT}" >/dev/null 2>&1 || true ;;
    Linux)
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "${REPORT}" >/dev/null 2>&1 || true
      fi
      ;;
  esac
}

cmd_up() {
  require_docker; require_ansible
  ensure_collection_link
  ensure_requirements
  say "Starting the demo fleet (Ubuntu 24.04, Rocky 9, Fedora 42)"
  docker compose -f "${COMPOSE_FILE}" up -d
  for c in linux-vitals-demo-ubuntu linux-vitals-demo-rocky linux-vitals-demo-fedora; do
    wait_for_systemd "${c}"
  done
  say "Provisioning the fleet"
  play "${DEMO_DIR}/playbooks/provision.yml" "$@"
}

cmd_scan() {
  require_docker; require_ansible
  say "Running the read-only health check"
  play "${REPO_DIR}/playbooks/healthcheck.yml" "$@"
  open_report
}

cmd_break() {
  require_docker; require_ansible
  say "Injecting faults: failed services, reboot required, /boot pressure, journal errors, memory threshold"
  play "${DEMO_DIR}/playbooks/break.yml" "$@"
  warn "Run './run.sh scan' to see them detected, then './run.sh heal' to see them remediated."
}

cmd_heal() {
  require_docker; require_ansible
  say "Re-running with self-healing enabled (-e linux_vitals_heal_enabled=true)"
  warn "This is the only step in the demo that changes anything on a managed host."
  play "${REPO_DIR}/playbooks/healthcheck.yml" -e linux_vitals_heal_enabled=true "$@"
  open_report
}

cmd_repair() {
  require_docker; require_ansible
  say "Clearing the injected faults"
  play "${DEMO_DIR}/playbooks/repair.yml" "$@"
}

cmd_clean() {
  say "Removing containers, network, and demo output"
  if command -v docker >/dev/null 2>&1; then
    # Not fatal: `clean` must still remove the demo's files on a machine where
    # Docker has since been removed or stopped.
    docker compose -f "${COMPOSE_FILE}" down -v --remove-orphans || true
  fi
  rm -rf "${DEMO_DIR}/reports" "${DEMO_DIR}/group_vars/all/10-injected.yml"
  say "Clean."
}

cmd_all() {
  cmd_up
  say "STEP 1 of 3 -- a healthy fleet"
  cmd_scan
  cmd_break
  say "STEP 2 of 3 -- the same fleet, now broken"
  cmd_scan
  say "STEP 3 of 3 -- self-healing"
  cmd_heal
  cat <<EOF

Done. What to look at, in order:
  * demo/reports/archive/   one dashboard per run -- healthy, broken, healed
  * the Health Score banner falling between run 1 and run 2, and recovering in run 3
  * demo-payments-api.service   restarted and reported "Fixed"
  * demo-log-shipper.service    not fixable; reported as needing manual follow-up
  * ./run.sh clean          when you are finished

EOF
}

# Anything after the subcommand is handed straight to ansible-playbook, so
# `./run.sh break --tags service` demonstrates one check at a time.
subcommand="${1:-all}"
[ $# -gt 0 ] && shift

case "${subcommand}" in
  all|"")  cmd_all ;;
  up)      cmd_up "$@" ;;
  scan)    cmd_scan "$@" ;;
  break)   cmd_break "$@" ;;
  heal)    cmd_heal "$@" ;;
  repair)  cmd_repair "$@" ;;
  clean)   cmd_clean ;;
  -h|--help|help)
           # Print the header comment block and stop at the first line that
           # is not part of it, so the help text cannot drift from the file.
           awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}" ;;
  *)       die "Unknown command '${subcommand}'. Try: ./run.sh help" ;;
esac
