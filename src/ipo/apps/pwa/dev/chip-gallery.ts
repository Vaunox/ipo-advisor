// DEV-ONLY visual-QA harness for the OP-2 Phase 2 sync chip. NOT part of the production bundle:
// it lives under dev/ (outside tsconfig's `include`) and no production entry imports it. Every chip
// is rendered by the SHIPPED pure `syncChip()` + the SHIPPED styles.css, so what you see here is
// exactly what the app renders — the preview cannot drift from production.
//
//   Run:  npm run dev   (in src/ipo/apps/pwa)   →   open http://localhost:5173/dev/chip-gallery.html
import '../src/styles.css'
import { DELAY_DISCLOSURE, syncChip } from '../src/status'
import type { SyncChipInput } from '../src/status'
import type { StatusView } from '../src/api/types'

// A healthy /status snapshot: checked at 10:29 IST, data also fresh. Individual cases override it.
const base: StatusView = {
  live_ingest: true,
  last_successful_ingest: '2026-07-20T10:29:00+05:30',
  last_attempt: '2026-07-20T10:29:00+05:30',
  last_attempt_ok: true,
  checked_at: '2026-07-20T10:29:00+05:30',
  records_source: null,
  context_source: null,
  next_refresh_at: null,
}

interface Case {
  group: string
  name: string
  input: SyncChipInput
}

const cases: Case[] = [
  {
    group: 'Steady — the new primary line',
    name: 'healthy: "Checked HH:MM" (the app-pull clock, not the VM refreshed_at)',
    input: { isError: false, refreshInFlight: false, ack: 'none', status: base },
  },
  {
    group: 'Acknowledgment — 2s transient after a manual press',
    name: 'nothing newer (advanced=false) — the console case that used to feel dead',
    input: { isError: false, refreshInFlight: false, ack: 'uptodate', status: base },
  },
  {
    group: 'Acknowledgment — 2s transient after a manual press',
    name: 'new data arrived (advanced=true)',
    input: { isError: false, refreshInFlight: false, ack: 'newdata', status: base },
  },
  {
    group: 'Acknowledgment — 2s transient after a manual press',
    name: 'a reachable pull errored',
    input: { isError: false, refreshInFlight: false, ack: 'failed', status: base },
  },
  {
    group: 'In-flight',
    name: 'manual pull in flight (≥600ms beat, before the ack)',
    input: { isError: false, refreshInFlight: true, ack: 'none', status: base },
  },
  {
    group: 'Formerly a chip suffix — now PLAIN "Checked" (F12: the degradation moved to the bell)',
    name: 'a newer pull failed → plain "Checked" (bell: "Refresh failed")',
    input: {
      isError: false,
      refreshInFlight: false,
      ack: 'none',
      status: { ...base, last_attempt_ok: false },
    },
  },
  {
    group: 'Formerly a chip suffix — now PLAIN "Checked" (F12: the degradation moved to the bell)',
    name: 'records on local → plain "Checked" (bell: "Server unreachable")',
    input: {
      isError: false,
      refreshInFlight: false,
      ack: 'none',
      status: { ...base, records_source: 'local', context_source: 'vm' },
    },
  },
  {
    group: 'Formerly a chip suffix — now PLAIN "Checked" (F12: the degradation moved to the bell)',
    name: 'context on local → plain "Checked" (bell: "Market context aging")',
    input: {
      isError: false,
      refreshInFlight: false,
      ack: 'none',
      status: { ...base, records_source: 'vm', context_source: 'local' },
    },
  },
  {
    group: 'Formerly a chip suffix — now PLAIN "Checked" (F12: the degradation moved to the bell)',
    name: 'both stores fell back → plain "Checked" (bell: two entries)',
    input: {
      isError: false,
      refreshInFlight: false,
      ack: 'none',
      status: { ...base, records_source: 'local', context_source: 'local' },
    },
  },
  {
    group: 'Other states',
    name: 'engine unreachable — STAYS on the chip ("Reconnecting…") AND is a red bell condition',
    input: { isError: true, refreshInFlight: false, ack: 'none', status: base },
  },
  {
    group: 'Other states',
    name: 'no live feed configured (dark-ship)',
    input: { isError: false, refreshInFlight: false, ack: 'none', status: { ...base, live_ingest: false } },
  },
  {
    group: 'Other states',
    name: 'cold start — "No data yet" (honest at any duration, not a transient "Awaiting…")',
    input: {
      isError: false,
      refreshInFlight: false,
      ack: 'none',
      status: { ...base, checked_at: null, last_successful_ingest: null },
    },
  },
]

