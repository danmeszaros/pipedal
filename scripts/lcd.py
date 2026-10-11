#!/usr/bin/env python3
"""
lcd.py — PiPedal stage LCD (pygame / KMSDRM, no desktop needed).

Top:    current preset name in large type (+ "modified" dot, "OFFLINE" warning).
Bottom: three effect slots. Only effects whose plugin caption starts with a
        known type prefix (uppercase, followed by a space, e.g. "OD Klon") are
        shown, left to right in signal-chain order, max 3.
        Enabled = vivid colour, bypassed = dark colour, unused slot = black.

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
import signal
import sys
import threading

os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
os.environ.setdefault("SDL_DRM_DEVICE", "/dev/dri/card0")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pipedal_stage import PiPedalClient, StageState  # noqa: E402

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


def draw(screen, key):
    preset, modified, connected, slots = key
    W, H = screen.get_size()
    pad = int(min(W, H) * 0.03)
    gap = pad
    slot_h = int(H * 0.28)
    slot_top = H - pad - slot_h

    screen.fill(BG)

    # Preset name, centred in the area above the slots.
    surf = get_font(NAME_FONT_SIZE).render(preset or "—", True, FG)
    screen.blit(surf, surf.get_rect(center=(W // 2, (slot_top - gap) // 2)))

    small = get_font(max(14, H // 16))
    if modified:
        r = max(6, H // 40)
        pygame.draw.circle(screen, WARN, (pad + r, pad + r), r)
    if not connected:
        warn = small.render("OFFLINE", True, WARN)
        screen.blit(warn, warn.get_rect(topright=(W - pad, pad)))

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

    pygame.display.flip()


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

    updates = queue.Queue()
    client = PiPedalClient(f"ws://{args.host}:{args.port}/pipedal", updates.put)
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

    key = display_key(StageState(preset="WELCOME"), args.label)
    draw(screen, key)
    clock = pygame.time.Clock()

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
                    draw(screen, key)

            clock.tick(20)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
