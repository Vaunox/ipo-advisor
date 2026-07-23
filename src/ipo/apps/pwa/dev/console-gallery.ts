// DEV-ONLY visual-QA harness for the F7 console line clamp+expand. NOT part of the production bundle:
// it lives under dev/ (outside tsconfig's `include`) and no production entry imports it. Rows are built
// from the SHIPPED pure formatDetail/levelClass/levelCode/shortTs + the SHIPPED styles.css, so what you
// see here is what the console renders — the preview cannot drift from production.
//
//   Run:  npm run dev   (in src/ipo/apps/pwa)   →   open http://localhost:5173/dev/console-gallery.html
import '../src/styles.css'
import { formatDetail, levelClass, levelCode, shortTs } from '../src/state/logview'
import type { LogEntry } from '../src/api/types'

const ISO = '2026-07-22T14:40:30.030102+05:30'

// The three real worst cases from the log call sites (placeholder host — the real VM IP is kept out
// of everything, including dev fixtures).
const cases: { label: string; entry: LogEntry }[] = [
  {
    label: 'stdin_refresh_outcome — ~165 chars, every manual refresh (classify_refresh_outcome)',
    entry: {
      ts: ISO, level: 'INFO', logger: 'ipo.service.runner', message: 'stdin_refresh_outcome',
      source: 'vm', advanced: false, attempted: false, attempt_ok: true,
      refreshed_at: ISO, refreshed_at_before: ISO,
    },
  },
  {
    label: 'vm_records_fallback_local error= — VM down, ~250 chars (str(exc), placeholder host)',
    entry: {
      ts: ISO, level: 'WARNING', logger: 'ipo.data.ingest.data_plane', message: 'vm_records_fallback_local',
      error:
        "HTTPConnectionPool(host='vm-internal', port=8000): Max retries exceeded with url: /records (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object>: Failed to establish a new connection: [Errno 111] Connection refused'))",
    },
  },
  {
    label: 'exc_info traceback — unbounded, multi-line (formatException through FastAPI/httpx)',
    entry: {
      ts: ISO, level: 'ERROR', logger: 'ipo.service.runner', message: 'scheduler_cycle_failed',
      error: 'Connection refused',
      exc_info:
        'Traceback (most recent call last):\n' +
        '  File "/app/ipo/service/runner.py", line 216, in _run_cycle_guarded\n' +
        '    return service.run_cycle()\n' +
        '  File "/app/ipo/service/engine.py", line 88, in run_cycle\n' +
        '    records = self._data_plane.records()\n' +
        '  File "/app/ipo/data/ingest/data_plane.py", line 71, in records\n' +
        '    resp = httpx.get(url, timeout=10)\n' +
        'httpx.ConnectError: [Errno 111] Connection refused',
    },
  },
]

// A couple of routine short lines, so you can see the list stays scannable (these don't wrap).
const routine: LogEntry[] = [
  { ts: ISO, level: 'INFO', logger: 'r', message: 'records_from_vm', count: 7 },
  { ts: ISO, level: 'INFO', logger: 'r', message: 'scheduler_cycle_done', scored: 10, transitions: 0, became_apply: 0 },
  { ts: ISO, level: 'INFO', logger: 'r', message: 'context_from_vm', ipos: 401 },
]

const root = document.getElementById('root')!
root.style.cssText =
  'padding:28px 32px; max-width:1120px; margin:0 auto; font-family:"Fira Sans", system-ui, sans-serif;'

// A console panel (the `.cl` scope defines the fixed dark tokens; width pinned to 1000px so the detail
// cell is the real ~408px and the wrap points match production). Height auto so rows show in full.
function panel(): HTMLElement {
  const wrap = document.createElement('div')
  wrap.className = 'cl'
  wrap.style.cssText = 'width:1000px; height:auto; max-width:100%; margin:0 0 8px;'
  const body = document.createElement('div')
  body.className = 'cl-body'
  body.style.cssText = 'overflow:visible;'
  const head = document.createElement('div')
  head.className = 'cl-head cl-grid'
  head.innerHTML = '<span>ts</span><span>level</span><span>event</span><span>ipo_id</span><span>detail</span>'
  body.append(head)
  wrap.append(body)
  return wrap
}

