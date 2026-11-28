#!/usr/bin/env bash
# Render the pixel lot's sounds with Lumina SFX, then save them here as small MP3 files.
#   bash home/studio/sounds/render.sh /path/to/lumina-sfx
# Needs Node.js 22.20+ and ffmpeg (with libmp3lame). See CREDITS.md.
set -euo pipefail

LUMINA="$(cd "${1:?usage: render.sh /path/to/lumina-sfx}" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$LUMINA/scripts/remix.mjs" ]] || { echo "not a Lumina SFX clone: $LUMINA" >&2; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/wav" "$WORK/tmp"

# file          Lumina sound                               MP3 bit rate
while read -r name sound rate; do
  (cd "$LUMINA" && TMPDIR="$WORK/tmp" node --permission --allow-fs-read="$LUMINA" --allow-fs-read="$WORK" \
     --allow-fs-write="$WORK/wav" --allow-fs-write="$WORK/tmp" \
     scripts/remix.mjs "$sound" --id "lot-$name" --format wav --dest "$WORK/wav" </dev/null >/dev/null)
  ffmpeg -nostdin -hide_banner -v error -y -i "$WORK/wav/lot-$name.wav" -map_metadata -1 -ac 1 \
    -codec:a libmp3lame -b:a "$rate" -write_xing 1 "$HERE/lot-$name.mp3"
  echo "lot-$name.mp3  <- $sound"
done <<'LIST'
slate     book-cover-shut                            96k
done      timer-complete-chime                       96k
fail      console-error-buzz                         96k
hold      amber-guidance-console-loses-power         96k
pitch     quest-accepted-chime                       96k
bird-1    sparrow-chirps                             96k
bird-2    robin-song                                 96k
bird-3    house-sparrow-contact-call                 96k
cricket   crickets-beneath-a-half-open-window-loop   64k
town      local-streetcar-far-side-of-street-loop    64k
rain      light-rain-loop                            64k
storm     heavy-storm-rain-loop                      64k
wind      slow-wind-gusts-loop                       64k
LIST
