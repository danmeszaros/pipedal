#!/usr/bin/env python3
"""
lcd.py — PiPedal stage LCD (pygame / KMSDRM, no desktop needed).

Top:    current preset name in large type (+ "modified" dot, "OFFLINE" warning).
Bottom: three effect slots. Only effects whose plugin caption starts with a
        known type prefix (uppercase, followed by a space, e.g. "OD Klon") are
        shown, left to right in signal-chain order, max 3.
        Enabled = vivid colour, bypassed = dark colour, unused slot = black.
Sides:  vertical peak meters above the slots, input on the left, output on the right, with a
        peak-hold line and a clip light on top.

Live data comes from the PiPedal websocket via pipedal_stage.PiPedalClient,
so pipedal_stage.py must sit in the same directory.

Usage:
    lcd.py                          # slot label mode "word"  ->  Klon
    lcd.py --label full             # OD Klon
    lcd.py --label type             # OD
    lcd.py --host 127.0.0.1 --port 80
"""

import argparse
import asyncio
import os
import queue
import re
import math
import signal
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
os.environ.setdefault("SDL_DRM_DEVICE", "/dev/dri/card0")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pipedal_stage import PiPedalClient, StageState, VU_INPUT_ID, VU_OUTPUT_ID  # noqa: E402

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

FONT_FILE = os.path.join(HERE, "BNMachine.ttf")
NAME_FONT_SIZE = 110        # fixed; preset names are expected to fit
NUM_SLOTS = 3
LABEL_MODE = "word"         # default for --label: "type" | "word" | "full"

# Caption prefix -> vivid colour (enabled). Bypassed uses a darkened version.
EFFECT_TYPES = {
    "OD":  (255, 200,   0),   # overdrive   - yellow
    "CHO": (150,  60, 220),   # chorus      - violet
    "DLY": ( 30, 110, 255),   # delay       - blue
    "TRM": (  0, 180, 170),   # tremolo     - teal
    "PHA": (255, 120,   0),   # phaser      - orange
    "FLA": (230,  60, 150),   # flanger     - pink
    "WAH": (170, 110,  40),   # wah         - bronze
    "CMP": (175, 180, 190),   # compressor  - silver
    "BST": (220,  30,  30),   # boost       - red
    "FUZ": ( 40, 170,  60),   # fuzz        - green
}
DIM_BG = 0.25               # bypassed background = colour * DIM_BG
DIM_FG = 0.75               # bypassed text       = colour * DIM_FG

# VU meters (dBFS, linear-in-dB scale from METER_FLOOR_DB to 0).
VU_METERS = True            # False: no meters and no VU subscription to the server
METER_W = 16                # bar width in px
METER_FLOOR_DB = -60.0
METER_YELLOW_DB = -12.0     # zone boundaries
METER_RED_DB = -3.0
METER_FALL_DB_S = 96.0      # bar fall rate (full 60 dB scale in 0.6 s)
PEAK_HOLD_S = 1.5           # peak line holds, then falls at METER_FALL_DB_S
CLIP_HOLD_S = 2.0           # clip light stays on this long after a sample >= 0 dBFS
METER_DIM = 0.18            # unlit part of the bar = zone colour * METER_DIM
METER_GREEN = (40, 200, 60)
METER_YELLOW = (255, 200, 0)
METER_RED = (230, 30, 30)
FPS = 30
NICE = 19                   # CPU priority increment for this process (19 = lowest), keeps the audio ahead

BG = (0, 0, 0)
EMPTY_SLOT = (20, 20, 20)    # unassigned slot box - dark grey
FG = (255, 255, 255)
WARN = (255, 176, 32)

# "OD Klon" -> ("OD", "Klon"); "OD" alone -> ("OD", None). Case-sensitive.
PREFIX_RE = re.compile(r"^(%s)(?: +(.*))?$" % "|".join(map(re.escape, EFFECT_TYPES)))


# --------------------------------------------------------------------------
# State -> what to show
# --------------------------------------------------------------------------

def slot_label(kind, rest, mode):
    rest = (rest or "").strip()
    if mode == "type" or not rest:
        return kind
    if mode == "word":
        return rest.split()[0]
    return f"{kind} {rest}"


def display_key(s: StageState, mode):
    """Everything that is drawn; redraw only when this changes."""
    slots = []
    for e in s.effects:
        m = PREFIX_RE.match(e.name.strip())
        if not m:
            continue
        slots.append((m.group(1), slot_label(m.group(1), m.group(2), mode), e.enabled))
        if len(slots) == NUM_SLOTS:
            break
    return (s.preset, s.preset_modified, s.connected, tuple(slots))


