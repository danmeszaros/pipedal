import board
import digitalio
import rotaryio
import time
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# 1. Initialize MIDI
midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=0)

# 2. Setup Encoders (Rotation)
# Clock (CLK) and Data (DT) pins
enc1 = rotaryio.IncrementalEncoder(board.GP8, board.GP7)
enc2 = rotaryio.IncrementalEncoder(board.GP11, board.GP10)
enc3 = rotaryio.IncrementalEncoder(board.GP22, board.GP21)

encoders = [enc1, enc2, enc3]
last_positions = [0, 0, 0]

# 3. Setup Buttons (SW)
# Using Pull.UP: Button press connects the pin to Ground
button_pins = [board.GP6, board.GP9, board.GP20]
buttons = []
for p in button_pins:
    btn = digitalio.DigitalInOut(p)
    btn.direction = digitalio.Direction.INPUT
    btn.pull = digitalio.Pull.UP
    buttons.append(btn)

last_btn_states = [True, True, True] # True means unpressed (Pull-up)

print("MIDI Encoders Ready!")

while True:
    # Check Encoders (Rotary)
    for i, enc in enumerate(encoders):
        current_pos = enc.position  # No division!
        
        if current_pos != last_positions[i]:
            # This logic ensures we only trigger on a change of 1 or more
            diff = current_pos - last_positions[i]
            
            # Note assignment
            note_num = 36 + (i * 3)
            
            if diff > 0:
                print(f"Encoder {i+1} turned Clockwise")
            elif diff < 0:
                print(f"Encoder {i+1} turned Counter-Clockwise")
                note_num = note_num + 1
                
            midi.send(NoteOn(note_num, 80))
            
            # Immediately send NoteOff so it's ready for the next click
            time.sleep(0.01)
            midi.send(NoteOff(note_num, 0))
            
            # Update last_position to the actual current_pos
            last_positions[i] = current_pos

    # Check Buttons
    for i, btn in enumerate(buttons):
        if btn.value != last_btn_states[i]:
            # btn.value is False when pressed (connected to GND)
            note_num = 38 + (i * 3)
            
            if not btn.value: # Press
                print(f"Button {i+1} Pressed")
                midi.send(NoteOn(note_num, 100))
            else: # Release
                print(f"Button {i+1} Released")
                midi.send(NoteOff(note_num, 0))
            
            last_btn_states[i] = btn.value

    time.sleep(0.001) # Fast polling
