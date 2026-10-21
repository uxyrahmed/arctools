#!/usr/bin/env bash
# Zip one toolbox folder so it can be unzipped and added straight to ArcGIS Pro.
#
#   scripts/build_toolbox_zip.sh <toolbox folder name> <output zip path>
#
# The zip holds the folder itself (README, .pyt and helper modules), without
# tests or Python caches.
set -euo pipefail

name="$1"
out="$2"
root="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$root/toolboxes/$name" ]; then
  echo "No toolbox folder toolboxes/$name" >&2
  exit 1
fi

case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
mkdir -p "$(dirname "$out")"
rm -f "$out"

cd "$root/toolboxes"
zip -r -q -X "$out" "$name" \
  -x "$name/tests/*" "*/__pycache__/*" "*.pyc" "*.pyo" "*.lock" "*/.DS_Store"
echo "Built $out"
