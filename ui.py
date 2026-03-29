#!/usr/bin/env python3
"""
K585 Discovery UI — web-based visual key mapper.

Reads all K585 evdev inputs, streams events to a browser via SSE.
Keys light up on the visual layout as they're discovered.

Usage:
    sudo python3 ui.py [--port 8585]
    Then open http://localhost:8585
"""

import argparse
import json
import os
import queue
import selectors
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import evdev
from evdev import InputDevice, ecodes, categorize

VENDOR = 0x320f
PRODUCT = 0x5000
OUT_DIR = Path(__file__).parent
MAP_FILE = OUT_DIR / 'discovered-keys.json'

# thread-safe event queue for SSE
event_queue = queue.Queue()

# shared state
state = {
    'keys': {},       # code -> {name, devices, count, first_seen}
    'unknown': {},    # code -> {name, devices, count, raw_type, raw_code}
    'log': [],        # last N events
    'lock': threading.Lock(),
}


def find_k585_devices():
    devices = []
    for path in evdev.list_devices():
        dev = InputDevice(path)
        if dev.info.vendor == VENDOR and dev.info.product == PRODUCT:
            caps = dev.capabilities(verbose=False)
            if ecodes.EV_KEY in caps or ecodes.EV_REL in caps:
                devices.append(dev)
    return devices


# known K585 key codes mapped to layout positions
K585_KNOWN_CODES = {
    # row 0: top (ESC + numbers)
    'KEY_ESC', 'KEY_1', 'KEY_2', 'KEY_3', 'KEY_4', 'KEY_5', 'KEY_6', 'KEY_7',
    # row 1: TAB row
    'KEY_TAB', 'KEY_Q', 'KEY_W', 'KEY_E', 'KEY_R', 'KEY_T', 'KEY_Y', 'KEY_U',
    # row 2: CAPS row
    'KEY_CAPSLOCK', 'KEY_A', 'KEY_S', 'KEY_D', 'KEY_F', 'KEY_G',
    # row 3: SHIFT row
    'KEY_LEFTSHIFT', 'KEY_Z', 'KEY_X', 'KEY_C', 'KEY_V', 'KEY_B',
    # row 4: bottom
    'KEY_LEFTCTRL', 'KEY_LEFTALT', 'KEY_SPACE',
    # F keys (some models)
    'KEY_F1', 'KEY_F2', 'KEY_F3', 'KEY_F4', 'KEY_F5', 'KEY_F6',
    'KEY_F7', 'KEY_F8', 'KEY_F9', 'KEY_F10', 'KEY_F11', 'KEY_F12',
    # nav
    'KEY_UP', 'KEY_DOWN', 'KEY_LEFT', 'KEY_RIGHT',
    'KEY_BACKSPACE', 'KEY_ENTER', 'KEY_GRAVE',
    # modifiers
    'KEY_RIGHTSHIFT', 'KEY_RIGHTCTRL', 'KEY_RIGHTALT', 'KEY_FN',
    # G keys (macro)
    'KEY_MACRO1', 'KEY_MACRO2', 'KEY_MACRO3', 'KEY_MACRO4', 'KEY_MACRO5',
    # possible G key codes
    'KEY_F13', 'KEY_F14', 'KEY_F15', 'KEY_F16', 'KEY_F17',
    'KEY_F18', 'KEY_F19', 'KEY_F20', 'KEY_F21', 'KEY_F22', 'KEY_F23', 'KEY_F24',
    # other common
    'KEY_LEFTBRACE', 'KEY_RIGHTBRACE', 'KEY_SEMICOLON', 'KEY_APOSTROPHE',
    'KEY_COMMA', 'KEY_DOT', 'KEY_SLASH', 'KEY_BACKSLASH',
    'KEY_MINUS', 'KEY_EQUAL', 'KEY_8', 'KEY_9', 'KEY_0',
    'KEY_H', 'KEY_I', 'KEY_J', 'KEY_K', 'KEY_L', 'KEY_M', 'KEY_N',
    'KEY_O', 'KEY_P',
}


