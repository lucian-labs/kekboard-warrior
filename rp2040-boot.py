#!/usr/bin/env python3
"""Force an RP2040 running QMK into USB bootloader mode.

Uses the PICOBOOT vendor interface if available, or falls back to
sending a QMK-specific raw HID reset command.

For Corne v4: vendor=0x4653 product=0x0004
"""

import sys
import usb.core
import usb.util
import struct
import time

VENDOR_ID = 0x4653
PRODUCT_ID = 0x0004

# PICOBOOT interface constants (RP2040 ROM bootloader)
PICOBOOT_INTERFACE_CLASS = 0xFF
PICOBOOT_INTERFACE_SUBCLASS = 0x00
PICOBOOT_INTERFACE_PROTOCOL = 0x00

# QMK uses ChibiOS on RP2040 — we can trigger bootloader via
# a USB device reset followed by holding BOOTSEL timing trick,
# OR via the QMK raw HID "bootloader jump" command if raw HID is enabled.
# Since raw HID isn't enabled in the joystick firmware, we'll try
# the direct approach: find the device, send a USB reset, and if that
# doesn't work, try vendor-specific control transfers.


def find_device():
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev:
        return dev
    # also check for RPI-RP2 bootloader mode
    dev = usb.core.find(idVendor=0x2e8a, idProduct=0x0003)
    if dev:
        print("Device already in bootloader mode (RPI-RP2)")
        sys.exit(0)
    return None


def try_picoboot_reboot(dev):
    """Try to reboot via PICOBOOT vendor interface (only works if exposed)."""
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass == 0xFF:  # vendor specific
                print(f"  Found vendor interface {intf.bInterfaceNumber}, trying PICOBOOT reboot...")
                try:
                    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                    # PICOBOOT reboot command
                    dev.ctrl_transfer(0x21, 0x01, 0, intf.bInterfaceNumber, b'')
                    print("  PICOBOOT reboot sent!")
                    return True
                except Exception as e:
                    print(f"  PICOBOOT failed: {e}")
    return False


def try_qmk_reset(dev):
    """Try QMK-specific reset methods."""
    # Method 1: Send SET_PROTOCOL on the HID interface
    # Some QMK builds respond to this by resetting
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass == 3:  # HID
                try:
                    if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                        dev.detach_kernel_driver(intf.bInterfaceNumber)
                except:
                    pass

    # Method 2: USB port power cycle via sysfs
    # This triggers re-enumeration. If bootmagic is enabled in QMK,
    # holding a key during this reset will enter bootloader.
    print("  Attempting USB device reset...")
    try:
        dev.reset()
        print("  USB reset sent. Check if RPI-RP2 drive appeared.")
        return True
    except Exception as e:
        print(f"  USB reset failed: {e}")
        return False


def main():
    print(f"Looking for Corne (VID={VENDOR_ID:#06x} PID={PRODUCT_ID:#06x})...")
    dev = find_device()
    if not dev:
        print("ERROR: Device not found on USB")
        sys.exit(1)

    print(f"Found device on bus {dev.bus}, address {dev.address}")

    # List interfaces
    for cfg in dev:
        for intf in cfg:
            print(f"  Interface {intf.bInterfaceNumber}: class={intf.bInterfaceClass} sub={intf.bInterfaceSubClass} proto={intf.bInterfaceProtocol}")

    # Try PICOBOOT first (unlikely in application mode, but worth trying)
    if try_picoboot_reboot(dev):
        time.sleep(1)
        # verify bootloader mode
        bl = usb.core.find(idVendor=0x2e8a, idProduct=0x0003)
        if bl:
            print("SUCCESS: Device is now in bootloader mode!")
            return

    # Try QMK reset
    try_qmk_reset(dev)

    # Check for bootloader after a moment
    time.sleep(2)
    bl = usb.core.find(idVendor=0x2e8a, idProduct=0x0003)
    if bl:
        print("SUCCESS: Device is now in bootloader mode!")
    else:
        # check if device is still there
        dev2 = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev2:
            print("Device still in application mode. Boot combo may be needed.")
            print("TIP: Hold 7,5 + 7,4 + 4,6 + 5,6 simultaneously (all 4 at once)")
        else:
            print("Device disconnected — check for RPI-RP2 drive mount")


if __name__ == '__main__':
    main()
