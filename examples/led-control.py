#!/usr/bin/env python3
"""Control Corne RGB LEDs via Raw HID.

Requires: pip install hidapi
Protocol: 32-byte packets to VID=0x4653 PID=0x0004 usage_page=0xFF60

Commands:
  0x01 led_index R G B     — set single LED
  0x02 R G B               — set all LEDs
  0x03 row col R G B       — set by matrix position
  0xFF                     — reset to default
"""

import hid
import time

VID = 0x4653
PID = 0x0004
USAGE_PAGE = 0xFF60

def find_device():
    for d in hid.enumerate(VID, PID):
        if d['usage_page'] == USAGE_PAGE:
            return d['path']
    return None

def send(dev, *bytes_):
    packet = list(bytes_) + [0] * (32 - len(bytes_))
    dev.write([0x00] + packet)  # report ID 0 + 32 bytes

def set_led(dev, index, r, g, b):
    send(dev, 0x01, index, r, g, b)

def set_all(dev, r, g, b):
    send(dev, 0x02, r, g, b)

def set_matrix(dev, row, col, r, g, b):
    send(dev, 0x03, row, col, r, g, b)

def reset(dev):
    send(dev, 0xFF)

if __name__ == '__main__':
    path = find_device()
    if not path:
        print("Corne not found (is Raw HID enabled in firmware?)")
        exit(1)

    dev = hid.device()
    dev.open_path(path)
    print(f"Connected: {dev.get_manufacturer_string()} {dev.get_product_string()}")

    # Example: red sweep across all LEDs
    for i in range(23):
        set_led(dev, i, 255, 0, 0)
        time.sleep(0.05)

    time.sleep(1)

    # All green
    set_all(dev, 0, 255, 0)
    time.sleep(1)

    # Reset to default
    reset(dev)
    dev.close()
