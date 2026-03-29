import json
import time
import os
import pygame
import signal
import sys

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_DRM_DEVICE"] = "/dev/dri/card0"

running = True

def handle_shutdown(signum, frame):
    """Gracefully stop the loop when a signal is received"""
    global running
    running = False

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


pygame.init()

# The Pi 5 will automatically detect the DSI resolution (800x480 for the 4.3")
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
width, height = screen.get_size()

running = True
clock = pygame.time.Clock()

font = pygame.font.Font("BNMachine.ttf", 100)
text_surface = font.render("Hello RPi 5!", True, (255, 255, 255))
text_rect = text_surface.get_rect(center=(width // 2, height // 2))

def get_preset_name_from_file(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        target_id = data.get("selectedPreset")
        presets = data.get("presets", [])

        # Search for the matching instanceId
        for entry in presets:
            if entry.get("instanceId") == target_id:
                # Return the name from the inner preset object
                return entry.get("preset", {}).get("name")

        return "Preset ID not found"

    except FileNotFoundError:
        return "Error: File not found"
    except json.JSONDecodeError:
        return "Error: Failed to decode JSON"

def redraw():
    text_surface = font.render(patch_name, True, (255, 255, 255))
    text_rect = text_surface.get_rect(center=(width // 2, height // 2))
    screen.fill((20, 20, 20)) # Dark Grey background
    screen.blit(text_surface, text_rect)
    pygame.display.flip()

# --- Example Usage ---
# draw_large_text(device, "PRESET: HEAVY", font_size=50)

patch_name = "WELCOME"

if __name__ == "__main__":
    # Replace 'wallpaper.jpg' with your actual file name
    try:
        #display_image("/usr/share/icons/hicolor/64x64/apps/mkvextract.png")
        ##display_image("heart.png")
        while running:
            preset = get_preset_name_from_file("/var/pipedal/presets/Default+Bank.bank")

            if preset != patch_name:
                patch_name = preset
                redraw()

            time.sleep(0.1)

        input("Press Enter to exit...")
    except FileNotFoundError:
        print("Error: Image file not found. Make sure it's in the same folder!")
    finally:
        pygame.quit()
        sys.exit(0)
