#
# show patchname on lcd screen
#


from PIL import Image
from luma.lcd.device import ili9486
from luma.core.interface.serial import spi
from luma.core.render import canvas
from PIL import ImageFont
import json
import time

# 1. Re-initialize (Same as before)
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25, bus_speed_hz=16000000)
device = ili9486(serial, width=320, height=480, rotate=1)
device.command(0x20) 

def display_image(image_path):
    # 2. Load and Resize
    # Use Image.Resampling.LANCZOS for better quality on the Pi 5
    img = Image.open(image_path).convert("RGB").resize((480, 320), Image.Resampling.LANCZOS)
    
    # 3. Display it
    # .display() sends the raw pixel data to the SPI bus
    print(f"Displaying {image_path}...")
    device.display(img)

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


def draw_large_text(message, font_size=40, y_pos=None):
    """
    Renders large text centered horizontally on the screen.
    """
    try:
        # Load a TrueType font. Adjust the path for your OS (e.g., /usr/share/fonts/...)
        # 'DejaVuSans.ttf' is common on Raspberry Pi/Linux
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except IOError:
        # Fallback to a basic (usually small) default if the file isn't found
        font = ImageFont.load_default()
        print("Warning: Custom font not found, using default.")
from PIL import Image
from luma.lcd.device import ili9486
from luma.core.interface.serial import spi
from luma.core.render import canvas
from PIL import ImageFont
import json
import time

# 1. Re-initialize (Same as before)
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25, bus_speed_hz=16000000)
device = ili9486(serial, width=320, height=480, rotate=1)
device.command(0x20) 

def display_image(image_path):
    # 2. Load and Resize
    # Use Image.Resampling.LANCZOS for better quality on the Pi 5
    img = Image.open(image_path).convert("RGB").resize((480, 320), Image.Resampling.LANCZOS)
    
    # 3. Display it
    # .display() sends the raw pixel data to the SPI bus
    print(f"Displaying {image_path}...")
    device.display(img)

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


def draw_large_text(message, font_size=40, y_pos=None):
    """
    Renders large text centered horizontally on the screen.
    """
    try:
        # Load a TrueType font. Adjust the path for your OS (e.g., /usr/share/fonts/...)
        # 'DejaVuSans.ttf' is common on Raspberry Pi/Linux
        font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    except IOError:
        # Fallback to a basic (usually small) default if the file isn't found
        font = ImageFont.load_default()
        print("Warning: Custom font not found, using default.")
    with canvas(device) as draw:
        # Calculate text size to center it
        # Note: getbbox returns (left, top, right, bottom)
        left, top, right, bottom = draw.textbbox((0, 0), message, font=font)
        w = right - left
        h = bottom - top
        
        # Center horizontally, and either center vertically or use provided y_pos
        x = (device.width - w) // 2
        y = (device.height - h) // 2 if y_pos is None else y_pos
        
        draw.text((x, y), message, font=font, fill="white")

# --- Example Usage ---
# draw_large_text(device, "PRESET: HEAVY", font_size=50)

if __name__ == "__main__":
    # Replace 'wallpaper.jpg' with your actual file name
    try:
        #display_image("/usr/share/icons/hicolor/64x64/apps/mkvextract.png")
        ##display_image("heart.png")
        while True:
            preset = get_preset_name_from_file("/var/pipedal/presets/Default+Bank.bank")
            draw_large_text(preset, 70)
            time.sleep(0.5)
        #with canvas(device) as draw:
        #    # If this looks Cyan, you need to swap RGB/BGR
        #    # If this looks White/Grey, you need to toggle Inversion (0x21)
        #    draw.rectangle((0, 0, 100, 100), fill="red")
        #    draw.text((10, 10), "Should be RED", fill="white")


        input("Press Enter to exit...")
    except FileNotFoundError:
        print("Error: Image file not found. Make sure it's in the same folder!")
