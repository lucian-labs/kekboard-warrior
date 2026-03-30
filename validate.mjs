import { readFileSync } from 'fs'
import { Window } from 'happy-dom'
import { execSync } from 'child_process'

const html = readFileSync('ui.html', 'utf8')
const window = new Window({ url: 'http://localhost' })
window.document.write(html)

await window.happyDOM.waitUntilComplete()

const errors = []

const onclicks = window.document.querySelectorAll('[onclick]')
const scriptEl = window.document.querySelector('script')
const scriptText = scriptEl ? scriptEl.textContent : ''

// Extract all function definitions
const definedFns = new Set()
const fnMatches = scriptText.matchAll(/function\s+(\w+)\s*\(/g)
for (const m of fnMatches) definedFns.add(m[1])

// Check onclick handlers reference defined functions
for (const el of onclicks) {
  const handler = el.getAttribute('onclick')
  const fnMatch = handler.match(/^(\w+)\(/)
  if (fnMatch && !definedFns.has(fnMatch[1])) {
    errors.push(`onclick="${handler}" references undefined function: ${fnMatch[1]}`)
  }
}

// Check getElementById calls reference existing elements
const idRefs = scriptText.matchAll(/getElementById\(['"]([^'"]+)['"]\)/g)
for (const m of idRefs) {
  if (!window.document.getElementById(m[1])) {
    errors.push(`getElementById('${m[1]}') — element not found in DOM`)
  }
}

// Check for JS syntax errors and runtime init errors by actually evaluating
// We wrap in a try/catch and mock browser APIs
try {
  const testScript = `
    // mock browser APIs
    const navigator = { getGamepads: () => [] }
    const localStorage = { getItem: () => null, setItem: () => {} }
    const location = { protocol: 'http:', search: '', hash: '', pathname: '/' }
    const history = { replaceState: () => {} }
    const EventSource = function() { this.onopen = null; this.onerror = null; this.onmessage = null }
    const document = {
      querySelectorAll: () => [],
      querySelector: () => null,
      getElementById: () => ({ textContent: '', innerHTML: '', style: {}, value: '', dataset: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){return false} }, setAttribute(){}, getAttribute(){return ''} }),
      addEventListener: () => {},
      createElement: () => ({ className:'', innerHTML:'', dataset:{}, style:{}, click(){}, appendChild(){}, setAttribute(){} }),
    }
    const window = { addEventListener: () => {} }
    const requestAnimationFrame = () => {}
    const setTimeout = () => 0
    const clearTimeout = () => {}
    const fetch = () => Promise.resolve({ ok: false, json: () => ({}) })
    const prompt = () => null
    const alert = () => {}
    const Blob = function() {}
    const URLSearchParams = globalThis.URLSearchParams
    const URL = globalThis.URL || { createObjectURL: () => '' }

    ${scriptText}
  `
  // Use Node's vm module for better error reporting
  const vm = await import('vm')
  const script = new vm.Script(testScript, { filename: 'ui.html' })
  script.runInNewContext({ globalThis, console, URLSearchParams, Promise, parseInt, isNaN, JSON, Date, Array, Object, Set, Map, Number, String, RegExp, Error, TypeError, SyntaxError }, { timeout: 5000 })
} catch (e) {
  if (e.message.includes('Cannot access') || e.message.includes('is not defined') || e.message.includes('Duplicate')) {
    errors.push(`Runtime error: ${e.message}`)
  }
  // Syntax errors
  if (e instanceof SyntaxError) {
    errors.push(`SyntaxError: ${e.message}`)
  }
}

console.log(`Functions defined: ${definedFns.size}`)
console.log(`onclick handlers: ${onclicks.length}`)
console.log(`Errors: ${errors.length}`)
if (errors.length) {
  errors.forEach(e => console.log(`  ✗ ${e}`))
  process.exit(1)
} else {
  console.log('  ✓ All checks passed')
}

await window.happyDOM.close()