# --------------------------------------------------------------------------
# VU meters
# --------------------------------------------------------------------------

def to_db(v):
    return 20 * math.log10(v) if v > 1e-6 else -120.0


class Meter:
    """Peak meter. feed() is called from the websocket thread, tick() once per frame."""

    def __init__(self):
        self._pending = 0.0          # max linear peak since the last tick
        self.level = METER_FLOOR_DB  # dB
        self.peak = METER_FLOOR_DB   # dB
        self._peak_t = 0.0
        self._clip_t = -1e9
        self.clip = False

    def feed(self, v):
        if v > self._pending:
            self._pending = v

    def tick(self, now, dt):
        v, self._pending = self._pending, 0.0
        db = to_db(v)
        self.level = max(db, self.level - METER_FALL_DB_S * dt, METER_FLOOR_DB)
        if db >= self.peak:
            self.peak, self._peak_t = db, now
        elif now - self._peak_t > PEAK_HOLD_S:
            self.peak = max(self.peak - METER_FALL_DB_S * dt, self.level)
        if v >= 1.0:
            self._clip_t = now
        self.clip = now - self._clip_t < CLIP_HOLD_S

    def view(self):
        """What is drawn: (level dB, peak dB, clip). Rounded so that frames
        which would look the same compare equal and are not redrawn."""
        return (round(self.level, 1), round(self.peak, 1), self.clip)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

_font_cache = {}


def get_font(size):
    f = _font_cache.get(size)
    if f is None:
        path = FONT_FILE if os.path.exists(FONT_FILE) else None
        f = _font_cache[size] = pygame.font.Font(path, size)
    return f


def scale(c, k):
    return tuple(int(v * k) for v in c)


def text_on(bg):
    """Black or white, whichever reads better on bg."""
    r, g, b = bg
    return (0, 0, 0) if 0.299 * r + 0.587 * g + 0.114 * b > 150 else FG


def layout(W, H):
    """(pad, x0, x1, slot_top, slot_h): outer padding, the span between the
    meters (above the slots) and the slot row, which uses the full width."""
    pad = int(min(W, H) * 0.03)
    slot_h = int(H * 0.28)
    return pad, pad + METER_W + pad, W - pad - METER_W - pad, H - pad - slot_h, slot_h


