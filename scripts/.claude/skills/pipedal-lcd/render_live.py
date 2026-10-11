#!/usr/bin/env python3
"""Fetch one live state from PiPedal (read-only) and render it offscreen.
Usage: render_live.py [host] [outdir]"""
import asyncio, os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT)

import pygame
import lcd
from pipedal_stage import PiPedalClient

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.248"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
os.makedirs(OUT, exist_ok=True)
URL = f"ws://{HOST}:80/pipedal"


async def first_state():
    got = asyncio.get_running_loop().create_future()

    def on_change(s):
        if s.connected and not got.done():
            got.set_result(s)

    task = asyncio.create_task(PiPedalClient(URL, on_change).run_forever())
    try:
        return await asyncio.wait_for(got, 10)
    finally:
        task.cancel()


state = asyncio.run(first_state())
print("preset:", repr(state.preset), "modified:", state.preset_modified,
      "snapshot:", repr(state.snapshot))
for e in state.effects:
    match = "SLOT" if lcd.PREFIX_RE.match(e.name.strip()) else "    "
    print(f"  {match} {'ON ' if e.enabled else 'off'} {e.name!r}")

pygame.init()
screen = pygame.display.set_mode((800, 480))
for mode in ("word", "type", "full"):
    key = lcd.display_key(state, mode)
    print(mode, key)
    lcd.draw(screen, key)
    pygame.image.save(screen, os.path.join(OUT, f"live_{mode}.png"))
pygame.quit()
print("PNGs written to", OUT)