// Build the SHIPPED chip markup (mirrors components/TopBar.tsx SyncStatus) from a syncChip result.
function chipEl(input: SyncChipInput): HTMLElement {
  const chip = syncChip(input)
  const wrap = document.createElement('div')
  wrap.className = `syncstat ${chip.state}`
  wrap.setAttribute('role', 'status')
  wrap.title = chip.title // real hover tooltip
  const dot = document.createElement('span')
  dot.className = chip.dot
  const t = document.createElement('span')
  t.className = 'syncstat-t'
  t.textContent = chip.text
  wrap.append(dot, t)
  return wrap
}

const root = document.getElementById('root')!
root.style.cssText =
  'padding:28px 32px; max-width:1100px; margin:0 auto; font-family:"Fira Sans", system-ui, sans-serif;'

const h1 = document.createElement('h1')
h1.textContent = 'F12 — sync chip: ONE fixed 16ch width in every state (rendered by the shipped syncChip)'
h1.style.cssText = 'font-size:18px; margin:0 0 4px;'
const sub = document.createElement('div')
sub.textContent = `Tooltip on every chip = the static disclosure "${DELAY_DISCLOSURE}" (hover to confirm); degraded/error states carry their own title.`
sub.style.cssText = 'font-size:12.5px; color:var(--tx2); margin-bottom:24px;'
root.append(h1, sub)

let lastGroup = ''
for (const c of cases) {
  if (c.group !== lastGroup) {
    lastGroup = c.group
    const g = document.createElement('div')
    g.textContent = c.group
    g.style.cssText =
      'font-family:"Fira Code"; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--tx3); margin:22px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px;'
    root.append(g)
  }
  const row = document.createElement('div')
  row.style.cssText = 'display:flex; align-items:center; gap:18px; margin:10px 0;'
  const chip = chipEl(c.input)
  const label = document.createElement('div')
  label.textContent = c.name
  label.style.cssText = 'font-size:12.5px; color:var(--tx2);'
  const tip = document.createElement('div')
  tip.textContent = `tooltip: ${syncChip(c.input).title}`
  tip.style.cssText = 'font-family:"Fira Code"; font-size:10.5px; color:var(--tx3); margin-left:auto;'
  row.append(chip, label, tip)
  root.append(row)
}

// --- Width / no-shift check: EVERY retained state, stacked left-aligned so their right edges must
// line up on the dashed guide. The chip is now fixed at 16ch (min==max), so none can poke past it —
// every degraded suffix that used to overrun it lives in the bell (F12).
const shiftHead = document.createElement('div')
shiftHead.textContent = 'Width / no-shift check — every state shares the FIXED 16ch width; right edges must align'
shiftHead.style.cssText =
  'font-family:"Fira Code"; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--tx3); margin:30px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px;'
root.append(shiftHead)

const stack = document.createElement('div')
stack.style.cssText = 'position:relative; display:inline-flex; flex-direction:column; gap:8px;'
const noShift: SyncChipInput[] = [
  { isError: false, refreshInFlight: false, ack: 'none', status: base }, // Checked 10:29 AM
  { isError: false, refreshInFlight: true, ack: 'none', status: base }, // Refreshing…
  { isError: false, refreshInFlight: false, ack: 'newdata', status: base }, // New data ✓
  { isError: false, refreshInFlight: false, ack: 'uptodate', status: base }, // Up to date ✓
  { isError: false, refreshInFlight: false, ack: 'failed', status: base }, // Couldn't refresh
  { isError: true, refreshInFlight: false, ack: 'none', status: base }, // Reconnecting…
  { isError: false, refreshInFlight: false, ack: 'none', status: { ...base, live_ingest: false } }, // Live
  { isError: false, refreshInFlight: false, ack: 'none', status: { ...base, checked_at: null, last_successful_ingest: null } }, // No data yet
]
for (const i of noShift) stack.append(chipEl(i))
// A dashed guide at the right edge of the (equal-width) chips.
const guide = document.createElement('div')
guide.style.cssText =
  'position:absolute; top:-4px; bottom:-4px; right:0; border-right:1px dashed var(--marginal); pointer-events:none;'
stack.append(guide)
root.append(stack)
