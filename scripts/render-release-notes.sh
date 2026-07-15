#!/usr/bin/env bash

set -euo pipefail

TAG_INPUT="${1:-${GITHUB_REF_NAME:-}}"
if [[ -z "${TAG_INPUT}" ]]; then
  echo "Usage: scripts/render-release-notes.sh <tag>" >&2
  exit 2
fi

TAG="${TAG_INPUT#refs/tags/}"
VERSION="${TAG#claude-otel-plugin--v}"

mapfile -t TAGS < <(git tag --list 'claude-otel-plugin--v*' --sort=version:refname)

PREVIOUS_TAG=""
for ((i=0; i<${#TAGS[@]}; i++)); do
  if [[ "${TAGS[$i]}" == "${TAG}" ]]; then
    if (( i > 0 )); then
      PREVIOUS_TAG="${TAGS[$((i-1))]}"
    fi
    break
  fi
done

if [[ -n "${PREVIOUS_TAG}" ]]; then
  RANGE="${PREVIOUS_TAG}..${TAG}"
else
  RANGE="${TAG}"
fi

mapfile -t COMMITS < <(git log --format='%s' --no-merges "${RANGE}" | sed '/^Release [0-9][0-9.]*$/d')
mapfile -t CHANGED_FILES < <(git diff --name-only ${PREVIOUS_TAG:+${PREVIOUS_TAG}} ${PREVIOUS_TAG:+${TAG}})

if [[ -z "${PREVIOUS_TAG}" ]]; then
  mapfile -t CHANGED_FILES < <(git show --pretty='' --name-only "${TAG}")
fi

declare -a BULLETS=()
seen_bullet() {
  local item="$1"
  local existing
  for existing in "${BULLETS[@]:-}"; do
    [[ "${existing}" == "${item}" ]] && return 0
  done
  return 1
}

add_bullet() {
  local item="$1"
  [[ -n "${item}" ]] || return 0
  if ! seen_bullet "${item}"; then
    BULLETS+=("${item}")
  fi
}

for subject in "${COMMITS[@]:-}"; do
  [[ -n "${subject}" ]] || continue
  add_bullet "${subject}"
done

has_file() {
  local pattern="$1"
  local file
  for file in "${CHANGED_FILES[@]:-}"; do
    [[ "${file}" == ${pattern} ]] && return 0
  done
  return 1
}

if has_file "scripts/install.sh" || has_file "scripts/install-release.sh" || has_file "scripts/install-remote.sh"; then
  add_bullet "Improved local, remote, and release installers with install-time configuration options."
fi

if git diff --quiet ${PREVIOUS_TAG:+${PREVIOUS_TAG}} ${PREVIOUS_TAG:+${TAG}} -- hooks/claude_otel_hook.py docs/metrics.md test/test_claude_otel_hook.py 2>/dev/null; then
  :
elif git diff ${PREVIOUS_TAG:+${PREVIOUS_TAG}} ${PREVIOUS_TAG:+${TAG}} -- hooks/claude_otel_hook.py docs/metrics.md test/test_claude_otel_hook.py | grep -qE '(^[-+].*outcome|^[-+].*status)'; then
  add_bullet "Renamed the agent operation metric label from `outcome` to `status`."
fi

if has_file "scripts/package-release.sh"; then
  add_bullet "Updated release packaging so published assets include the installer entry points required by customers."
fi

if has_file ".claude-plugin/plugin.json"; then
  add_bullet "Expanded plugin install-time configuration options, including timeout and user ID support."
fi

if has_file "README.md" || has_file "docs/install.md" || has_file "docs/development.md"; then
  add_bullet "Refreshed English installation and release documentation for customer-facing usage."
fi

if has_file ".github/workflows/release.yml"; then
  add_bullet "Refined GitHub Release publishing so titles and notes are cleaner and easier to scan."
fi

if has_file "hooks/claude_otel_hook.py" || has_file "hooks/hooks.json" || has_file "hooks/run_hook.sh"; then
  add_bullet "Updated hook runtime packaging and plugin metadata emitted by the Claude OTEL runtime."
fi

if has_file "test/test_claude_otel_hook.py"; then
  add_bullet "Kept automated validation in place for installer and hook behavior."
fi

if [[ "${#BULLETS[@]}" -eq 0 ]]; then
  BULLETS+=("Internal maintenance and packaging updates.")
fi

cat <<EOF
## Summary

This release packages the latest Claude OpenTelemetry plugin updates and customer-facing installer assets.

## Changes
EOF

for item in "${BULLETS[@]}"; do
  printf -- '- %s\n' "${item}"
done

cat <<EOF

## Validation

- \`python3 -m unittest discover -s test\`
- \`claude plugin validate .\`

## Assets

- \`install-release.sh\`: release installer with install-time configuration options
- \`claude-otel-plugin.tar.gz\`: canonical release package
- \`claude-otel-plugin-${VERSION}.tar.gz\`: versioned release package
- \`claude-otel-plugin.tar.gz.sha256\`: checksum file for the canonical package
EOF
