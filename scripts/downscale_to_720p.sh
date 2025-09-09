#!/usr/bin/env bash
# downscale_to_720p.sh
# Usage: ./downscale_to_720p.sh /path/to/videos
# Requires: ffmpeg, ffprobe (and optional: VAAPI-capable AMD GPU + mesa-va-drivers)

set -euo pipefail

# Ensure Ctrl-C (SIGINT) or SIGTERM stops the whole script immediately.
# Without this, we temporarily disable errexit around ffmpeg and a SIGINT
# could cause ffmpeg to exit non‑zero while the script continues. This trap
# makes sure the script exits on those signals.
trap 'echo "Interrupted"; exit 130' INT TERM
DIR="${1:-.}"

# ---------- deps ----------
command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found. Install it first."; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "ffprobe not found. Install ffmpeg (includes ffprobe)."; exit 1; }

# ---------- VAAPI detect (AMD, headless) ----------
VA_DEVICE="/dev/dri/renderD128"
USE_VAAPI=0
if [[ -e "$VA_DEVICE" ]]; then
  # Quick, quiet probe: try to init VAAPI and encode 1 dummy frame to null
  if ffmpeg -hide_banner -v error -f lavfi -i color=s=16x16:d=0.1 \
      -init_hw_device vaapi=va:${VA_DEVICE} -filter_hw_device va \
      -frames:v 1 -c:v h264_vaapi -f null - >/dev/null 2>&1; then
    echo "VA-API available on ${VA_DEVICE} — will use GPU."
    USE_VAAPI=1
  else
    echo "VA-API probe failed — will use CPU (libx264)."
  fi
else
  echo "No ${VA_DEVICE} device — will use CPU (libx264)."
fi

