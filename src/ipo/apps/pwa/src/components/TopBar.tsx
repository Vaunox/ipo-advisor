import { useIsFetching, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useHealth, useStatus } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { fallbackStatus } from '../status'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { IconRefresh } from './Icons'
import { ThemeToggle } from './ThemeToggle'

// v3 V3-13: a header Refresh control beside the alert bell. On click it asks the engine for a REAL
// data pull — the same VM-primary→fallback cycle the app runs automatically (via the shell's
// privileged stdin channel, `window.ipoDesktop.refresh`), NOT a cosmetic spinner or timestamp bump.
// The "Updated" chip (SyncStatus) advances on its own once the genuine pull lands. In-flight state:
// disabled + spinning while a pull is outstanding, cleared when a newer successful pull lands (the
// `/status` timestamp advances) or after a bounded timeout so a coalesced/failed/VM-unreachable pull
// can't hang the spinner. Overlapping fetches are impossible anyway — the engine coalesces triggers
// within a 15s debounce (`_STDIN_REFRESH_DEBOUNCE_SEC`), so a mid-cycle press never stacks a pull.
function RefreshButton() {
  const qc = useQueryClient()
  const status = useStatus()
  const updatedAt = status.data?.last_successful_ingest ?? null
  const [busy, setBusy] = useState(false)
  const baseline = useRef<string | null>(null)

  useEffect(() => {
    if (!busy) return
    if (updatedAt !== baseline.current) {
      setBusy(false) // a genuinely-newer successful pull landed
      return
    }
    const t = window.setTimeout(() => setBusy(false), 20_000) // bounded: coalesced / failed / VM-down
    return () => window.clearTimeout(t)
  }, [busy, updatedAt])

  const onClick = () => {
    if (busy) return
    baseline.current = updatedAt
    setBusy(true)
    const api = (window as unknown as { ipoDesktop?: { refresh?: () => Promise<boolean> } }).ipoDesktop
    if (api?.refresh) void api.refresh()
    else void qc.invalidateQueries() // browser/dev without the shell: re-read the engine, no live pull
  }

  return (
    <button
      className="refreshbtn"
      onClick={onClick}
      disabled={busy}
      aria-label="Refresh now"
      title="Refresh now — pull the latest from the live feed"
    >
      <IconRefresh className={busy ? 'spin' : undefined} />
    </button>
  )
}

const istTimeOf = (iso: string): string =>
  new Date(iso).toLocaleTimeString('en-US', {
    timeZone: 'Asia/Kolkata',
    hour12: true,
    hour: 'numeric',
    minute: '2-digit',
  })

// Always-visible data-state chip. It reports the ONE honest clock: the last time a live NSE pull
// actually succeeded (`/status.last_successful_ingest`) — NOT when the local API last answered
// (v3 BUG 1 / Defect 2). So "Updated 9:00 AM" means NSE data genuinely last landed at 9:00 AM. If
// the feed is failing, the store is still served but the chip goes amber and says "retrying" — it
// never implies a freshness it does not have.
function SyncStatus() {
  const fetching = useIsFetching()
  const health = useHealth()
  const status = useStatus()
  const s = status.data
  const updated = s?.last_successful_ingest ? istTimeOf(s.last_successful_ingest) : null

  let state: 'err' | 'busy' | 'ok' | 'warn'
  let text: string
  let title: string
  if (health.isError) {
    state = 'err'
    text = 'Reconnecting…'
    title = "Couldn't reach the engine — retrying automatically"
  } else if (fetching > 0) {
    state = 'busy'
    text = 'Refreshing…'
    title = 'Refreshing from the live feed…'
  } else if (s && s.live_ingest === false) {
    // No live feed wired in this build — don't assert a time we don't have.
    state = 'ok'
    text = 'Live'
    title = 'No live NSE feed configured in this build'
  } else if (updated && s?.last_attempt_ok === false) {
    // Store still served, but the latest NSE pull failed — stale + retrying, shown honestly.
    state = 'warn'
    text = `Updated ${updated} · retrying`
    title = `Last successful NSE pull ${updated} IST — a newer pull failed; retrying automatically`
  } else if (updated) {
    state = 'ok'
    text = `Updated ${updated}`
    title = `Last successful NSE pull ${updated} IST`
  } else {
    // Never completed a successful pull yet (fresh install mid-first-fetch, or feed down at boot).
    state = s?.last_attempt_ok === false ? 'warn' : 'ok'
    text = 'Awaiting first update…'
    title = 'No successful NSE pull yet — fetching'
  }

  // v3 V3-1: compose the data-plane fallback into THIS one chip (never a second, contradicting chip).
  // It stays silent unless a store fell back from a configured VM; then it appends the honest
  // per-store truth (records fresh vs context aging) and turns the dot amber so a local degrade is
  // never silent. Freshness ("Updated …") already reflects records; this adds only the source state.
  const fb = s ? fallbackStatus(s.records_source, s.context_source) : null
  if (fb) {
    if (state === 'ok') state = 'warn'
    text = `${text} · ${fb.text}`
    title = `${title} · ${fb.title}`
  }

  // v3 QoL: append the next scheduled refresh to the TOOLTIP only (never the visible chip). The
  // engine sends `next_refresh_at` only when it can be honestly predicted (it's null on a failing
  // feed, a fallback, or just after a manual refresh) — so we simply show it when present, never a
  // guessed time. It reflects the engine's own windowed cadence (~30 min while a book is open, ~6h
  // otherwise), i.e. when NSE data actually gets newer — not the 5s UI poll that only re-reads.
  if (s?.next_refresh_at) title = `${title} · next refresh ~${istTimeOf(s.next_refresh_at)} IST`

  const dot = state === 'err' ? 'sync err' : state === 'warn' ? 'sync warn' : state === 'busy' ? 'sync on' : 'sync'
  return (
    <div className={`syncstat ${state}`} role="status" aria-live="polite" title={title}>
      <span className={dot} />
      <span className="syncstat-t">{text}</span>
    </div>
  )
}

export function TopBar({
  title,
  sub,
  board,
  onOpenIpo,
  onSearch,
}: {
  title: string
  sub: string
  board: IPOListRow[]
  onOpenIpo: (id: string) => void
  onSearch: () => void
}) {
  return (
    <div className="top">
      <div>
        <h1>{title}</h1>
        <div className="sub">{sub}</div>
      </div>
      <div className="controls">
        <AlertCenter board={board} onOpenIpo={onOpenIpo} />
        <RefreshButton />
        <button className="kbtn" onClick={onSearch}>
          Search <kbd>Ctrl K</kbd>
        </button>
        <SyncStatus />
        <Clock />
        <ThemeToggle />
      </div>
    </div>
  )
}
