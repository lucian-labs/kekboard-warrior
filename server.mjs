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

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)
  const path = url.pathname

  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); res.end(); return }

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
