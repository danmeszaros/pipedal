#!/usr/bin/env python3
"""Render lcd.draw() offscreen for fake states; one PNG per case x label mode.
Usage: render_test.py [outdir]"""
import os, sys
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, PROJECT)

import pygame
import lcd
from pipedal_stage import StageState, Effect

OUT = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
os.makedirs(OUT, exist_ok=True)


def fx(name, on):
    return Effect(0, name, on)


cases = {
    "full_chain": StageState(connected=True, preset="CLEAN VERSE", effects=[
        fx("Gate", True), fx("OD Klon Clone", True), fx("Amp NAM", True),
        fx("CHO Small Clone", False), fx("Cab IR", True), fx("DLY Tape Echo", True),
        fx("FUZ Muff", True), fx("Reverb", True)]),   # FUZ = 4th, must be dropped
    "two_slots_modified": StageState(connected=True, preset="LEAD", preset_modified=True,
        effects=[fx("BST Mini", False), fx("Amp", True), fx("PHA 90", True), fx("ODYSSEY", True)]),
    "offline_no_fx": StageState(connected=False, preset="AMBIENT",
        effects=[fx("Amp", True), fx("od lowercase", True)]),
}

pygame.init()
screen = pygame.display.set_mode((800, 480))
print("font file present:", os.path.exists(lcd.FONT_FILE))

for mode in ("type", "word", "full"):
    for name, st in cases.items():
        key = lcd.display_key(st, mode)
        print(mode, name, key)
        lcd.draw(screen, key)
        pygame.image.save(screen, os.path.join(OUT, f"{name}_{mode}.png"))

# Palette: every type, alternating enabled / bypassed, 3 per image.
types = list(lcd.EFFECT_TYPES)
for i in range(0, len(types), lcd.NUM_SLOTS):
    chunk = types[i:i + lcd.NUM_SLOTS]
    st = StageState(connected=True, preset=f"PALETTE {i // lcd.NUM_SLOTS}",
                    effects=[fx(k + " X", n % 2 == 0) for n, k in enumerate(chunk)])
    lcd.draw(screen, lcd.display_key(st, "type"))
    pygame.image.save(screen, os.path.join(OUT, f"palette_{i // lcd.NUM_SLOTS}.png"))
pygame.quit()
print("PNGs written to", OUT)
