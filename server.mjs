import { createServer } from 'http'
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from 'fs'
import { join, extname } from 'path'
import { fileURLToPath } from 'url'
import { dirname } from 'path'
import { execSync } from 'child_process'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PORT = process.env.PORT || 3333
const CONFIG_DIR = join(__dirname, 'config')
const QMK_DIR = join(__dirname, 'qmk')
const QMK_FIRMWARE = process.env.QMK_FIRMWARE || join(process.env.HOME, 'qmk_firmware')

const MIME = {
  '.html': 'text/html', '.js': 'application/javascript', '.mjs': 'application/javascript',
  '.json': 'application/json', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml',
}

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.setHeader('Access-Control-Allow-Methods', 'GET, PUT, POST, OPTIONS')
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
}

function json(res, data, status = 200) {
  cors(res)
  res.writeHead(status, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify(data))
}

function readBody(req) {
  return new Promise(resolve => {
    let body = ''
    req.on('data', c => body += c)
    req.on('end', () => resolve(body))
  })
}

// ── keymap.c generator ──

// Map user-friendly action strings to QMK keycodes
const ACTION_TO_QMK = {
  // letters
  ...Object.fromEntries('abcdefghijklmnopqrstuvwxyz'.split('').map(c => [c, `KC_${c.toUpperCase()}`])),
  // numbers
  ...Object.fromEntries('0123456789'.split('').map(c => [c, `KC_${c}`])),
  // arrows
  up: 'KC_UP', down: 'KC_DOWN', left: 'KC_LEFT', right: 'KC_RIGHT',
  // nav
  home: 'KC_HOME', end: 'KC_END', pgup: 'KC_PAGE_UP', pgdn: 'KC_PAGE_DOWN',
  pageup: 'KC_PAGE_UP', pagedown: 'KC_PAGE_DOWN',
  // common
  enter: 'KC_ENTER', return: 'KC_ENTER', esc: 'KC_ESCAPE', escape: 'KC_ESCAPE',
  space: 'KC_SPACE', tab: 'KC_TAB', backspace: 'KC_BACKSPACE', delete: 'KC_DELETE',
  del: 'KC_DELETE', insert: 'KC_INSERT', ins: 'KC_INSERT',
  capslock: 'KC_CAPS_LOCK', caps: 'KC_CAPS_LOCK',
  printscreen: 'KC_PRINT_SCREEN', prtsc: 'KC_PRINT_SCREEN',
  scrolllock: 'KC_SCROLL_LOCK', pause: 'KC_PAUSE',
  // punctuation
  '-': 'KC_MINUS', minus: 'KC_MINUS',
  '=': 'KC_EQUAL', equal: 'KC_EQUAL', equals: 'KC_EQUAL',
  '[': 'KC_LEFT_BRACKET', lbracket: 'KC_LEFT_BRACKET',
  ']': 'KC_RIGHT_BRACKET', rbracket: 'KC_RIGHT_BRACKET',
  '\\': 'KC_BACKSLASH', backslash: 'KC_BACKSLASH',
  ';': 'KC_SEMICOLON', semicolon: 'KC_SEMICOLON',
  "'": 'KC_QUOTE', quote: 'KC_QUOTE',
  '`': 'KC_GRAVE', grave: 'KC_GRAVE',
  ',': 'KC_COMMA', comma: 'KC_COMMA',
  '.': 'KC_DOT', dot: 'KC_DOT', period: 'KC_DOT',
  '/': 'KC_SLASH', slash: 'KC_SLASH',
  // function keys
  ...Object.fromEntries(Array.from({length: 24}, (_, i) => [`f${i+1}`, `KC_F${i+1}`])),
  // modifiers
  lctrl: 'KC_LEFT_CTRL', lshift: 'KC_LEFT_SHIFT', lalt: 'KC_LEFT_ALT', lgui: 'KC_LEFT_GUI',
  rctrl: 'KC_RIGHT_CTRL', rshift: 'KC_RIGHT_SHIFT', ralt: 'KC_RIGHT_ALT', rgui: 'KC_RIGHT_GUI',
  ctrl: 'KC_LEFT_CTRL', shift: 'KC_LEFT_SHIFT', alt: 'KC_LEFT_ALT', gui: 'KC_LEFT_GUI',
  // media
  play: 'KC_MEDIA_PLAY_PAUSE', playpause: 'KC_MEDIA_PLAY_PAUSE',
  stop: 'KC_MEDIA_STOP', next: 'KC_MEDIA_NEXT_TRACK', prev: 'KC_MEDIA_PREV_TRACK',
  volup: 'KC_AUDIO_VOL_UP', voldown: 'KC_AUDIO_VOL_DOWN', mute: 'KC_AUDIO_MUTE',
  // mouse
  mouse1: 'MS_BTN1', mouse2: 'MS_BTN2', mouse3: 'MS_BTN3',
  // special
  boot: 'QK_BOOT', bootloader: 'QK_BOOT', reboot: 'QK_REBOOT',
}

