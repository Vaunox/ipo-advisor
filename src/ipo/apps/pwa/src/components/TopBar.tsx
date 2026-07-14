import { useIsFetching } from '@tanstack/react-query'
import { useHealth, useStatus } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { ThemeToggle } from './ThemeToggle'

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
    text = `Updated ${updated} IST · retrying`
    title = `Last successful NSE pull ${updated} IST — a newer pull failed; retrying automatically`
  } else if (updated) {
    state = 'ok'
    text = `Updated ${updated} IST`
    title = `Last successful NSE pull ${updated} IST`
  } else {
    // Never completed a successful pull yet (fresh install mid-first-fetch, or feed down at boot).
    state = s?.last_attempt_ok === false ? 'warn' : 'ok'
    text = 'Awaiting first update…'
    title = 'No successful NSE pull yet — fetching'
  }

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
