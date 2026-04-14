#!/bin/bash
# /usr/local/bin/jf_delete_unmonitor.sh

SONARR_API="http://localhost:8989/api/v3"
RADARR_API="http://localhost:7878/api/v3"
WHISPARR_API="http://localhost:6969/api/v3"   # adjust port
SONARR_KEY="27fd6d53bb6b4181828aea0dd5297047"
RADARR_KEY="0a2710c1184648b49706f7e16ef47ee4"
WHISPARR_KEY="YOUR_WHISPARR_API_KEY"

TITLE="$1"

# Helper: unmonitor series in Sonarr
SONARR_ID=$(curl -s "$SONARR_API/series" -H "X-Api-Key: $SONARR_KEY" \
  | jq ".[] | select(.title==\"$TITLE\") | .id")

if [ -n "$SONARR_ID" ]; then
  curl -s -X PUT "$SONARR_API/series/$SONARR_ID" \
    -H "X-Api-Key: $SONARR_KEY" -H "Content-Type: application/json" \
    -d '{"monitored": false}' >/dev/null
fi

# Helper: unmonitor movies in Radarr
RADARR_ID=$(curl -s "$RADARR_API/movie" -H "X-Api-Key: $RADARR_KEY" \
  | jq ".[] | select(.title==\"$TITLE\") | .id")

if [ -n "$RADARR_ID" ]; then
  curl -s -X PUT "$RADARR_API/movie/$RADARR_ID" \
    -H "X-Api-Key: $RADARR_KEY" -H "Content-Type: application/json" \
    -d '{"monitored": false}' >/dev/null
fi

# Helper: unmonitor series in Whisparr
WHISPARR_ID=$(curl -s "$WHISPARR_API/series" -H "X-Api-Key: $WHISPARR_KEY" \
  | jq ".[] | select(.title==\"$TITLE\") | .id")

if [ -n "$WHISPARR_ID" ]; then
  curl -s -X PUT "$WHISPARR_API/series/$WHISPARR_ID" \
    -H "X-Api-Key: $WHISPARR_KEY" -H "Content-Type: application/json" \
    -d '{"monitored": false}' >/dev/null
fi

