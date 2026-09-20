#!/usr/bin/env bash
#
# Regenerate the dashboard screenshots in docs/images/ from a live demo run.
#
#   ./screenshots.sh
#
# Screenshots age badly -- that is the stated reason the roadmap puts #6 last.
# This script is the mitigation: the images in the README are reproducible from
# the current templates in one command, so refreshing them after a dashboard
# change is not a manual chore anyone has to remember how to do.
#
# Requires a headless Chrome. Runs the full demo cycle, so it will start and
# reconfigure the demo containers.

set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${DEMO_DIR}/.." && pwd)"
OUT="${REPO_DIR}/docs/images"
REPORT="${DEMO_DIR}/reports/linux_vitals_report.html"
WORK="$(mktemp -d)"
MAINT_ID="$(date +%Y-%m-%d)-patch-window"

trap 'rm -rf "${WORK}"' EXIT

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

find_chrome() {
  local c
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "$(command -v google-chrome-stable || true)" \
    "$(command -v chromium || true)"; do
    [ -x "${c}" ] && { echo "${c}"; return 0; }
  done
  return 1
}

CHROME="$(find_chrome)" || die "no headless Chrome found."

shoot() {
  local src="$1" out="$2" height="$3"
  "${CHROME}" --headless --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=1440,"${height}" \
    --screenshot="${out}" "file://${src}" 2>/dev/null
  # Halve the retina capture back to a sensible width for a README.
  if command -v sips >/dev/null 2>&1; then
    sips -Z 1600 "${out}" >/dev/null 2>&1
  elif command -v convert >/dev/null 2>&1; then
    convert "${out}" -resize 1600x1600\> "${out}"
  fi
}

# Expand the first host's detail row. Only the is-hidden class is removed, so
# the content is exactly what clicking the row would reveal -- nothing is
# added, styled differently, or faked.
expand_first_row() {
  local src="$1" dest="$2"
  python3 - "${src}" "${dest}" <<'PY'
import pathlib, sys
src, dest = sys.argv[1], sys.argv[2]
html = pathlib.Path(src).read_text()
pathlib.Path(dest).write_text(
    html.replace('<tr class="detail-row is-hidden"', '<tr class="detail-row"', 1)
)
PY
}

mkdir -p "${OUT}"

say "Capturing the healthy / broken / healed cycle for the animation"
"${DEMO_DIR}/run.sh" up
mkdir -p "${WORK}/frames"
# Vacuum the journals first: otherwise the "healthy" frame carries log errors
# left over from the previous cycle and the three frames do not tell a story.
for c in ubuntu rocky fedora; do
  docker exec "linux-vitals-demo-${c}" journalctl --rotate --vacuum-time=1s >/dev/null 2>&1 || true
done
"${DEMO_DIR}/run.sh" repair
"${DEMO_DIR}/run.sh" scan
shoot "${REPORT}" "${WORK}/frames/1-healthy.png" 600
"${DEMO_DIR}/run.sh" break
"${DEMO_DIR}/run.sh" scan
shoot "${REPORT}" "${WORK}/frames/2-broken.png" 600
"${DEMO_DIR}/run.sh" heal
shoot "${REPORT}" "${WORK}/frames/3-healed.png" 600

if command -v ffmpeg >/dev/null 2>&1; then
  say "Assembling docs/images/dashboard-cycle.gif"
  # 2.2s per frame: long enough to read a column, short enough that the loop
  # does not feel stalled. 128 colours keeps a dark UI clean under ~150 KB.
  ffmpeg -y -loglevel error -framerate 1/2.2 \
    -pattern_type glob -i "${WORK}/frames/*.png" \
    -vf "scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
    -loop 0 "${OUT}/dashboard-cycle.gif"
else
  say "ffmpeg not found -- skipping the animation, stills only"
fi

say "Capturing the fleet overview and an expanded host"
cp "${WORK}/frames/3-healed.png" "${OUT}/dashboard-overview.png"
expand_first_row "${REPORT}" "${WORK}/expanded.html"
shoot "${WORK}/expanded.html" "${OUT}/dashboard-host-detail.png" 860

say "Building a baseline/postcheck comparison"
export ANSIBLE_CONFIG="${REPO_DIR}/ansible.cfg" ANSIBLE_NO_TARGET_SYSLOG=True
"${DEMO_DIR}/run.sh" repair
ansible-playbook -i "${DEMO_DIR}/inventory.ini" "${REPO_DIR}/playbooks/baseline.yml" \
  -e linux_vitals_maintenance_id="${MAINT_ID}"
"${DEMO_DIR}/run.sh" break
ansible-playbook -i "${DEMO_DIR}/inventory.ini" "${REPO_DIR}/playbooks/postcheck.yml" \
  -e linux_vitals_maintenance_id="${MAINT_ID}"

say "Capturing the before/after comparison"
expand_first_row "${REPORT}" "${WORK}/expanded-cmp.html"
shoot "${WORK}/expanded-cmp.html" "${OUT}/dashboard-comparison.png" 900

say "Done"
ls -la "${OUT}"
cat <<EOF

The demo containers are still running. Remove them with:
  ${DEMO_DIR}/run.sh clean
EOF
