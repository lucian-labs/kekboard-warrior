#!/usr/bin/env python3
"""
Keyboard Translator — Linux evdev/uinput implementation.

One process, multiple modes:
    sudo python3 translator.py scan              — list all input devices
    sudo python3 translator.py discover           — monitor all K585 inputs, save key map
    sudo python3 translator.py run [--no-grab]    — translate keys using keymap.json

Requires: python3-evdev (apt install python3-evdev)
Must run as root (or with uinput permissions).
"""

import argparse
import json
import os
import selectors
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import evdev
from evdev import InputDevice, UInput, ecodes, categorize

from engine import TranslationEngine

OUT_DIR = Path(__file__).parent


def find_devices(vendor_id=None, product_id=None, name_match=None):
    """Find input devices matching criteria. Includes any device with key or rel events."""
    devices = [InputDevice(path) for path in evdev.list_devices()]
    matches = []

    for dev in devices:
        info = dev.info
        vid_match = vendor_id is None or info.vendor == vendor_id
        pid_match = product_id is None or info.product == product_id
        nm_match = name_match is None or name_match.lower() in dev.name.lower()

        caps = dev.capabilities(verbose=False)
        has_events = ecodes.EV_KEY in caps or ecodes.EV_REL in caps

        if vid_match and pid_match and nm_match and has_events:
            matches.append(dev)

    return matches


def make_selector(devices):
    """Create a selector for reading from multiple devices."""
    sel = selectors.DefaultSelector()
    for dev in devices:
        sel.register(dev, selectors.EVENT_READ)
    return sel


# ── scan ──────────────────────────────────────────────────────────────

def cmd_scan():
    """Print all input devices and their capabilities."""
    devices = [InputDevice(path) for path in evdev.list_devices()]
    for dev in devices:
        caps = dev.capabilities(verbose=False)
        key_count = len(caps.get(ecodes.EV_KEY, []))
        has_rel = ecodes.EV_REL in caps
        print(f'\n  {dev.path}  {dev.name}')
        print(f'    vendor={hex(dev.info.vendor)} product={hex(dev.info.product)}')
        print(f'    phys={dev.phys}')
        print(f'    keys={key_count}  rel={"yes" if has_rel else "no"}')


# ── discover ──────────────────────────────────────────────────────────

def cmd_discover(config):
    """Monitor all matching devices, log every event, save a key map on exit."""
    dev_conf = config.get('device', {})
    vendor_id = int(dev_conf.get('vendor_id', '0'), 16) if dev_conf.get('vendor_id') else None
    product_id = int(dev_conf.get('product_id', '0'), 16) if dev_conf.get('product_id') else None
    name_match = dev_conf.get('name')

    devices = find_devices(vendor_id, product_id, name_match)
    if not devices:
        print('No matching devices found! Run: sudo python3 translator.py scan')
        sys.exit(1)

    print(f'Monitoring {len(devices)} device(s):')
    for dev in devices:
        caps = dev.capabilities(verbose=False)
        parts = []
        if ecodes.EV_KEY in caps:
            parts.append(f'{len(caps[ecodes.EV_KEY])} keys')
        if ecodes.EV_REL in caps:
            parts.append('rel')
        print(f'  {dev.path}  {dev.name}  [{", ".join(parts)}]')

    print(f'\nPress every key on the keyboard. Ctrl+C to stop and save.\n')

    key_map = {}
    log_lines = []
    sel = make_selector(devices)

    map_file = OUT_DIR / 'discovered-keys.json'
    log_file = OUT_DIR / 'discover.log'

    def save_and_exit(*_):
        print(f'\n\nSaving {len(key_map)} unique keys...')

        output = {
            'device': dev_conf.get('name', 'unknown'),
            'vendor_id': dev_conf.get('vendor_id'),
            'product_id': dev_conf.get('product_id'),
            'discovered_at': datetime.now().isoformat(),
            'devices_monitored': [
                {'path': d.path, 'name': d.name, 'phys': d.phys}
                for d in devices
            ],
            'keys': {}
        }

        for code in sorted(k for k in key_map if isinstance(k, int)):
            info = key_map[code]
            output['keys'][info['name']] = {
                'code': code,
                'device_paths': sorted(info['devices']),
                'press_count': info['count'],
            }

        for rk in sorted(k for k in key_map if isinstance(k, str)):
            info = key_map[rk]
            output['keys'][rk] = {
                'type': 'rel_axis',
                'device_paths': sorted(info['devices']),
                'event_count': info['count'],
            }

        with open(map_file, 'w') as f:
            json.dump(output, f, indent=2)
        print(f'  Key map  → {map_file}')

        with open(log_file, 'w') as f:
            f.write('\n'.join(log_lines) + '\n')
        print(f'  Raw log  → {log_file}  ({len(log_lines)} events)')
        sys.exit(0)

    signal.signal(signal.SIGINT, save_and_exit)
    signal.signal(signal.SIGTERM, save_and_exit)

    while True:
        for key, _ in sel.select():
            dev = key.fileobj
            for event in dev.read():
                ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

                if event.type == ecodes.EV_KEY:
                    key_event = categorize(event)
                    name = key_event.keycode
                    if isinstance(name, list):
                        name = name[0]
                    state = {0: 'UP', 1: 'DOWN', 2: 'HOLD'}[event.value]

                    log_lines.append(f'{ts}  {state:4s}  code={event.code:3d}  {name:30s}  {dev.path}')

                    if event.value == 1:
                        if event.code not in key_map:
                            key_map[event.code] = {'name': name, 'devices': set(), 'count': 0}
                            print(f'  NEW  code={event.code:3d}  {name:30s}  ({dev.path})')
                        key_map[event.code]['devices'].add(dev.path)
                        key_map[event.code]['count'] += 1

                elif event.type == ecodes.EV_REL:
                    axis = ecodes.REL.get(event.code, f'REL_{event.code}')
                    log_lines.append(f'{ts}  REL   axis={str(axis):20s}  value={event.value:4d}  {dev.path}')

                    rk = f'REL_{axis}'
                    if rk not in key_map:
                        key_map[rk] = {'name': str(axis), 'devices': set(), 'count': 0}
                        print(f'  NEW  {str(axis):35s}  ({dev.path})')
                    key_map[rk]['devices'].add(dev.path)
                    key_map[rk]['count'] += 1


