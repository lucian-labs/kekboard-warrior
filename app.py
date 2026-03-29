#!/usr/bin/env python3
"""
K585 Keyboard Translator — Native GTK3 App

Modes:
  - Discover: monitor all K585 inputs, visualize key presses
  - Translate: grab keyboard, remap keys through chord layers

Usage:
    sudo python3 app.py
"""

import json
import os
import selectors
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

import evdev
from evdev import InputDevice, UInput, ecodes, categorize

from engine import TranslationEngine

VENDOR = 0x320f
PRODUCT = 0x5000
APP_DIR = Path(__file__).parent
KEYMAP_FILE = APP_DIR / 'keymap.json'
MAP_FILE = APP_DIR / 'discovered-keys.json'

# K585 DITI physical layout — maps (row, col) to evdev key name
# and display label
K585_LAYOUT = {
    'g_column': [
        ('KEY_F5', 'G5'),
        ('KEY_F4', 'G4'),
        ('KEY_F3', 'G3'),
        ('KEY_F2', 'G2'),
        ('KEY_F1', 'G1'),
    ],
    'm_row': [
        (None, 'M1'), (None, 'M2'), (None, 'M3'), (None, 'M4'), (None, 'REC'),
    ],
    'f_row': [
        ('KEY_F6', 'F1'), ('KEY_F7', 'F2'), ('KEY_F8', 'F3'), ('KEY_F9', 'F4'), ('KEY_F10', 'Fn'),
    ],
    'rows': [
        [('KEY_ESC', 'Esc'), ('KEY_1', '1'), ('KEY_2', '2'), ('KEY_3', '3'),
         ('KEY_4', '4'), ('KEY_5', '5'), ('KEY_6', '6')],
        [('KEY_TAB', 'Tab', 1.3), ('KEY_Q', 'Q'), ('KEY_W', 'W'), ('KEY_E', 'E'),
         ('KEY_R', 'R'), ('KEY_T', 'T')],
        [('KEY_CAPSLOCK', 'Caps', 1.5), ('KEY_A', 'A'), ('KEY_S', 'S'), ('KEY_D', 'D'),
         ('KEY_F', 'F'), ('KEY_G', 'G')],
        [('KEY_LEFTSHIFT', 'Shift', 1.8), ('KEY_Z', 'Z'), ('KEY_X', 'X'), ('KEY_C', 'C'),
         ('KEY_V', 'V'), ('KEY_B', 'B')],
        [('KEY_LEFTCTRL', 'Ctrl', 1.3), ('KEY_LEFTALT', 'Alt', 1.3), ('KEY_SPACE', 'Space', 3.0)],
    ],
    'extra': [
        ('KEY_GRAVE', '`'), ('KEY_N', 'N'), ('KEY_M', 'M'), ('KEY_P', 'P'),
        ('KEY_Y', 'Y'), ('KEY_U', 'U'), ('KEY_I', 'I'), ('KEY_O', 'O'),
        ('KEY_BACKSPACE', 'Bksp'), ('KEY_ENTER', 'Enter'),
        ('KEY_UP', 'Up'), ('KEY_DOWN', 'Dn'), ('KEY_LEFT', 'Lt'), ('KEY_RIGHT', 'Rt'),
    ],
}

# colors
COL_BG = '#0a0a0f'
COL_KEY_BG = '#141420'
COL_KEY_BORDER = '#2a2a3a'
COL_KEY_TEXT = '#555555'
COL_DISCOVERED = '#0a2a1a'
COL_DISCOVERED_BORDER = '#1a6a3a'
COL_DISCOVERED_TEXT = '#4aea8a'
COL_ACTIVE = '#1a4a2a'
COL_ACTIVE_BORDER = '#4aea8a'
COL_G_BG = '#1a1025'
COL_G_BORDER = '#3a2a4a'
COL_G_DISCOVERED = '#2a1a3a'
COL_G_DISCOVERED_BORDER = '#8a4aea'
COL_G_TEXT = '#c09af8'
COL_G_ACTIVE = '#3a2a5a'
COL_UNKNOWN = '#eaaa4a'
COL_M_BG = '#1a1a1a'


