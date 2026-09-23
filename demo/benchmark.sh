#!/usr/bin/env bash
#
# Measure what LinuxVitals costs to run, as a function of fleet size.
#
#   ./benchmark.sh 10            one run against 10 hosts
#   ./benchmark.sh 10 25 50      one run per size, as a table
#   FORKS=50 ./benchmark.sh 50   override the fork count (default: fleet size)
#
# What this measures, precisely: wall-clock time, peak control-node RSS, and
# control-node CPU seconds for a full scan + render against N systemd
# containers on this machine.
#
# What it does NOT measure: network latency, SSH handshake cost, or real disk
# and journal sizes. Containers are local and their journals are seconds old.
# Treat the results as a *control-plane lower bound* -- the cost of Ansible's
# own fan-out, fact gathering, and report rendering, with per-host work at its
# cheapest. A real fleet is slower. See docs/performance.md for how to run this
# against real hosts, which is the only way to get numbers worth publishing.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DEMO_DIR}/.." && pwd)"
WORK="${DEMO_DIR}/.bench"
IMAGE="${IMAGE:-geerlingguy/docker-ubuntu2404-ansible:latest}"
NETWORK="linux-vitals-bench"

export ANSIBLE_CONFIG="${REPO_DIR}/ansible.cfg"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is not installed."
docker info >/dev/null 2>&1 || die "the Docker daemon is not running."
command -v ansible-playbook >/dev/null 2>&1 || die "ansible-playbook is not on PATH."

SIZES=("$@")
[[ ${#SIZES[@]} -gt 0 ]] || SIZES=(5)

teardown() {
  docker ps -aq --filter "name=lv-bench-" | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap teardown EXIT

start_fleet() {
  local n="$1" i
  docker network create "${NETWORK}" >/dev/null 2>&1 || true
  for i in $(seq 1 "${n}"); do
    docker run -d --name "lv-bench-${i}" --hostname "bench-${i}" \
      --network "${NETWORK}" --privileged --cgroupns=host \
      -v /sys/fs/cgroup:/sys/fs/cgroup:rw --tmpfs /run --tmpfs /run/lock \
      "${IMAGE}" /usr/lib/systemd/systemd >/dev/null
  done
  # Wait for the last one; they boot in parallel and take about the same time.
  local tries=60
  while [[ "${tries}" -gt 0 ]]; do
    case "$(docker exec "lv-bench-${n}" systemctl is-system-running 2>/dev/null || true)" in
      running|degraded) return 0 ;;
    esac
    tries=$((tries - 1)); sleep 2
  done
  die "systemd did not finish booting in the benchmark fleet."
}

write_inventory() {
  local n="$1" i
  mkdir -p "${WORK}"
  {
    echo "[linux_servers]"
    for i in $(seq 1 "${n}"); do echo "bench-${i} ansible_host=lv-bench-${i}"; done
    echo
    echo "[linux_servers:vars]"
    echo "ansible_connection=community.docker.docker"
    echo "ansible_user=root"
    echo "ansible_python_interpreter=/usr/bin/python3"
  } > "${WORK}/inventory.ini"
  mkdir -p "${WORK}/group_vars"
  cat > "${WORK}/group_vars/all.yml" <<'YAML'
---
# Notifications off: a benchmark should not measure someone else's API.
linux_vitals_heal_enabled: false
linux_vitals_email_enabled: false
linux_vitals_generic_webhook_enabled: false
linux_vitals_archive_html_reports: false
linux_vitals_archive_json_reports: false
YAML
}

# GNU time reports peak RSS and CPU seconds; macOS /usr/bin/time -l does too,
# with different labels. Prefer gtime when present, fall back to the system one.
timer_cmd() {
  if command -v gtime >/dev/null 2>&1; then echo "gtime -v"
  elif /usr/bin/time -l true >/dev/null 2>&1; then echo "/usr/bin/time -l"
  else echo "/usr/bin/time -p"; fi
}

run_size() {
  local n="$1" forks="${FORKS:-$1}"
  local log="${WORK}/run-${n}.log"
  say "Fleet of ${n} (forks=${forks})"
  start_fleet "${n}"
  write_inventory "${n}"

  # One warm-up run: the first pass pays for fact-cache population and the
  # Python interpreter discovery, which is a one-time cost, not a scaling one.
  ansible-playbook -i "${WORK}/inventory.ini" -f "${forks}" \
    "${REPO_DIR}/playbooks/healthcheck.yml" >/dev/null 2>&1 || true

  local start end
  start="$(date +%s.%N)"
  # shellcheck disable=SC2086
  $(timer_cmd) ansible-playbook -i "${WORK}/inventory.ini" -f "${forks}" \
    "${REPO_DIR}/playbooks/healthcheck.yml" > "${log}" 2>&1 || true
  end="$(date +%s.%N)"

  local wall rss cpu
  wall="$(printf '%.1f' "$(echo "${end} - ${start}" | bc)")"
  rss="$(grep -Eo 'Maximum resident set size[^0-9]*([0-9]+)|([0-9]+)[[:space:]]+maximum resident set size' "${log}" \
        | grep -Eo '[0-9]+' | head -1 || true)"
  cpu="$(grep -Eo '(User time \(seconds\): |[0-9.]+[[:space:]]+user)' -A0 "${log}" | grep -Eo '[0-9.]+' | head -1 || true)"

  # macOS reports RSS in bytes, GNU time in kilobytes.
  if [[ -n "${rss}" ]]; then
    if [[ "${rss}" -gt 10000000 ]]; then rss="$((rss / 1048576)) MB"; else rss="$((rss / 1024)) MB"; fi
  else
    rss="n/a"
  fi

  printf '| %-5s | %-5s | %8ss | %-9s | %-8s |\n' \
    "${n}" "${forks}" "${wall}" "${rss}" "${cpu:-n/a}s" >> "${WORK}/results.md"

  teardown
}

mkdir -p "${WORK}"
cat > "${WORK}/results.md" <<'EOF'
| Hosts | Forks | Wall time | Peak RSS | CPU time |
| --- | --- | --- | --- | --- |
EOF

for n in "${SIZES[@]}"; do
  [[ "${n}" =~ ^[0-9]+$ ]] || die "'${n}' is not a fleet size."
  run_size "${n}"
done

say "Results"
cat "${WORK}/results.md"
cat <<EOF

Recorded on: $(uname -srm), $(ansible --version | head -1)
Image: ${IMAGE}

These are control-plane numbers from local containers. Before quoting them
anywhere, read the "What these numbers are not" section of
docs/performance.md.
EOF
