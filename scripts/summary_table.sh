#!/usr/bin/env bash
# summary_table.sh - show name, size (human readable), and file count for a directory
# Usage: ./scripts/summary_table.sh /path/to/dir

set -euo pipefail

# Parse flags: -S/--size (sort by size), -F/--files (sort by number of files), default: name
sort_mode="name"
usage() {
  cat <<EOF
Usage: $0 [-S|--size] [ -F|--files ] [DIR]
  -S, --size    sort by size (largest first)
  -F, --files   sort by number of files inside directories (largest first)
  DIR           directory to summarize (default: .)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -S|--size) sort_mode="size"; shift ;;
    -F|--files) sort_mode="files"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "Unknown option: $1"; usage; exit 2 ;;
    *) DIR="$1"; shift; break ;;
  esac
done

DIR="${DIR:-.}"
if [[ ! -d "$DIR" ]]; then
  echo "Error: '$DIR' is not a directory"
  exit 1
fi

printf "%s\n" "$(printf '%0.s-' {1..95})"
# Build a temporary TSV with fields: Type<TAB>Name<TAB>SizeBytes<TAB>SizeHuman<TAB>FileCount
tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

while IFS= read -r -d '' entry; do
  name=$(basename "$entry")
  if [[ -d "$entry" ]]; then
    type="DIR"
    # size in bytes for sorting; prefer du -sb, fallback to du -s --block-size=1
    if du -sb -- "$entry" >/dev/null 2>&1; then
      size_bytes=$(du -sb -- "$entry" 2>/dev/null | cut -f1)
    else
      size_bytes=$(du -s --block-size=1 -- "$entry" 2>/dev/null | cut -f1)
    fi
    # human readable size
    if command -v numfmt >/dev/null 2>&1; then
      size_human=$(numfmt --to=iec --suffix=B "$size_bytes")
    else
      size_human="${size_bytes}B"
    fi
    # count files inside (regular files only)
    filecount=$(find "$entry" -type f 2>/dev/null | wc -l | tr -d '[:space:]')
  else
    type="FILE"
    size_bytes=$(stat -c%s -- "$entry" 2>/dev/null || echo 0)
    if command -v numfmt >/dev/null 2>&1; then
      size_human=$(numfmt --to=iec --suffix=B "$size_bytes")
    else
      size_human="${size_bytes}B"
    fi
    filecount="-"
  fi
  # Escape tabs/newlines in name (replace with space) to keep TSV simple
  safe_name=$(printf '%s' "$name" | tr '\t\n' '  ')
  printf '%s\t%s\t%s\t%s\t%s\n' "$type" "$safe_name" "$size_bytes" "$size_human" "$filecount" >> "$tmpfile"
done < <(find "$DIR" -mindepth 1 -maxdepth 1 -print0 | sort -z)

# Choose sort command based on mode
case "$sort_mode" in
  size) sort_cmd="sort -t$'\t' -k3,3nr" ;;
  files) sort_cmd="sort -t$'\t' -k5,5nr" ;;
  *) sort_cmd="sort -t$'\t' -k2,2f" ;;
esac

# Header
printf "%-5s %-60s %10s %10s\n" "Type" "Name" "Size" "#Files"
printf "%s\n" "$(printf '%0.s-' {1..95})"

# Output sorted table
eval "$sort_cmd" "$tmpfile" | while IFS=$'\t' read -r type name size_bytes size_human filecount; do
  printf "%-5s %-60s %10s %10s\n" "$type" "$name" "$size_human" "$filecount"
done
