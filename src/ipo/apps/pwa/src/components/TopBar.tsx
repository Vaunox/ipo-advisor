import { useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useHealth, useStatus } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { refreshHold, syncChip } from '../status'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { IconRefresh } from './Icons'
import { ThemeToggle } from './ThemeToggle'

// OP-2: ONE source of truth for "a genuine manual refresh is in flight", shared by the RefreshButton
// (writer) and the SyncStatus chip (reader). It owns the min-duration hold — `inFlight` stays true
// for at least REFRESH_MIN_VISIBLE_MS even if the pull resolves faster — so the chip's "Refreshing…"
// is a readable beat, never a sub-perceptible flash. Auto/background pulls NEVER touch this, so the
// chip is silent for them: the honest behavior, since the client cannot observe an auto-pull (the
// OP-2 diagnosis — `useIsFetching()` pulsing on every 5s /status re-poll was the old flicker).
interface RefreshCtx {
  inFlight: boolean
  trigger: () => void
}
const RefreshContext = createContext<RefreshCtx>({ inFlight: false, trigger: () => {} })
const useRefresh = () => useContext(RefreshContext)

// v3 V3-13 + OP-2: the manual-refresh busy/baseline/clear logic (formerly inside RefreshButton),
// lifted here so the chip reads the SAME in-flight state. On trigger it asks the engine for a REAL
// data pull — the same VM-primary→fallback cycle the app runs automatically (via the shell's
// privileged stdin channel, `window.ipoDesktop.refresh`), NOT a cosmetic spinner. It clears as soon
// as the engine genuinely DID something — `last_successful_ingest` OR `last_attempt` moved past this
// click's baseline (watching `last_attempt` too: a pull that reached NSE and failed still completes
// and shouldn't leave it spinning) — or the bounded fallback fires (the one case neither signal can
// see: the engine's 15s stdin debounce silently swallowing a click that lands right after a cycle).
// The min-duration hold (refreshHold) keeps "Refreshing…" visible for a readable beat regardless.
function RefreshProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const status = useStatus()
  const updatedAt = status.data?.last_successful_ingest ?? null
  const attemptedAt = status.data?.last_attempt ?? null
  const [inFlight, setInFlight] = useState(false)
  const baselineSuccess = useRef<string | null>(null)
  const baselineAttempt = useRef<string | null>(null)
  const startedAt = useRef<number>(0)

  useEffect(() => {
    if (!inFlight) return
    const elapsed = Date.now() - startedAt.current
    const resolved = updatedAt !== baselineSuccess.current || attemptedAt !== baselineAttempt.current
    const { clear, waitMs } = refreshHold(elapsed, resolved)
    if (clear) {
      setInFlight(false)
      return
    }
    // Not clearing yet: if resolved-within-beat, hold out the remaining beat; if still pulling, fall
    // back at the 10s bound (a debounced-away click has nothing to observe, so it just times out).
    const delay = resolved ? waitMs : Math.max(0, 10_000 - elapsed)
    const t = window.setTimeout(() => setInFlight(false), delay)
    return () => window.clearTimeout(t)
  }, [inFlight, updatedAt, attemptedAt])

  const trigger = () => {
    if (inFlight) return
    baselineSuccess.current = updatedAt
    baselineAttempt.current = attemptedAt
    startedAt.current = Date.now()
    setInFlight(true)
    const api = (window as unknown as { ipoDesktop?: { refresh?: () => Promise<boolean> } }).ipoDesktop
    if (api?.refresh) void api.refresh()
    else void qc.invalidateQueries() // browser/dev without the shell: re-read the engine, no live pull
  }

  return <RefreshContext.Provider value={{ inFlight, trigger }}>{children}</RefreshContext.Provider>
}

// v3 V3-13: a header Refresh control beside the alert bell. In-flight state: disabled + spinning
// while a manual pull is outstanding (the shared RefreshContext), cleared as soon as the engine did
// something — never a cosmetic spinner or timestamp bump.
function RefreshButton() {
  const { inFlight, trigger } = useRefresh()
  return (
    <button
      className="refreshbtn"
      onClick={trigger}
      disabled={inFlight}
      aria-label="Refresh now"
      title="Refresh now — pull the latest from the live feed"
    >
      <IconRefresh className={inFlight ? 'spin' : undefined} />
    </button>
  )
}

// Always-visible data-state chip. It reports the ONE honest clock: the last time a live NSE pull
// actually succeeded (`/status.last_successful_ingest`) — NOT when the local API last answered
// (v3 BUG 1 / Defect 2). The state/text/title decision is the pure `syncChip` in status.ts (tested),
// so the shipped chip can't drift from the tested one. OP-2: "Refreshing…" shows ONLY for a genuine
// manual pull (RefreshContext.inFlight), never `useIsFetching()`.
function SyncStatus() {
  const { inFlight } = useRefresh()
  const health = useHealth()
  const status = useStatus()
  const chip = syncChip({ isError: health.isError, refreshInFlight: inFlight, status: status.data })
  return (
    <div className={`syncstat ${chip.state}`} role="status" aria-live="polite" title={chip.title}>
      <span className={chip.dot} />
      <span className="syncstat-t">{chip.text}</span>
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
      <RefreshProvider>
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
      </RefreshProvider>
    </div>
  )
}