def find_k585_devices():
    devices = []
    for path in evdev.list_devices():
        dev = InputDevice(path)
        if dev.info.vendor == VENDOR and dev.info.product == PRODUCT:
            caps = dev.capabilities(verbose=False)
            if ecodes.EV_KEY in caps or ecodes.EV_REL in caps:
                devices.append(dev)
    return devices


class KeyButton(Gtk.DrawingArea):
    """A single key on the visual keyboard."""

    def __init__(self, key_name, label, width=44, is_g=False, is_m=False):
        super().__init__()
        self.key_name = key_name
        self.label = label
        self.is_g = is_g
        self.is_m = is_m
        self.discovered = False
        self.active = False
        self.press_count = 0

        self.set_size_request(width, 38)
        self.connect('draw', self.on_draw)

    def on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()

        # pick colors
        if self.active:
            if self.is_g:
                bg, border, text = COL_G_ACTIVE, COL_ACTIVE_BORDER, '#ffffff'
            else:
                bg, border, text = COL_ACTIVE, COL_ACTIVE_BORDER, '#ffffff'
        elif self.discovered:
            if self.is_g:
                bg, border, text = COL_G_DISCOVERED, COL_G_DISCOVERED_BORDER, COL_G_TEXT
            else:
                bg, border, text = COL_DISCOVERED, COL_DISCOVERED_BORDER, COL_DISCOVERED_TEXT
        elif self.is_g:
            bg, border, text = COL_G_BG, COL_G_BORDER, COL_KEY_TEXT
        elif self.is_m:
            bg, border, text = COL_M_BG, COL_KEY_BORDER, '#333333'
        else:
            bg, border, text = COL_KEY_BG, COL_KEY_BORDER, COL_KEY_TEXT

        # background
        r, g, b = self._hex_to_rgb(bg)
        cr.set_source_rgb(r, g, b)
        self._rounded_rect(cr, 1, 1, w - 2, h - 2, 4)
        cr.fill()

        # border
        r, g, b = self._hex_to_rgb(border)
        cr.set_source_rgb(r, g, b)
        self._rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 4)
        cr.set_line_width(1)
        cr.stroke()

        # label
        r, g, b = self._hex_to_rgb(text)
        cr.set_source_rgb(r, g, b)
        cr.select_font_face('monospace', 0, 0)
        cr.set_font_size(10)
        extents = cr.text_extents(self.label)
        cr.move_to((w - extents.width) / 2, (h + extents.height) / 2)
        cr.show_text(self.label)

        # press count
        if self.press_count > 0:
            count_text = str(self.press_count)
            cr.set_font_size(7)
            r, g, b = self._hex_to_rgb('#4a8a5a' if not self.is_g else '#7a5aaa')
            cr.set_source_rgb(r, g, b)
            extents = cr.text_extents(count_text)
            cr.move_to(w - extents.width - 3, 10)
            cr.show_text(count_text)

    def _rounded_rect(self, cr, x, y, w, h, r):
        import math
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _hex_to_rgb(self, hex_color):
        h = hex_color.lstrip('#')
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def set_active(self, active):
        self.active = active
        if active and not self.discovered:
            self.discovered = True
        if active:
            self.press_count += 1
        self.queue_draw()

    def reset(self):
        self.discovered = False
        self.active = False
        self.press_count = 0
        self.queue_draw()