# ── run (translate) ───────────────────────────────────────────────────

def cmd_run(keymap_path, grab=True):
    """Main translation loop."""
    engine = TranslationEngine(keymap_path)
    config = engine.config

    dev_conf = config.get('device', {})
    vendor_id = int(dev_conf.get('vendor_id', '0'), 16) if dev_conf.get('vendor_id') else None
    product_id = int(dev_conf.get('product_id', '0'), 16) if dev_conf.get('product_id') else None
    name_match = dev_conf.get('name')

    devices = find_devices(vendor_id, product_id, name_match)
    if not devices:
        print('No matching keyboard found! Run: sudo python3 translator.py scan')
        sys.exit(1)

    print(f'Found {len(devices)} device(s):')
    for dev in devices:
        print(f'  {dev.path}  {dev.name}')

    # collect all capabilities from all matched devices
    all_keys = set()
    all_rel = set()
    for dev in devices:
        caps = dev.capabilities(verbose=False)
        if ecodes.EV_KEY in caps:
            all_keys.update(caps[ecodes.EV_KEY])
        if ecodes.EV_REL in caps:
            all_rel.update(caps[ecodes.EV_REL])

    ui_caps = {ecodes.EV_KEY: list(all_keys)}
    if all_rel:
        ui_caps[ecodes.EV_REL] = list(all_rel)
    ui = UInput(ui_caps, name='KeyTranslator Virtual Keyboard')
    print(f'Virtual device: {ui.device.path}')

    status = engine.get_status()
    print(f'Layer: {status["layer_name"]} | Keymap: {config["name"]}')
    print(f'Translating... (Ctrl+C to stop)\n')

    if grab:
        for dev in devices:
            dev.grab()
            print(f'  Grabbed: {dev.path}')

    def cleanup(*_):
        print('\nReleasing devices...')
        if grab:
            for dev in devices:
                try:
                    dev.ungrab()
                except Exception:
                    pass
        ui.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    sel = make_selector(devices)

    try:
        while True:
            for key, _ in sel.select():
                dev = key.fileobj
                for event in dev.read():
                    if event.type == ecodes.EV_KEY:
                        outputs = engine.process_key(event.code, event.value)
                        for out_code, out_value in outputs:
                            ui.write(ecodes.EV_KEY, out_code, out_value)
                            ui.syn()

                        new_status = engine.get_status()
                        if new_status['layer'] != status['layer']:
                            print(f'  Layer → {new_status["layer_name"]}')
                            status = new_status

                    elif event.type == ecodes.EV_REL:
                        ui.write(event.type, event.code, event.value)
                        ui.syn()

                    elif event.type not in (ecodes.EV_SYN, ecodes.EV_MSC):
                        ui.write(event.type, event.code, event.value)
                        ui.syn()
    except Exception as e:
        print(f'\nError: {e}')
        cleanup()


# ── main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Keyboard Translator')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('scan', help='List all input devices')

    p_discover = sub.add_parser('discover', help='Monitor all K585 inputs, save key map')
    p_discover.add_argument('--keymap', '-k', default='keymap.json')

    p_run = sub.add_parser('run', help='Translate keys using keymap config')
    p_run.add_argument('--keymap', '-k', default='keymap.json')
    p_run.add_argument('--no-grab', action='store_true',
                       help='Do not grab device (allows dual input for testing)')

    args = parser.parse_args()

    if os.geteuid() != 0:
        print('Must run as root (sudo).')
        sys.exit(1)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'scan':
        cmd_scan()
        return

    # load config for device matching
    keymap_path = Path(getattr(args, 'keymap', 'keymap.json'))
    if not keymap_path.is_absolute():
        keymap_path = OUT_DIR / keymap_path

    if args.command == 'discover':
        with open(keymap_path) as f:
            config = json.load(f)
        cmd_discover(config)

    elif args.command == 'run':
        if not keymap_path.exists():
            print(f'Keymap not found: {keymap_path}')
            sys.exit(1)
        cmd_run(str(keymap_path), grab=not args.no_grab)


if __name__ == '__main__':
    main()
