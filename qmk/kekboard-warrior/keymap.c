// Corne v4 — All Joystick Buttons
// Firmware: crkbd/rev4_0/standard
// Layout:  LAYOUT_split_3x6_3_ex2

#include QMK_KEYBOARD_H

// clang-format off
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [0] = LAYOUT_split_3x6_3_ex2(
        // [ 0- 6] Left: row0(6) + ex1
            JS_7,  JS_6,  JS_5,  JS_4,  JS_3,  JS_2,  JS_0,
        // [ 7-13] Right: ex1, row0
            JS_0,  JS_2,  JS_3,  JS_4,  JS_5,  JS_6,  JS_7,
        // [14-20] Left: row1(6) + ex2
            JS_13, JS_12, JS_11, JS_10, JS_9,  JS_8,  JS_1,
        // [21-27] Right: ex2, row1
            JS_1,  JS_8,  JS_9,  JS_10, JS_11, JS_12, JS_13,
        // [28-33] Left: row2(6)
            JS_19, JS_18, JS_17, JS_16, JS_15, JS_14,
        // [34-39] Right: row2
            JS_14, JS_15, JS_16, JS_17, JS_18, JS_19,
        // [40-42] Left: thumb
            JS_22, JS_21, JS_20,
        // [43-45] Right: thumb
            JS_20, JS_21, JS_22
    ),
};
// clang-format on
