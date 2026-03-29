import json
import time
from evdev import ecodes


class TranslationEngine:
    def __init__(self, keymap_path):
        with open(keymap_path) as f:
            self.config = json.load(f)

        self.layers = self.config['layers']
        self.hold_threshold = self.config.get('hold_threshold_ms', 150) / 1000.0
        self.macros = self.config.get('macros', {})

        # chord keys: map evdev key name -> layer index
        # e.g. {"KEY_F13": 1, "KEY_F14": 2}
        self.chord_keys = self.config.get('chord_keys', {})
        self.chord_key_codes = {}
        for key_name, layer_idx in self.chord_keys.items():
            code = ecodes.ecodes.get(key_name)
            if code is not None:
                self.chord_key_codes[code] = layer_idx

        # build compiled keymaps: layer_index -> {input_code: output_code}
        self.compiled_layers = []
        for layer in self.layers:
            compiled = {}
            for in_name, out_name in layer.get('map', {}).items():
                in_code = ecodes.ecodes.get(in_name)
                out_code = ecodes.ecodes.get(out_name)
                if in_code is not None and out_code is not None:
                    compiled[in_code] = out_code
            self.compiled_layers.append(compiled)

        # runtime state
        self.active_layer = 0
        self.chord_state = set()  # set of held chord key codes
        self.held_keys = {}  # code -> timestamp (for tap-hold detection)

    def resolve_layer(self):
        """Determine active layer from chord state."""
        if self.chord_state:
            # use the highest-priority chord key's layer
            # for multi-chord combos, we could do bitmask lookup later
            for code in self.chord_state:
                return self.chord_key_codes[code]
        return 0  # base layer

    def process_key(self, code, value):
        """Process a key event. Returns list of (code, value) pairs to emit.

        value: 1 = press, 0 = release, 2 = repeat
        """
        # check if this is a chord modifier key
        if code in self.chord_key_codes:
            if value == 1:
                self.chord_state.add(code)
                self.active_layer = self.resolve_layer()
            elif value == 0:
                self.chord_state.discard(code)
                self.active_layer = self.resolve_layer()
            # chord keys are consumed — not passed through
            return []

        # translate through active layer, fall back to base, fall back to passthrough
        layer = self.compiled_layers[self.active_layer] if self.active_layer < len(self.compiled_layers) else {}
        base = self.compiled_layers[0] if self.compiled_layers else {}

        if code in layer:
            out_code = layer[code]
        elif self.active_layer != 0 and code in base:
            out_code = base[code]
        else:
            out_code = code  # passthrough

        # check for macro trigger
        macro_key = None
        for key_name, macro_code in [(k, ecodes.ecodes.get(k)) for k in self.macros]:
            if macro_code == out_code:
                macro_key = key_name
                break

        if macro_key and value == 1:
            return self._expand_macro(self.macros[macro_key])

        return [(out_code, value)]

    def _expand_macro(self, macro_def):
        """Expand a macro definition into key events.

        macro_def can be:
        - a string: typed as keystrokes
        - a list of {"key": "KEY_X", "value": 1/0} for explicit sequences
        """
        events = []
        if isinstance(macro_def, str):
            for char in macro_def:
                key_name = self._char_to_key(char)
                code = ecodes.ecodes.get(key_name)
                if code is not None:
                    events.append((code, 1))
                    events.append((code, 0))
        elif isinstance(macro_def, list):
            for step in macro_def:
                code = ecodes.ecodes.get(step['key'])
                if code is not None:
                    events.append((code, step['value']))
        return events

    def _char_to_key(self, char):
        """Map a character to an evdev key name."""
        char_map = {
            '\n': 'KEY_ENTER',
            ' ': 'KEY_SPACE',
            '\t': 'KEY_TAB',
            '-': 'KEY_MINUS',
            '=': 'KEY_EQUAL',
            '[': 'KEY_LEFTBRACE',
            ']': 'KEY_RIGHTBRACE',
            '\\': 'KEY_BACKSLASH',
            ';': 'KEY_SEMICOLON',
            "'": 'KEY_APOSTROPHE',
            ',': 'KEY_COMMA',
            '.': 'KEY_DOT',
            '/': 'KEY_SLASH',
            '`': 'KEY_GRAVE',
        }
        if char in char_map:
            return char_map[char]
        if char.isalpha():
            return f'KEY_{char.upper()}'
        if char.isdigit():
            return f'KEY_{char}'
        return 'KEY_SPACE'  # fallback

    def get_status(self):
        """Return current engine status for display."""
        layer_name = self.layers[self.active_layer]['name'] if self.active_layer < len(self.layers) else '???'
        return {
            'layer': self.active_layer,
            'layer_name': layer_name,
            'chord_keys_held': len(self.chord_state),
        }
