// Corne v4 Right Half — All Joystick Buttons
// Firmware: crkbd/rev4_0/standard
// Layout:  LAYOUT_split_3x6_3_ex2
//
// Flash with:
//   qmk flash -kb crkbd/rev4_0/standard -km kekboard-warrior
//
// The right half sends JS_BUTTON0–JS_BUTTON22.
// The left half is KC_NO (unused / separate device).

#include QMK_KEYBOARD_H

// clang-format off
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [0] = LAYOUT_split_3x6_3_ex2(
        // ── Left half (unused — will be its own device) ──
        //  ex1    ex2
            KC_NO, KC_NO,
        //  row0
            KC_NO, KC_NO, KC_NO, KC_NO, KC_NO, KC_NO,
        //  row1
            KC_NO, KC_NO, KC_NO, KC_NO, KC_NO, KC_NO,
        //  row2
            KC_NO, KC_NO, KC_NO, KC_NO, KC_NO, KC_NO,
        //  thumb
                           KC_NO, KC_NO, KC_NO,

        // ── Right half — joystick buttons ──
        //  ex1          ex2
            JS_BUTTON0,  JS_BUTTON1,
        //  row0
            JS_BUTTON2,  JS_BUTTON3,  JS_BUTTON4,  JS_BUTTON5,  JS_BUTTON6,  JS_BUTTON7,
        //  row1
            JS_BUTTON8,  JS_BUTTON9,  JS_BUTTON10, JS_BUTTON11, JS_BUTTON12, JS_BUTTON13,
        //  row2
            JS_BUTTON14, JS_BUTTON15, JS_BUTTON16, JS_BUTTON17, JS_BUTTON18, JS_BUTTON19,
        //  thumb
                           JS_BUTTON20, JS_BUTTON21, JS_BUTTON22
    ),
};
// clang-format on
