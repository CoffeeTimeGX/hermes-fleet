# The pixel lot's sounds

These files are rendered with [Lumina SFX](https://github.com/LuminaBench/lumina-sfx)
v1.5.0 (commit `dbf1a1487fbbaa26e7335f5d3e2943219a0612c3`), the sound library the VPSs also
use, then saved as small mono MP3 files. `home/studio/pixel.html` plays them; `fleet
studio` serves them as `/sounds/<file>`.

They are **not** under this repository's licence. The Lumina sound designs are under the
*Lumina Open Game Audio License 1.0* (see Lumina's
[LICENSE](https://github.com/LuminaBench/lumina-sfx/blob/main/LICENSE)): they may ship in an
app that needs them at runtime, with no credit required, but must not be shared as a
sound pack, a sample library or a training dataset. The recordings they are built from are
CC0 (public domain).

| File | Lumina sound | Plays when | Recordings |
| --- | --- | --- | --- |
| `lot-slate.mp3` | `book-cover-shut` | a job starts | [buchklapp](https://freesound.org/people/opriema/sounds/749741/) by opriema (CC0-1.0) |
| `lot-done.mp3` | `timer-complete-chime` | a video is done | made by Lumina (no recording) |
| `lot-fail.mp3` | `console-error-buzz` | a job failed | made by Lumina (no recording) |
| `lot-hold.mp3` | `amber-guidance-console-loses-power` | a VPS reached its usage limit | made by Lumina (no recording) |
| `lot-pitch.mp3` | `quest-accepted-chime` | the zeppelin brings a new pitch | made by Lumina (no recording) |
| `lot-bird-1.mp3` | `sparrow-chirps` | birds by day | [House sparrow.wav](https://freesound.org/people/straget/sounds/404663/) by straget (CC0-1.0) |
| `lot-bird-2.mp3` | `robin-song` | birds by day | [Robin singing](https://freesound.org/people/naturenotesuk/sounds/418425/) by naturenotesuk (CC0-1.0) |
| `lot-bird-3.mp3` | `house-sparrow-contact-call` | birds by day | [House sparrow.wav](https://freesound.org/people/straget/sounds/404663/) by straget (CC0-1.0) |
| `lot-cricket.mp3` | `crickets-beneath-a-half-open-window-loop` | crickets on warm nights | [Night crickets](https://freesound.org/people/Vrymaa/sounds/734642/) by Vrymaa (CC0-1.0); [Rustling Leaves.wav](https://freesound.org/people/FunWithSound/sounds/406099/) by FunWithSound (CC0-1.0) |
| `lot-town.mp3` | `local-streetcar-far-side-of-street-loop` | the town, as busy as the roads | [Train Station](https://freesound.org/people/Sam-Mortley/sounds/774271/) by Sam-Mortley (CC0-1.0); [Squeaking tram departing.wav](https://freesound.org/people/dersinnsspace/sounds/417657/) by dersinnsspace (CC0-1.0) |
| `lot-rain.mp3` | `light-rain-loop` | rain | [08-24-rain-car-windscreen](https://freesound.org/people/DanielHren/sounds/750219/) by DanielHren (CC0-1.0) |
| `lot-storm.mp3` | `heavy-storm-rain-loop` | heavy rain, on top of the rain | [08-24-rain-car-windscreen](https://freesound.org/people/DanielHren/sounds/750219/) by DanielHren (CC0-1.0) |
| `lot-wind.mp3` | `slow-wind-gusts-loop` | wind, in snow, fog and cloud | made by Lumina (no recording) |

## Make them again

With a clone of Lumina SFX at that commit and Node.js 22.20 or newer:

```bash
bash home/studio/sounds/render.sh /path/to/lumina-sfx
```

It renders each sound to WAV with Lumina's `scripts/remix.mjs` (in Node's permission
sandbox: it may read the clone and write only its output folder), then encodes the MP3
files here with `ffmpeg`. To change a sound, change its line in `render.sh`, render, and
listen on the pixel lot.