class TranslatorApp(Gtk.Window):

    def __init__(self):
        super().__init__(title='K585 Keyboard Translator')
        self.set_default_size(750, 620)
        self.set_resizable(True)

        # dark theme
        settings = Gtk.Settings.get_default()
        settings.set_property('gtk-application-prefer-dark-theme', True)

        # override bg
        css = Gtk.CssProvider()
        css.load_from_data(f'''
            window {{ background-color: {COL_BG}; }}
            textview, textview text {{ background-color: #0f0f18; color: #888; font-family: monospace; font-size: 10px; }}
            label {{ color: #c0c0c0; }}
            button {{ background: #1a1a2e; border: 1px solid #333; color: #aaa; }}
            button:hover {{ background: #252545; color: #fff; }}
        '''.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.key_buttons = {}  # evdev key name -> KeyButton
        self.unknown_keys = {}
        self.total_events = 0
        self.devices = []
        self.running = False
        self.translate_mode = False
        self.ui_output = None
        self.engine = None

        self._build_ui()
        self._find_devices()

    def _build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self.add(vbox)

        # header
        title = Gtk.Label()
        title.set_markup('<span font="14" weight="bold" foreground="#e0e0e0">K585 DITI — Keyboard Translator</span>')
        title.set_halign(Gtk.Align.START)
        vbox.pack_start(title, False, False, 0)

        self.status_label = Gtk.Label()
        self.status_label.set_markup('<span foreground="#666" font="9">not connected</span>')
        self.status_label.set_halign(Gtk.Align.START)
        vbox.pack_start(self.status_label, False, False, 0)

        # toolbar
        toolbar = Gtk.Box(spacing=8)
        toolbar.set_margin_top(4)

        self.discover_btn = Gtk.Button(label='Discover')
        self.discover_btn.connect('clicked', self.on_discover)
        toolbar.pack_start(self.discover_btn, False, False, 0)

        self.translate_btn = Gtk.Button(label='Translate')
        self.translate_btn.connect('clicked', self.on_translate)
        toolbar.pack_start(self.translate_btn, False, False, 0)

        self.stop_btn = Gtk.Button(label='Stop')
        self.stop_btn.connect('clicked', self.on_stop)
        self.stop_btn.set_sensitive(False)
        toolbar.pack_start(self.stop_btn, False, False, 0)

        clear_btn = Gtk.Button(label='Clear')
        clear_btn.connect('clicked', self.on_clear)
        toolbar.pack_start(clear_btn, False, False, 0)

        save_btn = Gtk.Button(label='Save Map')
        save_btn.connect('clicked', self.on_save)
        toolbar.pack_start(save_btn, False, False, 0)

        self.stats_label = Gtk.Label()
        self.stats_label.set_markup('<span foreground="#666" font="9">keys: 0  unknown: 0  events: 0</span>')
        self.stats_label.set_halign(Gtk.Align.END)
        toolbar.pack_end(self.stats_label, False, False, 0)

        vbox.pack_start(toolbar, False, False, 0)

        # keyboard layout
        kb_frame = Gtk.Frame()
        kb_frame.set_shadow_type(Gtk.ShadowType.NONE)
        kb_box = Gtk.Box(spacing=4)
        kb_box.set_margin_top(8)

        # G column
        g_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        g_col.set_margin_top(30)
        for key_name, label in K585_LAYOUT['g_column']:
            btn = KeyButton(key_name, label, width=40, is_g=True)
            g_col.pack_start(btn, False, False, 0)
            if key_name:
                self.key_buttons[key_name] = btn
        kb_box.pack_start(g_col, False, False, 0)

        # main area
        main_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        # M row
        m_row = Gtk.Box(spacing=3)
        for key_name, label in K585_LAYOUT['m_row']:
            btn = KeyButton(key_name, label, width=36, is_m=True)
            m_row.pack_start(btn, False, False, 0)
            if key_name:
                self.key_buttons[key_name] = btn
        main_area.pack_start(m_row, False, False, 0)

        # F row
        f_row = Gtk.Box(spacing=3)
        for entry in K585_LAYOUT['f_row']:
            key_name, label = entry[0], entry[1]
            btn = KeyButton(key_name, label, width=36)
            f_row.pack_start(btn, False, False, 0)
            if key_name:
                self.key_buttons[key_name] = btn
        main_area.pack_start(f_row, False, False, 0)

        # main rows
        for row_data in K585_LAYOUT['rows']:
            row_box = Gtk.Box(spacing=3)
            for entry in row_data:
                key_name = entry[0]
                label = entry[1]
                width = int(entry[2] * 44) if len(entry) > 2 else 44
                btn = KeyButton(key_name, label, width=width)
                row_box.pack_start(btn, False, False, 0)
                self.key_buttons[key_name] = btn
            main_area.pack_start(row_box, False, False, 0)

        kb_box.pack_start(main_area, False, False, 0)

        # extra keys (right side / unmapped area)
        extra_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        extra_box.set_margin_start(12)
        extra_box.set_margin_top(30)
        extra_label = Gtk.Label()
        extra_label.set_markup('<span foreground="#444" font="8">extra</span>')
        extra_box.pack_start(extra_label, False, False, 2)

        extra_grid = Gtk.FlowBox()
        extra_grid.set_max_children_per_line(4)
        extra_grid.set_min_children_per_line(2)
        extra_grid.set_row_spacing(3)
        extra_grid.set_column_spacing(3)
        extra_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        for key_name, label in K585_LAYOUT['extra']:
            btn = KeyButton(key_name, label, width=44)
            extra_grid.add(btn)
            self.key_buttons[key_name] = btn
        extra_box.pack_start(extra_grid, False, False, 0)

        kb_box.pack_start(extra_box, False, False, 0)
        kb_frame.add(kb_box)
        vbox.pack_start(kb_frame, False, False, 0)

        # bottom panels
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_margin_top(8)

        # unknown keys panel
        unknown_frame = Gtk.Frame()
        unknown_frame.set_shadow_type(Gtk.ShadowType.NONE)
        unknown_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        unknown_title = Gtk.Label()
        unknown_title.set_markup(f'<span foreground="{COL_UNKNOWN}" font="9" weight="bold">Unknown Keys</span>')
        unknown_title.set_halign(Gtk.Align.START)
        unknown_box.pack_start(unknown_title, False, False, 0)

        self.unknown_list = Gtk.ListBox()
        self.unknown_list.set_selection_mode(Gtk.SelectionMode.NONE)
        unknown_scroll = Gtk.ScrolledWindow()
        unknown_scroll.set_min_content_height(120)
        unknown_scroll.add(self.unknown_list)
        unknown_box.pack_start(unknown_scroll, True, True, 0)
        unknown_frame.add(unknown_box)
        paned.pack1(unknown_frame, True, True)

        # event log
        log_frame = Gtk.Frame()
        log_frame.set_shadow_type(Gtk.ShadowType.NONE)
        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        log_title = Gtk.Label()
        log_title.set_markup(f'<span foreground="{COL_DISCOVERED_TEXT}" font="9" weight="bold">Event Log</span>')
        log_title.set_halign(Gtk.Align.START)
        log_box.pack_start(log_title, False, False, 0)

        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.NONE)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(120)
        log_scroll.add(self.log_view)
        log_box.pack_start(log_scroll, True, True, 0)
        log_frame.add(log_box)
        paned.pack2(log_frame, True, True)

        paned.set_position(300)
        vbox.pack_start(paned, True, True, 0)

        # layer indicator
        self.layer_label = Gtk.Label()
        self.layer_label.set_markup('<span foreground="#444" font="9">layer: base</span>')
        self.layer_label.set_halign(Gtk.Align.START)
        vbox.pack_start(self.layer_label, False, False, 0)

    def _find_devices(self):
        try:
            self.devices = find_k585_devices()
            if self.devices:
                names = ', '.join(d.path.split('/')[-1] for d in self.devices)
                self.status_label.set_markup(
                    f'<span foreground="#4aea8a" font="9">connected — {len(self.devices)} device(s): {names}</span>')
            else:
                self.status_label.set_markup(
                    '<span foreground="#ea4a4a" font="9">K585 not found — is it plugged in?</span>')
        except Exception as e:
            self.status_label.set_markup(
                f'<span foreground="#ea4a4a" font="9">error: {e} — run with sudo</span>')

    def _add_log(self, text, color=None):
        color = color or '#888'
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + '\n')
        # trim to last 200 lines
        line_count = self.log_buffer.get_line_count()
        if line_count > 200:
            start = self.log_buffer.get_start_iter()
            cut = self.log_buffer.get_iter_at_line(line_count - 200)
            self.log_buffer.delete(start, cut)
        # scroll to bottom
        end = self.log_buffer.get_end_iter()
        self.log_view.scroll_to_iter(end, 0, False, 0, 0)

    def _update_stats(self):
        known = sum(1 for b in self.key_buttons.values() if b.discovered)
        unknown = len(self.unknown_keys)
        self.stats_label.set_markup(
            f'<span foreground="#666" font="9">keys: {known}  unknown: {unknown}  events: {self.total_events}</span>')

    def _add_unknown(self, name, code, device):
        key = f'{name}_{code}'
        if key in self.unknown_keys:
            self.unknown_keys[key]['count'] += 1
            lbl = self.unknown_keys[key]['label']
            lbl.set_markup(
                f'<span foreground="{COL_UNKNOWN}" font="9">{name}</span>'
                f'  <span foreground="#666" font="8">code={code} · {device} · x{self.unknown_keys[key]["count"]}</span>')
            return

        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=8)
        lbl = Gtk.Label()
        lbl.set_markup(
            f'<span foreground="{COL_UNKNOWN}" font="9">{name}</span>'
            f'  <span foreground="#666" font="8">code={code} · {device} · x1</span>')
        lbl.set_halign(Gtk.Align.START)
        box.pack_start(lbl, True, True, 4)
        row.add(box)
        row.show_all()
        self.unknown_list.add(row)
        self.unknown_keys[key] = {'count': 1, 'label': lbl}

    def _process_event(self, event, dev_path):
        """Called from reader thread via GLib.idle_add."""
        self.total_events += 1
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        dev_short = dev_path.split('/')[-1]

        if event.type == ecodes.EV_KEY:
            key_event = categorize(event)
            name = key_event.keycode
            if isinstance(name, list):
                name = name[0]
            state = {0: 'UP', 1: 'DOWN', 2: 'HOLD'}.get(event.value, '?')
            is_down = event.value == 1

            if self.translate_mode and self.engine:
                outputs = self.engine.process_key(event.code, event.value)
                for out_code, out_value in outputs:
                    if self.ui_output:
                        self.ui_output.write(ecodes.EV_KEY, out_code, out_value)
                        self.ui_output.syn()
                status = self.engine.get_status()
                self.layer_label.set_markup(
                    f'<span foreground="#4aea8a" font="9">layer: {status["layer_name"]}</span>')

            # update visual
            if name in self.key_buttons:
                self.key_buttons[name].set_active(is_down)
            elif is_down:
                self._add_unknown(name, event.code, dev_short)

            self._add_log(f'{ts}  {state:4s}  {name:25s}  {dev_short}')

        elif event.type == ecodes.EV_REL:
            axis = ecodes.REL.get(event.code, f'REL_{event.code}')
            self._add_unknown(str(axis), event.code, dev_short)
            self._add_log(f'{ts}  REL   {axis}  val={event.value}  {dev_short}')

        self._update_stats()

    def _reader_thread(self, grab=False):
        """Background thread reading evdev events."""
        sel = selectors.DefaultSelector()
        for dev in self.devices:
            sel.register(dev, selectors.EVENT_READ)
            if grab:
                try:
                    dev.grab()
                    GLib.idle_add(self._add_log, f'Grabbed {dev.path}')
                except Exception as e:
                    GLib.idle_add(self._add_log, f'Grab failed {dev.path}: {e}')

        while self.running:
            try:
                for key, _ in sel.select(timeout=0.5):
                    if not self.running:
                        break
                    dev = key.fileobj
                    for event in dev.read():
                        GLib.idle_add(self._process_event, event, dev.path)
            except Exception as e:
                if self.running:
                    GLib.idle_add(self._add_log, f'Reader error: {e}')
                    time.sleep(0.1)

        if grab:
            for dev in self.devices:
                try:
                    dev.ungrab()
                except Exception:
                    pass

        sel.close()

    def on_discover(self, btn):
        if not self.devices:
            self._find_devices()
            if not self.devices:
                return
        self.running = True
        self.translate_mode = False
        self.discover_btn.set_sensitive(False)
        self.translate_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self._add_log('Discover mode — press keys on K585')
        self.layer_label.set_markup('<span foreground="#666" font="9">mode: discover</span>')
        t = threading.Thread(target=self._reader_thread, args=(False,), daemon=True)
        t.start()

    def on_translate(self, btn):
        if not self.devices:
            self._find_devices()
            if not self.devices:
                return
        # load engine
        try:
            self.engine = TranslationEngine(str(KEYMAP_FILE))
        except Exception as e:
            self._add_log(f'Failed to load keymap: {e}')
            return

        # create uinput
        all_keys = set()
        for dev in self.devices:
            caps = dev.capabilities(verbose=False)
            if ecodes.EV_KEY in caps:
                all_keys.update(caps[ecodes.EV_KEY])
        self.ui_output = UInput({ecodes.EV_KEY: list(all_keys)}, name='KeyTranslator Virtual Keyboard')

        self.running = True
        self.translate_mode = True
        self.discover_btn.set_sensitive(False)
        self.translate_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        status = self.engine.get_status()
        self._add_log(f'Translate mode — layer: {status["layer_name"]}')
        self.layer_label.set_markup(
            f'<span foreground="#4aea8a" font="9">layer: {status["layer_name"]} (translating)</span>')
        t = threading.Thread(target=self._reader_thread, args=(True,), daemon=True)
        t.start()

    def on_stop(self, btn):
        self.running = False
        self.translate_mode = False
        if self.ui_output:
            try:
                self.ui_output.close()
            except Exception:
                pass
            self.ui_output = None
        self.engine = None
        self.discover_btn.set_sensitive(True)
        self.translate_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self._add_log('Stopped.')
        self.layer_label.set_markup('<span foreground="#444" font="9">stopped</span>')
        # re-find devices (they may have changed after ungrab)
        self._find_devices()

    def on_clear(self, btn):
        for b in self.key_buttons.values():
            b.reset()
        self.unknown_keys.clear()
        for row in self.unknown_list.get_children():
            self.unknown_list.remove(row)
        self.log_buffer.set_text('')
        self.total_events = 0
        self._update_stats()

    def on_save(self, btn):
        output = {
            'device': 'Redragon K585 DITI',
            'vendor_id': hex(VENDOR),
            'product_id': hex(PRODUCT),
            'discovered_at': datetime.now().isoformat(),
            'keys': {},
            'unknown': {},
        }
        for key_name, btn in self.key_buttons.items():
            if btn.discovered and key_name:
                code = ecodes.ecodes.get(key_name)
                output['keys'][key_name] = {
                    'code': code,
                    'press_count': btn.press_count,
                }
        for uk, info in self.unknown_keys.items():
            output['unknown'][uk] = {'count': info['count']}

        with open(MAP_FILE, 'w') as f:
            json.dump(output, f, indent=2)
        self._add_log(f'Saved to {MAP_FILE}')


def main():
    if os.geteuid() != 0:
        print('Must run as root (sudo) for evdev access.')
        print('  sudo python3 app.py')
        sys.exit(1)

    app = TranslatorApp()
    app.connect('destroy', Gtk.main_quit)
    app.show_all()

    signal.signal(signal.SIGINT, signal.SIG_DFL)  # let Ctrl+C work
    Gtk.main()


if __name__ == '__main__':
    main()