def evdev_reader(devices):
    """Background thread: read evdev events and push to SSE queue."""
    sel = selectors.DefaultSelector()
    for dev in devices:
        sel.register(dev, selectors.EVENT_READ)

    while True:
        try:
            for key, _ in sel.select(timeout=1):
                dev = key.fileobj
                for event in dev.read():
                    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

                    if event.type == ecodes.EV_KEY:
                        key_event = categorize(event)
                        name = key_event.keycode
                        if isinstance(name, list):
                            name = name[0]
                        state_str = {0: 'UP', 1: 'DOWN', 2: 'HOLD'}.get(event.value, '?')

                        with state['lock']:
                            is_known = name in K585_KNOWN_CODES

                            if event.value == 1:  # press
                                target = state['keys'] if is_known else state['unknown']
                                if event.code not in target:
                                    target[event.code] = {
                                        'name': name,
                                        'devices': set(),
                                        'count': 0,
                                        'first_seen': ts,
                                    }
                                target[event.code]['devices'].add(dev.path)
                                target[event.code]['count'] += 1

                            log_entry = f'{ts}  {state_str:4s}  {name:30s}  code={event.code}  {dev.path}'
                            state['log'].append(log_entry)
                            if len(state['log']) > 200:
                                state['log'] = state['log'][-200:]

                        evt = {
                            'type': 'key',
                            'name': name,
                            'code': event.code,
                            'value': event.value,
                            'state': state_str,
                            'known': name in K585_KNOWN_CODES,
                            'device': dev.path,
                            'ts': ts,
                        }
                        event_queue.put(evt)

                    elif event.type == ecodes.EV_REL:
                        axis = ecodes.REL.get(event.code, f'REL_{event.code}')
                        rk = f'REL_{axis}'

                        with state['lock']:
                            if rk not in state['unknown']:
                                state['unknown'][rk] = {
                                    'name': str(axis),
                                    'devices': set(),
                                    'count': 0,
                                    'first_seen': ts,
                                }
                            state['unknown'][rk]['devices'].add(dev.path)
                            state['unknown'][rk]['count'] += 1

                        evt = {
                            'type': 'rel',
                            'name': str(axis),
                            'code': event.code,
                            'value': event.value,
                            'device': dev.path,
                            'ts': ts,
                        }
                        event_queue.put(evt)

                    elif event.type not in (ecodes.EV_SYN, ecodes.EV_MSC, ecodes.EV_LED, ecodes.EV_REP):
                        # catch anything weird
                        type_name = ecodes.EV.get(event.type, f'EV_{event.type}')
                        with state['lock']:
                            uk = f'{type_name}_{event.code}'
                            if uk not in state['unknown']:
                                state['unknown'][uk] = {
                                    'name': f'{type_name} code={event.code}',
                                    'devices': set(),
                                    'count': 0,
                                    'first_seen': ts,
                                }
                            state['unknown'][uk]['devices'].add(dev.path)
                            state['unknown'][uk]['count'] += 1

                        evt = {
                            'type': 'other',
                            'name': f'{type_name}_{event.code}',
                            'value': event.value,
                            'device': dev.path,
                            'ts': ts,
                        }
                        event_queue.put(evt)

        except Exception as e:
            print(f'evdev reader error: {e}')
            time.sleep(0.1)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.path = '/ui.html'
            # serve from script directory
            file_path = OUT_DIR / 'ui.html'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(file_path.read_bytes())

        elif self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            try:
                while True:
                    try:
                        evt = event_queue.get(timeout=1)
                        data = json.dumps(evt)
                        self.wfile.write(f'data: {data}\n\n'.encode())
                        self.wfile.flush()
                    except queue.Empty:
                        # keepalive
                        self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        elif self.path == '/state':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            with state['lock']:
                out = {
                    'keys': {str(k): {**v, 'devices': list(v['devices'])} for k, v in state['keys'].items()},
                    'unknown': {str(k): {**v, 'devices': list(v['devices'])} for k, v in state['unknown'].items()},
                    'log': state['log'][-50:],
                }
            self.wfile.write(json.dumps(out).encode())

        elif self.path == '/clear':
            with state['lock']:
                state['keys'].clear()
                state['unknown'].clear()
                state['log'].clear()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"cleared"}')

        elif self.path == '/save':
            self._save_map()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'saved', 'path': str(MAP_FILE)}).encode())

        else:
            self.send_error(404)

    def _save_map(self):
        with state['lock']:
            output = {
                'device': 'Redragon K585 DITI',
                'vendor_id': hex(VENDOR),
                'product_id': hex(PRODUCT),
                'discovered_at': datetime.now().isoformat(),
                'keys': {},
                'unknown': {},
            }
            for code, info in sorted(state['keys'].items(), key=lambda x: x[0] if isinstance(x[0], int) else 0):
                output['keys'][info['name']] = {
                    'code': code,
                    'device_paths': sorted(info['devices']),
                    'press_count': info['count'],
                }
            for code, info in state['unknown'].items():
                output['unknown'][str(code)] = {
                    'name': info['name'],
                    'device_paths': sorted(info['devices']),
                    'event_count': info['count'],
                }
        with open(MAP_FILE, 'w') as f:
            json.dump(output, f, indent=2)

    def log_message(self, format, *args):
        # suppress HTTP access logs
        pass


def main():
    parser = argparse.ArgumentParser(description='K585 Discovery UI')
    parser.add_argument('--port', '-p', type=int, default=8585)
    args = parser.parse_args()

    if os.geteuid() != 0:
        print('Must run as root (sudo).')
        sys.exit(1)

    devices = find_k585_devices()
    if not devices:
        print('No K585 found! Is it plugged in?')
        sys.exit(1)

    print(f'Found {len(devices)} K585 device(s):')
    for dev in devices:
        print(f'  {dev.path}  {dev.name}')

    # start evdev reader thread
    reader = threading.Thread(target=evdev_reader, args=(devices,), daemon=True)
    reader.start()

    # start HTTP server in a thread so main thread can handle signals
    server = HTTPServer(('0.0.0.0', args.port), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f'\nUI ready: http://localhost:{args.port}')
    print('Press Ctrl+C or type "q" to stop.\n')

    def shutdown(*_):
        print('\nShutting down...')
        server.shutdown()
        os._exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # main thread just waits for 'q' input
    try:
        while True:
            line = input()
            if line.strip().lower() in ('q', 'quit', 'exit'):
                shutdown()
    except (EOFError, KeyboardInterrupt):
        shutdown()


if __name__ == '__main__':
    main()
