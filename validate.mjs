import { readFileSync } from 'fs'
import { Window } from 'happy-dom'

const html = readFileSync('ui.html', 'utf8')
const window = new Window({ url: 'http://localhost' })
window.document.write(html)

await window.happyDOM.waitUntilComplete()

const errors = []

// Check all inline script for syntax by evaluating function names referenced in onclick
const onclicks = window.document.querySelectorAll('[onclick]')
const scriptEl = window.document.querySelector('script')
const scriptText = scriptEl ? scriptEl.textContent : ''

// Extract all function definitions from script
const definedFns = new Set()
const fnMatches = scriptText.matchAll(/function\s+(\w+)\s*\(/g)
for (const m of fnMatches) definedFns.add(m[1])

// Check onclick handlers
for (const el of onclicks) {
  const handler = el.getAttribute('onclick')
  const fnMatch = handler.match(/^(\w+)\(/)
  if (fnMatch && !definedFns.has(fnMatch[1])) {
    errors.push(`onclick="${handler}" references undefined function: ${fnMatch[1]}`)
  }
}

// Check getElementById calls reference existing elements
const idRefs = scriptText.matchAll(/getElementById\(['"](\w+)['"]\)/g)
for (const m of idRefs) {
  if (!window.document.getElementById(m[1])) {
    errors.push(`getElementById('${m[1]}') — element not found in DOM`)
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
