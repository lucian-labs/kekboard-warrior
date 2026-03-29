# Kekboard Warrior

Mapping for HONOR. Custom keyboard remapping and firmware toolkit.

## Devices

### Corne Choc v4 (Right Half) — Joystick Mode

Standalone right half of a Corne v4 flashed as a 23-button joystick. All keys send `JS_BUTTON0`–`JS_BUTTON22`. Chord mapping is handled on the software side.

```
[JS0] [JS1]                          <- extra keys (stacked left)
[JS2]  [JS3]  [JS4]  [JS5]  [JS6]  [JS7]    <- row 0
[JS8]  [JS9]  [JS10] [JS11] [JS12] [JS13]   <- row 1
[JS14] [JS15] [JS16] [JS17] [JS18] [JS19]   <- row 2
              [JS20] [JS21] [JS22]           <- thumb cluster
```

**Board:** `crkbd/rev4_0/standard` — `LAYOUT_split_3x6_3_ex2`
**QMK Configurator:** https://config.qmk.fm/#/crkbd/rev4_0/standard/LAYOUT_split_3x6_3_ex2

#### Flash

```bash
# copy keymap into QMK tree
cp -r qmk/kekboard-warrior ~/qmk_firmware/keyboards/crkbd/rev4_0/standard/keymaps/

# flash (put board in bootloader: double-tap reset)
qmk flash -kb crkbd/rev4_0/standard -km kekboard-warrior
```

### Redragon K585 DITI

Evdev-based key discovery and translation for the K585 one-handed gaming keyboard. Supports chord layers and macro expansion via `keymap.json`.

```bash
sudo python3 app.py         # GTK3 UI
sudo python3 ui.py           # web UI (localhost:8585)
sudo python3 translator.py scan       # list devices
sudo python3 translator.py discover   # discover key codes
sudo python3 translator.py run        # run translation
```

## Web UI

Open `ui.html` in a browser to visualize either device. Use the dropdown to switch between Corne and K585 layouts.

## Requirements

- Python 3, python3-evdev, GTK3 (for K585 tools)
- QMK CLI (for Corne firmware)
