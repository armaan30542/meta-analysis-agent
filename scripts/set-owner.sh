#!/usr/bin/env bash
# Replace the GitHub owner placeholder everywhere, e.g.:  ./scripts/set-owner.sh armaanpunjani
set -euo pipefail
[ $# -eq 1 ] || { echo "usage: $0 <github-username-or-org>"; exit 1; }
cd "$(dirname "$0")/.."
grep -rl "YOUR-GITHUB-USERNAME" --exclude-dir=.git --exclude=set-owner.sh . | while read -r f; do
  sed -i.bak "s/YOUR-GITHUB-USERNAME/$1/g" "$f" && rm -f "$f.bak"
  echo "updated $f"
done
