#!/usr/bin/env bash
# summary_table.sh - show name, size (human readable), and file count for a directory
# Usage: ./scripts/summary_table.sh /path/to/dir

set -euo pipefail

DIR="${1:-.}"
if [[ ! -d "$DIR" ]]; then
  echo "Error: '$DIR' is not a directory"
  exit 1
fi

# Header
printf "%-5s %-60s %10s %10s\n" "Type" "Name" "Size" "#Files"
printf "%s\n" "$(printf '%0.s-' {1..95})"

# Iterate entries (non-recursive), sorted, handling whitespace
while IFS= read -r -d '' entry; do
  name=$(basename "$entry")
  if [[ -d "$entry" ]]; then
    type="DIR"
    # human-readable size for directory
    if du --version >/dev/null 2>&1; then
      size=$(du -sh --apparent-size -- "$entry" 2>/dev/null | cut -f1)
    else
      size="$(du -sh "$entry" 2>/dev/null | cut -f1)"
    fi
    # count files inside (regular files only)
    filecount=$(find "$entry" -type f 2>/dev/null | wc -l | tr -d '[:space:]')
  else
    type="FILE"
    # size for file in human readable
    if command -v numfmt >/dev/null 2>&1; then
      bytes=$(stat -c%s -- "$entry" 2>/dev/null || echo 0)
      size=$(numfmt --to=iec --suffix=B "$bytes")
    else
      size="$(stat -c%s -- "$entry" 2>/dev/null || echo 0)B"
    fi
    filecount="-"
  fi

  printf "%-5s %-60s %10s %10s\n" "$type" "$name" "$size" "$filecount"

done < <(find "$DIR" -mindepth 1 -maxdepth 1 -print0 | sort -z)