function rowEl(entry: LogEntry, opts: { clamp?: number; interactive?: boolean } = {}): HTMLElement {
  const row = document.createElement('div')
  row.className = `cl-ln cl-grid ${levelClass(entry.level)}`
  row.innerHTML = '<span class="ts"></span><span class="lv"></span><span class="ev"></span><span class="id"></span><span class="dt"></span>'
  ;(row.querySelector('.ts') as HTMLElement).textContent = shortTs(entry.ts)
  ;(row.querySelector('.lv') as HTMLElement).textContent = levelCode(entry.level)
  ;(row.querySelector('.ev') as HTMLElement).textContent = entry.message ?? ''
  const idEl = row.querySelector('.id') as HTMLElement
  idEl.textContent = entry.ipo_id ? String(entry.ipo_id) : '·'
  if (!entry.ipo_id) idEl.classList.add('none')
  const dt = row.querySelector('.dt') as HTMLElement
  dt.textContent = formatDetail(entry)
  if (opts.clamp) dt.style.webkitLineClamp = String(opts.clamp) // override the shipped 4 for A/B
  if (opts.interactive) {
    row.addEventListener('click', () => {
      if (window.getSelection()?.toString()) return // a drag-select must not toggle
      const wasOpen = row.classList.contains('open')
      root.querySelectorAll('.cl-ln.open').forEach((r) => {
        r.classList.remove('open')
        r.querySelector('.cl-copy')?.remove()
      })
      if (!wasOpen) {
        row.classList.add('open')
        const btn = document.createElement('button')
        btn.className = 'cl-copy'
        btn.textContent = 'copy'
        btn.title = 'Copy this line'
        btn.addEventListener('click', (e) => {
          e.stopPropagation()
          void navigator.clipboard?.writeText(formatDetail(entry)) // gallery = browser → Clipboard API
          btn.textContent = 'copied'
          window.setTimeout(() => (btn.textContent = 'copy'), 900)
        })
        row.append(btn)
      }
    })
  }
  return row
}

function heading(text: string): void {
  const h = document.createElement('div')
  h.textContent = text
  h.style.cssText =
    'font-family:"Fira Code"; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--tx3); margin:26px 0 10px; border-bottom:1px solid #28323f; padding-bottom:6px;'
  root.append(h)
}
function note(text: string): void {
  const n = document.createElement('div')
  n.textContent = text
  n.style.cssText = 'font-size:12.5px; color:var(--tx2); margin:0 0 10px;'
  root.append(n)
}

const h1 = document.createElement('h1')
h1.textContent = 'F7 — console detail: clamp + click-to-expand (rendered by the shipped formatDetail + styles.css)'
h1.style.cssText = 'font-size:18px; margin:0 0 4px;'
const sub = document.createElement('div')
sub.textContent =
  'Measured: detail cell ≈408px, 54 chars/line → 3 lines=162, 4 lines=216. stdin_refresh_outcome is ~165, so 3 lines clips it; 4 lines shows it whole. Compare the two below.'
sub.style.cssText = 'font-size:12.5px; color:var(--tx2); margin-bottom:8px;'
root.append(h1, sub)

// --- A/B: 3-line vs 4-line clamp, same three cases, collapsed -----------------------------------
heading('Clamp A — 3 lines (162 chars): stdin_refresh_outcome is clipped by a hair → needs a click')
const p3 = panel()
const body3 = p3.querySelector('.cl-body') as HTMLElement
for (const c of cases) body3.append(rowEl(c.entry, { clamp: 3 }))
root.append(p3)

heading('Clamp B — 4 lines (216 chars, the shipped default): stdin_refresh_outcome + short error= fit; only long fallbacks / tracebacks need a click')
const p4 = panel()
const body4 = p4.querySelector('.cl-body') as HTMLElement
for (const c of cases) body4.append(rowEl(c.entry, { clamp: 4 }))
root.append(p4)

// --- Interactive: click any row to expand; copy button appears on the open row -------------------
heading('Interactive — click a row to expand to full; drag-select the text (must NOT toggle); use “copy”')
note('Routine short lines stay one line and scannable; the three long cases wrap. Open one, select part of it, then click again to close.')
const pi = panel()
const bodyi = pi.querySelector('.cl-body') as HTMLElement
for (const e of routine) bodyi.append(rowEl(e, { interactive: true }))
for (const c of cases) bodyi.append(rowEl(c.entry, { interactive: true }))
root.append(pi)