def draw_static(screen, key):
    """Everything except the meters; redrawn only when key changes."""
    preset, modified, connected, slots = key
    W, H = screen.get_size()
    pad, x0, x1, slot_top, slot_h = layout(W, H)
    gap = pad

    screen.fill(BG)

    # Preset name, centred in the area above the slots.
    surf = get_font(NAME_FONT_SIZE).render(preset or "—", True, FG)
    screen.blit(surf, surf.get_rect(center=((x0 + x1) // 2, (slot_top - gap) // 2)))

    small = get_font(max(14, H // 16))
    if modified:
        r = max(6, H // 40)
        pygame.draw.circle(screen, WARN, (x0 + r, pad + r), r)
    if not connected:
        warn = small.render("OFFLINE", True, WARN)
        screen.blit(warn, warn.get_rect(topright=(x1, pad)))

    # Effect slots.
    slot_w = (W - 2 * pad - (NUM_SLOTS - 1) * gap) // NUM_SLOTS
    radius = max(4, slot_h // 10)

    # One common label size: as big as fits height, shrunk to fit the widest label.
    size = int(slot_h * 0.6)
    labels = [label for _, label, _ in slots]
    while size > 10 and labels and max(get_font(size).size(t)[0] for t in labels) > slot_w * 0.9:
        size -= 2
    label_font = get_font(size)

    for i in range(NUM_SLOTS):
        rect = pygame.Rect(pad + i * (slot_w + gap), slot_top, slot_w, slot_h)
        if i >= len(slots):
            pygame.draw.rect(screen, EMPTY_SLOT, rect, border_radius=radius)
            continue
        kind, label, enabled = slots[i]
        color = EFFECT_TYPES[kind]
        if enabled:
            bg, fg = color, text_on(color)
        else:
            bg, fg = scale(color, DIM_BG), scale(color, DIM_FG)
        pygame.draw.rect(screen, bg, rect, border_radius=radius)
        t = label_font.render(label, True, fg)
        screen.blit(t, t.get_rect(center=rect.center))


def draw_meter(screen, x, view):
    """One vertical meter at x, above the slots: clip light on top, bar below."""
    level, peak, clip = view
    pad, _, _, slot_top, _ = layout(*screen.get_size())
    clip_rect = pygame.Rect(x, pad, METER_W, METER_W)
    pygame.draw.rect(screen, METER_RED if clip else scale(METER_RED, METER_DIM), clip_rect)

    top = clip_rect.bottom + pad // 2
    bottom = slot_top - pad
    span = bottom - top

    def y_of(db):
        f = (min(db, 0.0) - METER_FLOOR_DB) / -METER_FLOOR_DB
        return bottom - int(max(0.0, f) * span)

    y_lvl = y_of(level)
    zones = ((METER_FLOOR_DB, METER_YELLOW_DB, METER_GREEN),
             (METER_YELLOW_DB, METER_RED_DB, METER_YELLOW),
             (METER_RED_DB, 0.0, METER_RED))
    for lo, hi, color in zones:
        y_lo, y_hi = y_of(lo), y_of(hi)
        pygame.draw.rect(screen, scale(color, METER_DIM), (x, y_hi, METER_W, y_lo - y_hi))
        lit_top = max(y_hi, y_lvl)
        if lit_top < y_lo:
            pygame.draw.rect(screen, color, (x, lit_top, METER_W, y_lo - lit_top))
    if peak > METER_FLOOR_DB:
        color = next(c for lo, hi, c in zones if peak < hi or hi == 0.0)
        pygame.draw.rect(screen, color, (x, y_of(peak) - 1, METER_W, 3))


def meter_rects(W, H):
    """Screen areas of the input and output meters (clip light to bar bottom)."""
    pad, _, _, slot_top, _ = layout(W, H)
    h = slot_top - 2 * pad
    return [pygame.Rect(pad, pad, METER_W, h), pygame.Rect(W - pad - METER_W, pad, METER_W, h)]


def draw_meters(screen, vin, vout):
    if not VU_METERS:
        return
    r_in, r_out = meter_rects(*screen.get_size())
    draw_meter(screen, r_in.x, vin)
    draw_meter(screen, r_out.x, vout)


IDLE_METER = (METER_FLOOR_DB, METER_FLOOR_DB, False)


def draw(screen, key, vin=IDLE_METER, vout=IDLE_METER):
    draw_static(screen, key)
    draw_meters(screen, vin, vout)
    pygame.display.update()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="PiPedal stage LCD.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--label", choices=("type", "word", "full"), default=LABEL_MODE,
                    help='slot text for "OD Klon Clone": type=OD, word=Klon, full=OD Klon Clone')
    args = ap.parse_args()

    # Before any thread starts: on Linux nice is per thread and inherited by new threads.
    try:
        os.nice(NICE)
    except OSError as e:
        print(f"lcd: nice failed: {e}", file=sys.stderr)

    updates = queue.Queue()
    m_in, m_out = Meter(), Meter()

    def on_vu(body):
        iid = body.get("instanceId")
        if iid == VU_INPUT_ID:
            m_in.feed(body.get("inputMaxValueL", 0.0))
        elif iid == VU_OUTPUT_ID:
            m_out.feed(max(body.get("outputMaxValueL", 0.0), body.get("outputMaxValueR", 0.0)))

    client = PiPedalClient(f"ws://{args.host}:{args.port}/pipedal", updates.put,
                           on_vu if VU_METERS else None)
    threading.Thread(target=lambda: asyncio.run(client.run_forever()), daemon=True).start()

    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)

    running = True

    def handle_shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # The static part is rendered into `background` only when key changes and
    # then pushed to the screen whole. Meter-only frames restore just the meter
    # areas from `background`, draw the meters and update only those rects.
    background = pygame.Surface(screen.get_size())
    m_rects = meter_rects(*screen.get_size())
    key = display_key(StageState(preset="WELCOME"), args.label)
    draw_static(background, key)
    shown = None                      # (key, meter views) currently on screen
    clock = pygame.time.Clock()
    last = time.monotonic()

    try:
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False

            latest = None
            try:
                while True:
                    latest = updates.get_nowait()
            except queue.Empty:
                pass

            if latest is not None:
                new_key = display_key(latest, args.label)
                if new_key != key:
                    key = new_key
                    draw_static(background, key)

            now = time.monotonic()
            m_in.tick(now, now - last)
            m_out.tick(now, now - last)
            last = now
            frame = (key, m_in.view(), m_out.view())
            if shown is None or frame[0] != shown[0]:
                screen.blit(background, (0, 0))
                draw_meters(screen, frame[1], frame[2])
                pygame.display.update()
            elif frame != shown and VU_METERS:    # silence / steady state: no redraw
                for r in m_rects:
                    screen.blit(background, r, r)
                draw_meters(screen, frame[1], frame[2])
                pygame.display.update(m_rects)
            shown = frame

            clock.tick(FPS)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
