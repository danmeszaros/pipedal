# pipedal

## image
use rpi-images, install other -> lite os 64bit

## setup
```
sudo raspi-config nonint do_wifi_country CZ
# activate connection
sudo nmtui

# enable ssh, spi i2c
sudo raspi-config

apt-get update
apt-get dist-upgrade

# power off bus on power down
sudo rpi-eeprom-config --edit
# add POWER_OFF_ON_HALT=1

# add service/pipedal_lcd.service to /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pipedal_lcd.service
sudo systemctl start pipedal_lcd.service

reboot
```

## lcd sample code
prepare
```
sudo apt-get install python3-dev python3-pil libjpeg-dev zlib1g-dev libfreetype6-dev liblcms2-dev libopenjp2-7 libtiff5-dev
sudo apt-get install python3-pip

python -m venv venv --system-site-packages
source venv/bin/activate
pip install luma.lcd
```

code
```
from PIL import Image
from luma.lcd.device import ili9486
from luma.core.interface.serial import spi
from luma.core.render import canvas

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

if __name__ == "__main__":
    # Replace 'wallpaper.jpg' with your actual file name
    try:
        #display_image("/usr/share/icons/hicolor/64x64/apps/mkvextract.png")
        display_image("heart.png")
        #with canvas(device) as draw:
        #    # If this looks Cyan, you need to swap RGB/BGR
        #    # If this looks White/Grey, you need to toggle Inversion (0x21)
        #    draw.rectangle((0, 0, 100, 100), fill="red")
        #    draw.text((10, 10), "Should be RED", fill="white")


        input("Press Enter to exit...")
    except FileNotFoundError:
        print("Error: Image file not found. Make sure it's in the same folder!")
```
## lcd v2

```
sudo usermod -aG video,render,input $USER
sudo apt install libsdl2-2.0-0 libsdl2-dev
sudo apt install python3-pygame
```