# ---------- gather files ----------
shopt -s nullglob
mapfile -t FILES < <(find "$DIR" -type f \( \
  -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.m4v" -o -iname "*.avi" \
\) -print)

if (( ${#FILES[@]} == 0 )); then
  echo "No video files found in: $DIR"
  exit 0
fi

total_files=${#FILES[@]}
file_num=0
processed=0
skipped=0
errors=0
# start time for ETA calculations
start_time=$(date +%s)
# per-file durations (seconds) used to compute median ETA
durations=()
for f in "${FILES[@]}"; do
  file_num=$((file_num + 1))
  remaining=$((total_files - file_num))
  echo "----"
  # Estimate remaining time using the median seconds per completed file so far
  if [[ ${#durations[@]} -gt 0 ]]; then
    eta_sec=$(printf "%s\n" "${durations[@]}" | sort -n | awk -v r="$remaining" '
      { a[NR]=$1 }
      END {
        if (NR==0) { print 0; exit }
        if (NR%2==1) { median=a[(NR+1)/2] }
        else { median=(a[NR/2]+a[NR/2+1])/2 }
        printf "%d", median * r
      }')
    eta_formatted=$(printf "%02d:%02d:%02d" $((eta_sec/3600)) $((eta_sec%3600/60)) $((eta_sec%60)))
    median_sec=$(printf "%s\n" "${durations[@]}" | sort -n | awk '
      { a[NR]=$1 }
      END {
        if (NR==0) { print 0; exit }
        if (NR%2==1) { print a[(NR+1)/2] }
        else { printf "%.0f", (a[NR/2]+a[NR/2+1])/2 }
      }')
    echo "File $file_num of $total_files (remaining: $remaining) — ETA: ${eta_formatted} (median: ${median_sec}s/file)"
  else
    echo "File $file_num of $total_files (remaining: $remaining) — ETA: calculating..."
  fi
  echo "Checking: $f"

  # width x height of the first video stream
  dims=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -of csv=s=x:p=0 "$f" || true)

  if [[ -z "$dims" ]]; then
    echo "  No video stream found. Skipping."
  errors=$((errors+1))
    continue
  fi

  width=${dims%x*}
  height=${dims#*x}
  echo "  Detected: ${width}x${height}"

  # Get media duration (seconds) and print formatted HH:MM:SS before processing
  duration_raw=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null || true)
  if [[ -n "$duration_raw" ]]; then
    duration_sec=$(printf "%.0f" "$duration_raw")
  else
    # fallback: try the first video stream duration
    duration_raw=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "$f" 2>/dev/null || true)
    duration_sec=$(printf "%.0f" "${duration_raw:-0}")
  fi
  duration_fmt=$(printf "%02d:%02d:%02d" $((duration_sec/3600)) $((duration_sec%3600/60)) $((duration_sec%60)))
  echo "  Duration: ${duration_fmt} (${duration_sec}s)"

  # Skip if already ≤ 720p
  if (( width <= 1280 && height <= 720 )); then
    echo "  Already ≤ 720p. Skipping."
  skipped=$((skipped+1))
    continue
  fi

  # Build temp path that keeps the original extension (so muxer is chosen correctly)
  ext="${f##*.}"                  # extension (mp4/mkv/mov/...)
  base="${f%.*}"                  # filename without extension
  tmp="${base}.tmp-720p.$RANDOM.$RANDOM.$ext"

  # Subtitle handling: MP4/MOV need mov_text for compatibility; MKV etc. can copy
  subs_arg="-c:s copy"
  case "${ext,,}" in
    mp4|m4v|mov) subs_arg="-c:s mov_text" ;;
  esac

  echo "  Transcoding -> temp: $tmp"

  # per-file start time for duration reporting
  file_start=$(date +%s)

  # record original file size (bytes) for later comparison
  orig_size=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if command -v numfmt >/dev/null 2>&1; then
    orig_human=$(numfmt --to=iec --suffix=B "$orig_size")
  else
    orig_human="$orig_size bytes"
  fi

  # Run encoding for this file only; if it fails, clean up and continue to next file.
  # We temporarily disable `set -e` so a single ffmpeg failure doesn't stop the whole script.
  set +e
  if [[ "$USE_VAAPI" -eq 1 ]]; then
    # ---------- GPU path: AMD VAAPI (constant quality) ----------
    # Notes:
    # - scale_vaapi does hardware scaling; -qp ~22 is a good start (20–24 typical).
    # - If you prefer capped bitrate instead: replace '-qp 22' with
    #   '-b:v 3M -maxrate 3M -bufsize 6M'.
    ffmpeg -y -hide_banner -loglevel warning \
      -init_hw_device vaapi=va:${VA_DEVICE} -filter_hw_device va \
      -hwaccel vaapi -hwaccel_device ${VA_DEVICE} -hwaccel_output_format vaapi \
      -i "$f" \
      -map 0 \
      -vf "scale_vaapi=w=1280:h=720:force_original_aspect_ratio=decrease" \
      -c:v h264_vaapi -profile:v high -level 4.1 -qp 22 -g 240 -bf 2 \
      -c:a copy $subs_arg -movflags +faststart \
  "$tmp"
  else
    # ---------- CPU path: libx264 CRF ----------
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$f" \
      -map 0 \
      -c:v libx264 -crf 20 -preset medium \
      -vf "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease" \
      -pix_fmt yuv420p \
      -c:a copy $subs_arg -movflags +faststart \
      "$tmp"
  fi
  rc=$?
  # restore errexit
  set -e

  if [[ $rc -ne 0 ]]; then
    # If ffmpeg was terminated by a signal, its exit code will be >= 128.
    # In that case, we should exit the whole script so Ctrl-C works as expected.
  # Treat signal-based terminations (exit codes >=128) as hard exits,
  # but allow ffmpeg's 234 code to be handled as a recoverable error.
  if [[ $rc -ge 128 && $rc -ne 234 ]]; then
      echo "  Encoding terminated by signal (exit code $rc). Exiting."
      rm -f "$tmp" || true
      exit $rc
    fi
  echo "  Error: encoding failed (exit code $rc). Cleaning up temp and continuing."
    rm -f "$tmp" || true
  errors=$((errors+1))
    continue
  fi

  # Replace original if the temp file exists (encode succeeded)
  if [[ -f "$tmp" ]]; then
    echo "  Replacing original with 720p version"
  if mv -f "$tmp" "$f"; then
      # new size after successful replace
      new_size=$(stat -c%s "$f" 2>/dev/null || echo 0)
      if command -v numfmt >/dev/null 2>&1; then
        new_human=$(numfmt --to=iec --suffix=B "$new_size")
      else
        new_human="$new_size bytes"
      fi
      # delta and percent (percent shown as one decimal, "N/A" if orig was zero)
      delta=$((new_size - orig_size))
      if [[ $orig_size -gt 0 ]]; then
        pct=$(awk -v o="$orig_size" -v n="$new_size" 'BEGIN { printf "%.1f", (n-o)/o*100 }')
      else
        pct="N/A"
      fi
  # per-file duration
  file_end=$(date +%s)
  file_dur=$((file_end - file_start))
  file_dur_fmt=$(printf "%02d:%02d:%02d" $((file_dur/3600)) $((file_dur%3600/60)) $((file_dur%60)))
  echo "  Done. Size: ${orig_human} -> ${new_human} (delta: ${delta} bytes, ${pct}% ) Duration: ${file_dur_fmt}"
  processed=$((processed+1))
  # record duration for median-based ETA
  durations+=("$file_dur")
    else
      echo "  Warning: failed to replace original file. Leaving temp file: $tmp" 
      rm -f "$tmp" || true
      errors=$((errors+1))
    fi
  else
    echo "  Error: temp file not created. Skipping replace."
    errors=$((errors+1))
  fi
done

echo ""
echo "Summary:" 
echo "  Processed (downscaled & replaced): ${processed}"
echo "  Skipped (already ≤ 720p): ${skipped}"
echo "  Errors: ${errors}"
echo "  Total checked: ${total_files}"
total_end=$(date +%s)
total_elapsed=$((total_end - start_time))
total_fmt=$(printf "%02d:%02d:%02d" $((total_elapsed/3600)) $((total_elapsed%3600/60)) $((total_elapsed%60)))
echo "  Total elapsed: ${total_fmt}"
echo "All set ✅"

