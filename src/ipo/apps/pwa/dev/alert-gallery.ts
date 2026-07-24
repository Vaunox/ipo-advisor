// DEV-ONLY visual-QA harness for the F12 alert center. NOT part of the production bundle: it lives
// under dev/ (outside tsconfig's `include`) and no production entry imports it. Every panel is built
// from the SHIPPED pure `buildAlertFeed()` + the SHIPPED styles.css, and the row markup MIRRORS
// components/AlertCenter.tsx — so what you see here is what the app renders (it cannot drift, the same
// way chip-gallery mirrors the sync chip). Copy shown here is the real degradedConditions() copy —
// this is the surface to iterate the wording on.
//
//   Run:  npm run dev   (in src/ipo/apps/pwa)   →   open http://localhost:5173/dev/alert-gallery.html
import '../src/styles.css'
import { type AlertFeed, type AlertItem, buildAlertFeed, crossingKey } from '../src/alerts'
import type { IPOListRow, StatusView, VerdictTransition } from '../src/api/types'

// ── mock data ────────────────────────────────────────────────────────────────────────────────────
function ymd(offsetDays: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function row(id: string, o: { open: number; close: number }): IPOListRow {
  return {
    ipo_id: id,
    name: id,
    segment: 'mainboard',
    issue_size_cr: null,
    ofs_fraction: null,
    issue_pe: null,
    peer_median_pe: null,
    open_date: ymd(o.open),
    close_date: ymd(o.close),
    listing_date: null,
    verdict: 'APPLY',
    probability: 0.9,
    reason: '',
    watch: [],
    kill_flags: [],
    listing_overdue: false,
  }
}

function xing(ipo: string, name: string, prob: number): VerdictTransition {
  return {
    ipo_id: ipo,
    name,
    asof: '2026-07-14T15:00:00+05:30',
    from_verdict: 'MARGINAL',
    to_verdict: 'APPLY',
    probability: prob,
    crossed_into_apply: true,
  }
}

const board: IPOListRow[] = [row('tata', { open: -1, close: 2 }), row('nsdl', { open: -1, close: 0 })]
const crossings: VerdictTransition[] = [
  xing('tata', 'Tata Technologies', 0.94),
  xing('nsdl', 'NSDL', 0.81),
]
const healthy: StatusView = {
  live_ingest: true,
  last_successful_ingest: '2026-07-14T15:00:00+05:30',
  last_attempt: '2026-07-14T15:00:00+05:30',
  last_attempt_ok: true,
  checked_at: '2026-07-14T15:00:00+05:30',
  records_source: null,
  context_source: null,
  next_refresh_at: null,
}
const s = (over: Partial<StatusView>): StatusView => ({ ...healthy, ...over })

const fmtDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

const dotColor = (i: AlertItem): string =>
  i.kind === 'event' ? 'var(--apply)' : i.severity === 'red' ? 'var(--skip)' : 'var(--marginal)'

// ── shipped markup mirror (components/AlertCenter.tsx) ─────────────────────────────────────────────
function bellEl(feed: AlertFeed): HTMLElement {
  const btn = document.createElement('button')
  btn.className = 'alertbtn'
  btn.style.pointerEvents = 'none'
  btn.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"/></svg>'
  if (feed.flag) {
    const b = document.createElement('span')
    b.className = `badge flag ${feed.flag}`
    b.textContent = '!'
    btn.append(b)
  } else if (feed.badge > 0) {
    const b = document.createElement('span')
    b.className = 'badge'
    b.textContent = String(feed.badge)
    btn.append(b)
  }
  return btn
}

function itemEl(item: AlertItem): HTMLElement {
  const el = document.createElement('div')
  const dot = document.createElement('span')
  dot.className = 'adot'
  dot.style.background = dotColor(item)
  const body = document.createElement('div')
  const an = document.createElement('div')
  an.className = 'an'
  const am = document.createElement('div')
  am.className = 'am'
  if (item.kind === 'condition') {
    el.className = `alertitem condition ${item.severity}`
    an.textContent = item.title
    am.textContent = item.detail
  } else {
    el.className = 'alertitem event'
    an.innerHTML =
      `${item.name} ` +
      (item.probability != null
        ? `<span style="color:var(--apply);font-family:'Fira Code'">${Math.round(item.probability * 100)}%</span>`
        : '')
    am.innerHTML = `crossed into APPLY · <span class="mono">${fmtDate(item.asof)}</span>`
  }
  body.append(an, am)
  el.append(dot, body)
  return el
}

// Render the open panel for a feed; `onClear` (when the feed has events) wires the live Clear demo.
function panelEl(feed: AlertFeed, onClear?: () => void): HTMLElement {
  const panel = document.createElement('div')
  panel.className = 'alertpanel'
  panel.style.position = 'static' // gallery: lay panels out in the grid, not absolutely positioned
  const head = document.createElement('div')
  head.className = 'ahrow'
  const title = document.createElement('span')
  title.className = 'ah'
  title.textContent = 'Alerts'
  head.append(title)
  if (feed.items.some((i) => i.kind === 'event') && onClear) {
    const clear = document.createElement('button')
    clear.className = 'ah-clear'
    clear.textContent = 'Clear'
    clear.onclick = onClear
    head.append(clear)
  }
  panel.append(head)
  if (feed.items.length) {
    for (const item of feed.items) panel.append(itemEl(item))
  } else {
    const empty = document.createElement('div')
    empty.className = 'alert-empty'
    empty.textContent = "You're all caught up."
    panel.append(empty)
  }
  return panel
}

// ── scenarios ──────────────────────────────────────────────────────────────────────────────────────
interface Scene {
  name: string
  feed: () => AlertFeed
}
const none = new Set<string>()
const scenes: Scene[] = [
  {
    name: 'Events only — 2 unread APPLY crossings → the count badge (no "!")',
    feed: () => buildAlertFeed(crossings, board, healthy, false, none, none),
  },
  {
    name: 'Condition only — market context aging → "!" (amber) replaces the count, not dismissible',
    feed: () => buildAlertFeed([], board, s({ records_source: 'vm', context_source: 'local' }), false, none, none),
  },
  {
    name: 'Mixed — a condition + events → "!" summary; condition on top, events below; Clear removes only events',
    feed: () => buildAlertFeed(crossings, board, s({ records_source: 'vm', context_source: 'local' }), false, none, none),
  },
  {
    name: 'Engine unreachable (isError) — the single RED condition, "!" red, subsumes the source states',
    feed: () => buildAlertFeed(crossings, board, healthy, true, none, none),
  },
  {
    name: 'Full server outage — server-unreachable + context-aging = TWO amber entries (one per condition)',
    feed: () => buildAlertFeed([], board, s({ records_source: 'local', context_source: 'local' }), false, none, none),
  },
  {
    name: 'Empty — no events, no conditions',
    feed: () => buildAlertFeed([], board, healthy, false, none, none),
  },
]

// ── layout ───────────────────────────────────────────────────────────────────────────────────────
const root = document.getElementById('root')!
root.style.cssText =
  'padding:28px 32px; max-width:1100px; margin:0 auto; font-family:"Fira Sans", system-ui, sans-serif;'

const h1 = document.createElement('h1')
h1.textContent = 'F12 — alert center (rendered by the shipped buildAlertFeed + styles.css)'
h1.style.cssText = 'font-size:18px; margin:0 0 4px;'
const sub = document.createElement('div')
sub.textContent =
  'Each card = the bell badge + the open panel for one state. Conditions are undismissible (self-clear); events dismiss via Clear. Copy here is the shipped degradedConditions() text — iterate wording on this surface.'
sub.style.cssText = 'font-size:12.5px; color:var(--tx2); margin-bottom:24px;'
root.append(h1, sub)

const grid = document.createElement('div')
grid.style.cssText = 'display:flex; flex-wrap:wrap; gap:28px 40px; align-items:flex-start;'
root.append(grid)

for (const scene of scenes) {
  const card = document.createElement('div')
  card.style.cssText = 'display:flex; flex-direction:column; gap:12px; width:330px;'
  const label = document.createElement('div')
  label.textContent = scene.name
  label.style.cssText = 'font-size:12px; color:var(--tx2); min-height:32px;'
  const bellRow = document.createElement('div')
  bellRow.style.cssText = 'display:flex; align-items:center; gap:12px;'
  bellRow.append(bellEl(scene.feed()))
  card.append(label, bellRow, panelEl(scene.feed()))
  grid.append(card)
}

// ── interactive Clear demo — click Clear, watch events dismiss (conditions stay) ────────────────────
const demoHead = document.createElement('div')
demoHead.textContent = 'Interactive — click "Clear": events dismiss (conditions stay), the badge drops to no stale count'
demoHead.style.cssText =
  'font-family:"Fira Code"; font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--tx3); margin:34px 0 14px; border-bottom:1px solid var(--line); padding-bottom:6px;'
root.append(demoHead)

const demoWrap = document.createElement('div')
demoWrap.style.cssText = 'display:flex; align-items:flex-start; gap:12px; width:330px;'
root.append(demoWrap)

const dismissed = new Set<string>()
function renderDemo(): void {
  demoWrap.replaceChildren()
  // A live server-outage condition + the two events, so Clear leaves the two conditions behind.
  const feed = buildAlertFeed(
    crossings,
    board,
    s({ records_source: 'local', context_source: 'local' }),
    false,
    dismissed,
    none,
  )
  const col = document.createElement('div')
  col.style.cssText = 'display:flex; flex-direction:column; gap:12px; width:330px;'
  const bellRow = document.createElement('div')
  bellRow.style.cssText = 'display:flex; align-items:center; gap:12px;'
  bellRow.append(bellEl(feed))
  col.append(
    bellRow,
    panelEl(feed, () => {
      for (const i of feed.items) if (i.kind === 'event') dismissed.add(crossingKey({ ipo_id: i.ipo_id, asof: i.asof }))
      renderDemo()
    }),
  )
  demoWrap.append(col)
}
renderDemo()