function actionToQMK(type, action) {
  if (!type || type === 'none') return 'KC_NO'
  if (type === 'transparent') return 'KC_TRNS'
  if (type === 'bootloader') return 'QK_BOOT'

  const act = (action || '').trim()

  // layer types — strip wrapper if user typed "TG(0)" instead of just "0"
  const layerNum = act.match(/^(?:MO|TG|OSL)\((\d+)\)$/) ? act.match(/\((\d+)\)/)[1] : act
  if (type === 'layer_mo') return `MO(${layerNum})`
  if (type === 'layer_tg') return `TG(${layerNum})`
  if (type === 'oneshot_layer') return `OSL(${layerNum})`
  if (type === 'layer_tap') {
    // action format: "layer,keycode" e.g. "1,KC_SPC" or "1,space"
    const parts = act.split(',').map(s => s.trim())
    const layer = parts[0]
    const kc = parts[1] ? resolveKeycode(parts[1]) : 'KC_NO'
    return `LT(${layer},${kc})`
  }
  if (type === 'mod_tap') {
    // action format: "mod,keycode" e.g. "LCTL,KC_A" or "ctrl,a"
    const parts = act.split(',').map(s => s.trim())
    const mod = resolveModPrefix(parts[0])
    const kc = parts[1] ? resolveKeycode(parts[1]) : 'KC_NO'
    return `${mod}_T(${kc})`
  }
  if (type === 'oneshot_mod') {
    const mod = resolveModPrefix(act)
    return `OSM(MOD_${mod.replace('KC_', '').replace('LEFT_', 'L').replace('RIGHT_', 'R')})`
  }

  // if user typed a raw QMK keycode (starts with KC_, QK_, etc.), pass through
  if (/^(KC_|QK_|MO\(|TG\(|LT\(|MT\(|OSM\(|OSL\(|LCTL|LSFT|LALT|LGUI|RCTL|RSFT|RALT|RGUI|MS_|MI_|RGB_|S\(|C\(|A\(|G\()/.test(act)) {
    return act
  }

  // mod+key combos: "Ctrl+R" → LCTL(KC_R)
  if (type === 'mod' || act.includes('+')) {
    return resolveModCombo(act)
  }

  // basic/key/media — look up in the table
  return resolveKeycode(act)
}

function resolveKeycode(s) {
  const lower = s.toLowerCase().trim()
  if (ACTION_TO_QMK[lower]) return ACTION_TO_QMK[lower]
  // already a QMK keycode?
  if (/^(KC_|MS_|MI_|RGB_)/.test(s)) return s
  // try KC_ prefix
  const upper = `KC_${s.toUpperCase().replace(/\s+/g, '_')}`
  return upper
}

function resolveModPrefix(s) {
  const m = s.toLowerCase().trim()
  const map = { ctrl: 'LCTL', lctrl: 'LCTL', rctrl: 'RCTL', shift: 'LSFT', lshift: 'LSFT', rshift: 'RSFT', alt: 'LALT', lalt: 'LALT', ralt: 'RALT', gui: 'LGUI', lgui: 'LGUI', rgui: 'RGUI' }
  return map[m] || s.toUpperCase()
}

function resolveModCombo(s) {
  // "Ctrl+Shift+R" → C(S(KC_R))
  const parts = s.split('+').map(p => p.trim())
  const key = parts.pop()
  const kc = resolveKeycode(key)
  const modWrap = { ctrl: 'C', lctrl: 'C', rctrl: 'RCTL', shift: 'S', lshift: 'S', rshift: 'RSFT', alt: 'A', lalt: 'A', ralt: 'RALT', gui: 'G', lgui: 'G', rgui: 'RGUI' }
  let result = kc
  for (const mod of parts.reverse()) {
    const fn = modWrap[mod.toLowerCase()] || mod.toUpperCase()
    result = `${fn}(${result})`
  }
  return result
}

function generateKeymapC(device, preset) {
  const layout = device.qmk.layout
  const keymap = preset.keymap || [{}]
  const layers = preset.layers || [{ name: 'base' }]
  const sequences = preset.sequences || []

  // Build matrix → position lookup from device.json
  // The right half slot order in LAYOUT_split_3x6_3_ex2:
  // Right row0: ex1(4,6), 4,0..4,5  (slots 7-13)
  // Right row1: ex2(5,6), 5,0..5,5  (slots 21-27)
  // Right row2: 6,0..6,5            (slots 34-39)
  // Right thumb: 7,3, 7,4, 7,5      (slots 43-45)
  const rightSlots = [
    '4,6', '4,0', '4,1', '4,2', '4,3', '4,4', '4,5',   // row0
    '5,6', '5,0', '5,1', '5,2', '5,3', '5,4', '5,5',   // row1
    '6,0', '6,1', '6,2', '6,3', '6,4', '6,5',           // row2
    '7,3', '7,4', '7,5',                                  // thumb
  ]

  // Left half mirrors: same JS buttons, same layout
  const leftSlots = [
    '0,5', '0,0', '0,1', '0,2', '0,3', '0,4',  '0,6',  // row0 + ex1
    '1,5', '1,0', '1,1', '1,2', '1,3', '1,4',  '1,6',  // row1 + ex2
    '2,5', '2,0', '2,1', '2,2', '2,3', '2,4',           // row2
    '3,2', '3,1', '3,0',                                  // thumb
  ]

  // Find boot combo from sequences or device config
  const bootCombo = device.boot_combo || []
  // Map btn indices to matrix positions for combo
  const btnToMatrixMap = {}
  for (const k of device.matrix.keys) { btnToMatrixMap[k.btn] = k.matrix }

  // generate combo entries for sequences that map to layer_tg
  const combos = []

  // boot combo
  if (bootCombo.length > 0) {
    combos.push({
      name: 'boot_combo',
      keys: bootCombo.map(btn => `JS_${btn}`),
      action: 'QK_BOOT',
      comment: 'bootloader',
    })
  }

  // Generate layers
  const numLayers = Math.max(keymap.length, layers.length)
  const layerStrings = []

  for (let li = 0; li < numLayers; li++) {
    const layerKeys = keymap[li] || {}
    const layerName = (layers[li] && layers[li].name) || `layer ${li}`

    // Build right half keycodes
    const rightCodes = rightSlots.map(matrix => {
      const entry = layerKeys[matrix]
      if (entry) return actionToQMK(entry.type, entry.action)
      // unmapped key: transparent on non-base, joystick button on base
      if (li > 0) return 'KC_TRNS'
      const dk = device.matrix.keys.find(k => k.matrix === matrix)
      return dk ? `JS_${dk.btn}` : 'KC_NO'
    })

    // Left half: keep as joystick buttons (no left-half preset yet)
    const leftBtnOrder = [7, 6, 5, 4, 3, 2, 0, 13, 12, 11, 10, 9, 8, 1, 19, 18, 17, 16, 15, 14, 22, 21, 20]
    const leftCodes = leftBtnOrder.map(btn => li === 0 ? `JS_${btn}` : 'KC_TRNS')

    // Format the layer
    const indent = '        '
    const rows = [
      `${indent}// Left: row0(6) + ex1`,
      `${indent}${leftCodes.slice(0, 7).join(', ')},`,
      `${indent}// Right: ex1 + row0(6)`,
      `${indent}${rightCodes.slice(0, 7).join(', ')},`,
      `${indent}// Left: row1(6) + ex2`,
      `${indent}${leftCodes.slice(7, 14).join(', ')},`,
      `${indent}// Right: ex2 + row1(6)`,
      `${indent}${rightCodes.slice(7, 14).join(', ')},`,
      `${indent}// Left: row2(6)`,
      `${indent}${leftCodes.slice(14, 20).join(', ')},`,
      `${indent}// Right: row2(6)`,
      `${indent}${rightCodes.slice(14, 20).join(', ')},`,
      `${indent}// Left: thumb(3)`,
      `${indent}${leftCodes.slice(20, 23).join(', ')},`,
      `${indent}// Right: thumb(3)`,
      `${indent}${rightCodes.slice(20, 23).join(', ')}`,
    ]

    layerStrings.push(
      `    [${li}] = ${layout}(  // ${layerName}\n${rows.join('\n')}\n    )`
    )
  }

  // Build combo section
  let comboSection = ''
  if (combos.length > 0) {
    const comboDecls = combos.map(c =>
      `const uint16_t PROGMEM ${c.name}[] = {${c.keys.join(', ')}, COMBO_END};`
    ).join('\n')
    const comboArray = combos.map(c =>
      `    COMBO(${c.name}, ${c.action}), // ${c.comment}`
    ).join('\n')
    comboSection = `${comboDecls}\ncombo_t key_combos[] = {\n${comboArray}\n};\n`
  }

  // Build layer color section (for future RGB)
  const layerColors = layers.map((l, i) =>
    `//   layer ${i}: ${l.name} — ${l.color || '#ffffff'}`
  ).join('\n')

  // Assemble the file
  const keymapC = `// Generated by Kekboard Warrior
// Preset: ${preset.name || 'unnamed'}
// Device: ${device.name} (${device.qmk.keyboard})
// Generated: ${new Date().toISOString()}
//
// Layer colors:
${layerColors}

#include QMK_KEYBOARD_H

// ── Combos ──
${comboSection}
// clang-format off
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
${layerStrings.join(',\n\n')}
};
// clang-format on
`

  return keymapC
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)
  const path = url.pathname

  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); res.end(); return }

  // ── API: keycodes ──
  if (path === '/api/keycodes' && req.method === 'GET') {
    const f = join(CONFIG_DIR, 'keycodes.json')
    if (existsSync(f)) return json(res, JSON.parse(readFileSync(f, 'utf8')))
    return json(res, {})
  }

  // ── API: list devices ──
  if (path === '/api/devices' && req.method === 'GET') {
    const devices = readdirSync(CONFIG_DIR, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => {
        const f = join(CONFIG_DIR, d.name, 'device.json')
        return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : { id: d.name, name: d.name }
      })
    return json(res, devices)
  }

  // ── API: get device config ──
  const deviceMatch = path.match(/^\/api\/config\/([^/]+)\/device$/)
  if (deviceMatch && req.method === 'GET') {
    const f = join(CONFIG_DIR, deviceMatch[1], 'device.json')
    if (!existsSync(f)) return json(res, { error: 'not found' }, 404)
    return json(res, JSON.parse(readFileSync(f, 'utf8')))
  }

  // ── API: list presets ──
  const presetsMatch = path.match(/^\/api\/config\/([^/]+)\/presets$/)
  if (presetsMatch && req.method === 'GET') {
    const dir = join(CONFIG_DIR, presetsMatch[1], 'presets')
    if (!existsSync(dir)) return json(res, [])
    const presets = readdirSync(dir).filter(f => f.endsWith('.json')).map(f => f.replace('.json', ''))
    return json(res, presets)
  }

  // ── API: create new preset ──
  const newPresetMatch = path.match(/^\/api\/config\/([^/]+)\/presets$/)
  if (newPresetMatch && req.method === 'POST') {
    const deviceId = newPresetMatch[1]
    const dir = join(CONFIG_DIR, deviceId, 'presets')
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })

    // find next available name
    const existing = readdirSync(dir).filter(f => f.endsWith('.json')).map(f => f.replace('.json', ''))
    let n = 1
    let name = `${deviceId}-new-${n}`
    while (existing.includes(name)) { n++; name = `${deviceId}-new-${n}` }

    const skeleton = {
      name,
      device: deviceId,
      buttons: 23,
      layers: [{ name: 'base', color: '#e0f5ea' }],
      sequences: [],
      keymap: [{}],
      presetRules: [],
      deviceNotes: [],
      createdAt: new Date().toISOString(),
    }
    writeFileSync(join(dir, `${name}.json`), JSON.stringify(skeleton, null, 2))
    console.log(`created: config/${deviceId}/presets/${name}.json`)
    return json(res, { name, preset: skeleton })
  }

  // ── API: get/put preset ──
  const presetMatch = path.match(/^\/api\/config\/([^/]+)\/presets\/(.+)$/)
  if (presetMatch) {
    const deviceId = presetMatch[1]
    const presetName = presetMatch[2]
    const dir = join(CONFIG_DIR, deviceId, 'presets')
    const file = join(dir, `${presetName}.json`)

    if (req.method === 'GET') {
      if (!existsSync(file)) return json(res, { error: 'not found' }, 404)
      return json(res, JSON.parse(readFileSync(file, 'utf8')))
    }

    if (req.method === 'PUT') {
      const body = await readBody(req)
      try {
        const data = JSON.parse(body)
        data.savedAt = new Date().toISOString()
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
        writeFileSync(file, JSON.stringify(data, null, 2))
        console.log(`saved: config/${deviceId}/presets/${presetName}.json`)
        return json(res, { ok: true })
      } catch (e) { return json(res, { error: e.message }, 400) }
    }
  }

  // ── API: generate keymap.c ──
  if (path === '/api/generate-keymap' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req))
    const deviceId = body.device || 'corne-r'
    const presetName = body.preset
    if (!presetName) return json(res, { error: 'no preset specified' }, 400)

    const deviceFile = join(CONFIG_DIR, deviceId, 'device.json')
    const presetFile = join(CONFIG_DIR, deviceId, 'presets', `${presetName}.json`)
    if (!existsSync(deviceFile)) return json(res, { error: 'device not found' }, 404)
    if (!existsSync(presetFile)) return json(res, { error: 'preset not found' }, 404)

    const device = JSON.parse(readFileSync(deviceFile, 'utf8'))
    const preset = JSON.parse(readFileSync(presetFile, 'utf8'))

    try {
      const keymap = generateKeymapC(device, preset)
      // write to qmk dir
      const keymapPath = join(QMK_DIR, 'kekboard-warrior', 'keymap.c')
      writeFileSync(keymapPath, keymap)
      console.log(`generated: ${keymapPath}`)
      return json(res, { ok: true, keymap, path: keymapPath })
    } catch (e) {
      return json(res, { error: e.message }, 500)
    }
  }

  // ── API: compile firmware ──
  if (path === '/api/compile' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req))
    const deviceId = body.device || 'corne-r'
    const deviceFile = join(CONFIG_DIR, deviceId, 'device.json')
    if (!existsSync(deviceFile)) return json(res, { error: 'device not found' }, 404)
    const device = JSON.parse(readFileSync(deviceFile, 'utf8'))

    try {
      // copy keymap
      const keymapSrc = join(QMK_DIR, 'kekboard-warrior')
      const keymapDst = join(QMK_FIRMWARE, 'keyboards/crkbd/keymaps/kekboard-warrior')
      execSync(`cp -r ${keymapSrc}/* ${keymapDst}/`)

      // compile
      const result = execSync(
        `cd ${QMK_FIRMWARE} && qmk compile -kb ${device.qmk.keyboard} -km kekboard-warrior 2>&1`,
        { timeout: 300000, encoding: 'utf8' }
      )
      const uf2 = join(QMK_FIRMWARE, `crkbd_rev4_0_standard_kekboard-warrior.uf2`)
      return json(res, { ok: true, uf2: existsSync(uf2) ? uf2 : null, log: result.slice(-500) })
    } catch (e) {
      return json(res, { error: 'compile failed', log: e.stdout?.slice(-500) || e.message }, 500)
    }
  }

  // ── API: flash firmware ──
  if (path === '/api/flash' && req.method === 'POST') {
    const uf2 = join(QMK_FIRMWARE, 'crkbd_rev4_0_standard_kekboard-warrior.uf2')
    if (!existsSync(uf2)) return json(res, { error: 'no firmware compiled yet' }, 400)

    // look for RPI-RP2 mount
    const mounts = ['/media', '/run/media'].flatMap(base => {
      try {
        return readdirSync(base).flatMap(user => {
          const userDir = join(base, user)
          try {
            return readdirSync(userDir).filter(d => d.includes('RPI')).map(d => join(userDir, d))
          } catch { return [] }
        })
      } catch { return [] }
    })

    if (mounts.length === 0) return json(res, { error: 'no RPI-RP2 drive found — enter bootloader first' }, 400)

    try {
      execSync(`cp ${uf2} ${mounts[0]}/`)
      return json(res, { ok: true, target: mounts[0] })
    } catch (e) {
      return json(res, { error: e.message }, 500)
    }
  }

  // ── Static files ──
  let filePath = (path === '/' || path === '/index.html')
    ? join(__dirname, 'ui.html')
    : join(__dirname, path.slice(1))

  if (existsSync(filePath)) {
    cors(res)
    res.writeHead(200, { 'Content-Type': MIME[extname(filePath)] || 'application/octet-stream' })
    res.end(readFileSync(filePath))
  } else {
    res.writeHead(404); res.end('not found')
  }
})

server.listen(PORT, () => {
  console.log(`kekboard-warrior server`)
  console.log(`  http://localhost:${PORT}?device=corne-r&mode=mapping&preset=waveloop-2`)
  console.log(`  config: ${CONFIG_DIR}`)
  console.log(`  qmk:    ${QMK_FIRMWARE}`)
})
