---
name: pipedal-lcd
description: Work on the PiPedal stage LCD (lcd.py + pipedal_stage.py) running on a Raspberry Pi 5 — changing the display layout, effect-type prefixes/colours, label modes, adding indicators (e.g. xruns), or rendering test PNGs offscreen or from the live Pi. Use for any change or test of this project.
---

# PiPedal stage LCD

## What it is
A pygame display for a Raspberry Pi 5 with a DSI LCD (800x480). It runs on KMSDRM with no desktop.
- **Top:** the current preset name, a fixed `BNMachine.ttf` font at size 110. The user writes names that fit, so don't auto-shrink them. An orange dot top-left = preset modified (unsaved). An orange `OFFLINE` top-right = websocket down.
- **Bottom:** 3 effect slots, filled left to right in signal-chain order, max 3. Unused slots are black.
- **Sides:** vertical peak meters in the area above the slots (the slots keep the full width), input on the left and output on the right (mono; output = max(L,R)). Scale is -60..0 dBFS in green/yellow/red zones (boundaries at -12 and -3), with a peak-hold line and a clip light on top. Config `NICE` (applied in main() before threads start), `VU_METERS` (False = no meters and no server subscription), `METER_*`, `PEAK_HOLD_S`, `CLIP_HOLD_S`, `FPS`.

## Files (project root)
- `lcd.py` — the display. All config sits at the top:
  - `EFFECT_TYPES`: prefix → RGB
  - `LABEL_MODE`, `NAME_FONT_SIZE`, `NUM_SLOTS`, `DIM_BG`, `DIM_FG`
  - `display_key()`: turns the state into what gets drawn. It redraws only when the result changes.
  - `draw(screen, key, vin, vout)`: renders to any pygame surface; the meter views are optional and default to idle. No `flip()` anywhere. The main loop renders `draw_static()` into a cached background only when the key changes and pushes the whole screen with `pygame.display.update()`. Meter-only frames (`FPS`, 30) restore just the `meter_rects()` areas from the background, redraw the meters and call `display.update(meter_rects)`. Nothing is pushed when nothing changed.
  - `Meter`: `feed()` is called from the websocket thread with linear peaks, `tick()` once per frame, `view()` returns `(level_dB, peak_dB, clip)`.
- `pipedal_stage.py` — websocket client module (`PiPedalClient`, `StageState`, `Effect`). It connects to `ws://<host>:<port>/pipedal`, the same websocket the PiPedal web UI uses. Only read-only requests are used: `hello`, `currentPedalboard`, `getPresets`, and `addVuSubscription` when the optional `on_vu` callback is given. VU protocol (verified live): `addVuSubscription(instanceId)` with `VU_INPUT_ID=-2` / `VU_OUTPUT_ID=-3`; the server pushes `onVuUpdate` `{instanceId, inputMaxValueL/R, outputMaxValueL/R, isStereoInput/Output, ...}` (linear peaks), about 18–30/s each. Every update must be acked, or the server stops sending (the generic `replyTo` ack handles this). It also listens for notifications. `lcd.py` imports it, so leave it untouched unless asked; it also works standalone with `--console` or `--json`.
- `lcd_old.py` — the original version, which polled the `.bank` file. Kept as a backup.
- `BNMachine.ttf` — lives only on the Pi, next to `lcd.py`. The code loads it relative to the script's directory and falls back to pygame's default font.

## Effect slot rules
- An effect gets a slot only if its **plugin caption** (the `title` set in the PiPedal UI) starts with an UPPERCASE prefix from `EFFECT_TYPES`, followed by a space, e.g. `OD blues driver`. Matching is case-sensitive, so `ODYSSEY` and `od x` don't match.
- Amp, cab, reverb and anything else without a prefix is ignored.
- Enabled = vivid colour, with black or white text picked by luminance. Bypassed = colour × `DIM_BG` background with colour × `DIM_FG` text.
- Prefixes and colours: OD yellow, CHO violet, DLY blue, TRM teal, PHA orange, FLA pink, WAH bronze, CMP silver, BST red, FUZ green.
- `--label` modes, shown for `OD Klon Clone`:

  | Mode | Slot shows |
  |---|---|
  | `type` | `OD` |
  | `word` (default) | `Klon` |
  | `full` | `OD Klon Clone` |

## Environment
- Pi address: `192.168.1.248`, port 80. On the Pi itself, `lcd.py` defaults to `127.0.0.1:80`.
- On the Pi it runs under the system Python, with `python3-pygame` and `python3-websockets` from apt. A `ModuleNotFoundError` usually means it's being run with a different interpreter or venv.
- The user handles service/autostart setup; don't touch it.

## Working with this user
- **Ask clarifying questions first and wait for ALL answers** before writing code or running anything.
- **Never run `lcd.py` on the dev machine.** Its KMSDRM output is meant for the Pi.
- **Ask before any network call to the Pi**, even read-only ones.
- The user can't see images Claude reads. Give them the PNG path, or an `! xdg-open <path>` command.

## Testing without hardware
The scripts in this skill directory render `draw()` offscreen (`SDL_VIDEODRIVER=dummy`, 800x480) and save PNGs. Run them from anywhere; they locate the project themselves.

1. `python3 .claude/skills/pipedal-lcd/render_test.py [outdir]`
   - Uses fake states covering 4th-effect overflow, bypassed slots, the modified dot, OFFLINE, non-matching names, and every colour.
   - Writes one PNG per state × label mode.
   - Prints the `display_key` tuples, so filtering can be checked as text.
2. `python3 .claude/skills/pipedal-lcd/render_live.py [host] [outdir]`
   - **Ask the user first.**
   - Gets one live state from the Pi (default host `192.168.1.248`).
   - Prints every caption, marking which ones get a slot, and writes `live_{word,type,full}.png`.

`outdir` defaults to the current directory; use the session scratchpad. After rendering, Read the PNGs to check layout, contrast and text fit.

## Ideas not yet done
- **Xrun indicator.** PiPedal's web UI polls a `getJackStatus` request, believed to include an underrun counter, time since the last underrun, CPU % and temperature.
  - This is unverified: probe it once on the live Pi (with permission) to get the real field names before coding.
  - Plan: poll about once a second and flash a red `XRUN` badge for a few seconds whenever the counter goes up.
