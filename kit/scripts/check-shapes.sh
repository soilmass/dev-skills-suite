#!/usr/bin/env bash
# Checks every kit/shapes/<name>.schema.json is backward compatible with
# its copy at the last tag, using json-schema-compat-check's own script
# (SDS-K-023). Exit 1 on any breaking change.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
tag=$(git describe --tags --abbrev=0)
status=0
old=$(mktemp)
trap 'rm -f "$old"' EXIT
for f in kit/shapes/*.schema.json; do
  if ! git show "$tag:$f" > "$old" 2>/dev/null; then
    echo "new shape $f (no copy at $tag)"
    continue
  fi
  out=$(cd skills/json-schema-compat-check && python3 scripts/diff_json_schema.py "$old" "../../$f")
  errors=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for r in d['runs'][0]['results'] if r['level']=='error'))")
  echo "$f vs $tag: $errors breaking change(s)"
  [ "$errors" -eq 0 ] || status=1
done
exit $status
