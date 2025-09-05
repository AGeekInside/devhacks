#!/usr/bin/env bash
# downscale_to_720p.sh
# Usage: ./downscale_to_720p.sh /path/to/videos
# Requires: ffmpeg, ffprobe (and optional: VAAPI-capable AMD GPU + mesa-va-drivers)

set -euo pipefail
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

for f in "${FILES[@]}"; do
  echo "----"
  echo "Checking: $f"

  # width x height of the first video stream
  dims=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -of csv=s=x:p=0 "$f" || true)

  if [[ -z "$dims" ]]; then
    echo "  No video stream found. Skipping."
    continue
  fi

  width=${dims%x*}
  height=${dims#*x}
  echo "  Detected: ${width}x${height}"

  # Skip if already ≤ 720p
  if (( width <= 1280 && height <= 720 )); then
    echo "  Already ≤ 720p. Skipping."
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

  # Replace original if the temp file exists (encode succeeded)
  if [[ -f "$tmp" ]]; then
    echo "  Replacing original with 720p version"
    mv -f "$tmp" "$f"
    echo "  Done."
  else
    echo "  Error: temp file not created. Skipping replace."
  fi
done

echo "All set ✅"

