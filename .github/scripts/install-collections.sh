#!/usr/bin/env bash
# Install the collections CI needs, retrying transient Galaxy failures.
#
# galaxy.ansible.com intermittently answers 5xx (a 504 on a dependency lookup
# has turned an otherwise-green run red before). A Galaxy hiccup is not a
# defect in this repository, so it should not fail the build on the first try.
#
# Takes the same target as install-tooling.sh. `floor` installs the newest
# collection majors that still support the ansible-core floor instead -- see
# .github/constraints/collections-floor.yml.
set -euo pipefail

case "${1:-latest}" in
  latest) files=(requirements.yml molecule/collections.yml) ;;
  floor) files=(.github/constraints/collections-floor.yml) ;;
  *)
    echo "usage: $0 [latest|floor]" >&2
    exit 2
    ;;
esac

install_all() {
  local file
  for file in "${files[@]}"; do
    ansible-galaxy collection install -r "$file" || return 1
  done
}

attempts=3
delay=15

for attempt in $(seq 1 "$attempts"); do
  if install_all; then
    exit 0
  fi

  if [[ "$attempt" -lt "$attempts" ]]; then
    echo "::warning::Galaxy collection install failed (attempt ${attempt}/${attempts}); retrying in ${delay}s."
    sleep "$delay"
    delay=$((delay * 2))
  fi
done

echo "::error::Galaxy collection install failed after ${attempts} attempts."
exit 1
