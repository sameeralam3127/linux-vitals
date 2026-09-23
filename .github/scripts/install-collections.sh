#!/usr/bin/env bash
# Install the collections CI needs, retrying transient Galaxy failures.
#
# galaxy.ansible.com intermittently answers 5xx (a 504 on a dependency lookup
# has turned an otherwise-green run red before). A Galaxy hiccup is not a
# defect in this repository, so it should not fail the build on the first try.
set -euo pipefail

attempts=3
delay=15

for attempt in $(seq 1 "$attempts"); do
  if ansible-galaxy collection install -r requirements.yml &&
     ansible-galaxy collection install -r molecule/collections.yml; then
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
