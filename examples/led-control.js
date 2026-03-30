#!/usr/bin/env node
/**
 * Control Corne RGB LEDs via Raw HID.
 * Requires: npm install node-hid
 *
 * Protocol: 32-byte packets to VID=0x4653 PID=0x0004 usage_page=0xFF60
 * Commands:
 *   0x01 led_index R G B     — set single LED
 *   0x02 R G B               — set all LEDs
 *   0x03 row col R G B       — set by matrix position
 *   0xFF                     — reset to default
 */

const HID = require('node-hid')

const VID = 0x4653
const PID = 0x0004
const USAGE_PAGE = 0xFF60

function findDevice() {
  return HID.devices().find(d =>
    d.vendorId === VID && d.productId === PID && d.usagePage === USAGE_PAGE
  )
}

function send(dev, ...bytes) {
  const packet = Buffer.alloc(33) // report ID 0 + 32 bytes
  bytes.forEach((b, i) => packet[i + 1] = b)
  dev.write(packet)
}

const info = findDevice()
if (!info) { console.log('Corne not found (is Raw HID enabled?)'); process.exit(1) }

const dev = new HID.HID(info.path)
console.log(`Connected: ${info.manufacturer} ${info.product}`)

// Example: all blue
send(dev, 0x02, 0, 0, 255)

setTimeout(() => {
  send(dev, 0xFF) // reset
  dev.close()
}, 2000)
