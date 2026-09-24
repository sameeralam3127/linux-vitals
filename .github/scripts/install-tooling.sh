#!/usr/bin/env bash
# Install the Python dev tooling for one ansible-core target.
#
#   latest  requirements-dev.txt as written: the newest core this collection
#           is developed against, kept current by Dependabot.
#   floor   the same tooling, with ansible-core taken from
#           .github/constraints/ansible-core-floor.txt -- the minimum declared
#           in meta/runtime.yml. requirements-dev.txt's own ansible-core line
#           is dropped rather than edited: a constraints file can narrow a
#           requirement but not contradict it, and a widened pin would be
#           raised straight back by Dependabot.
#
# Usable locally too, inside a virtualenv on a Python the floor supports:
#   ./.github/scripts/install-tooling.sh floor
set -euo pipefail

target="${1:-latest}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
floor_constraints="$repo_root/.github/constraints/ansible-core-floor.txt"

if [[ "$target" != "latest" && "$target" != "floor" ]]; then
  echo "usage: $0 [latest|floor]" >&2
  exit 2
fi

python -m pip install --upgrade pip

case "$target" in
  latest)
    python -m pip install -r "$repo_root/requirements-dev.txt"
    ;;
  floor)
    requirements="$(mktemp)"
    trap 'rm -f "$requirements"' EXIT
    grep -v '^ansible-core' "$repo_root/requirements-dev.txt" > "$requirements"
    python -m pip install -r "$requirements" ansible-core -c "$floor_constraints"
    ;;
esac

installed="$(python -c 'from ansible.release import __version__; print(__version__)')"
echo "ansible-core ${installed} installed for target '${target}'."

# A floor job that quietly resolved some other core would report the floor as
# tested when it was not. Refuse to continue rather than pass.
if [[ "$target" == "floor" ]]; then
  floor="$(sed -n 's/^ansible-core>=\([0-9]*\.[0-9]*\).*/\1/p' "$floor_constraints")"
  if [[ -z "$floor" || "$installed" != "$floor".* ]]; then
    echo "::error::Expected ansible-core ${floor:-<unparseable>}.x for the floor job, got ${installed}."
    exit 1
  fi
fi
