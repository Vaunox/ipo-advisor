import { useIsFetching } from '@tanstack/react-query'
import { useBoard, useHealth } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { ThemeToggle } from './ThemeToggle'

// Always-visible data-state chip: shows when the app is refreshing, when it last successfully
// refreshed ("Updated h:mm AM/PM" IST), and — when the engine is unreachable — that it's reconnecting.
// So the user always knows what the app is doing with the live feed. Reads react-query state only.
function SyncStatus() {
  const fetching = useIsFetching()
  const health = useHealth()
  const board = useBoard()
  const updated = board.dataUpdatedAt
    ? new Date(board.dataUpdatedAt).toLocaleTimeString('en-US', {
        timeZone: 'Asia/Kolkata',
        hour12: true,
        hour: 'numeric',
        minute: '2-digit',
      })
    : null

  let state: 'err' | 'busy' | 'ok'
  let text: string
  if (health.isError) {
    state = 'err'
    text = 'Reconnecting…'
  } else if (fetching > 0) {
    state = 'busy'
    text = 'Refreshing…'
  } else {
    state = 'ok'
    text = updated ? `Updated ${updated} IST` : 'Live'
  }

  return (
    <div
      className={`syncstat ${state}`}
      role="status"
      aria-live="polite"
      title={
        state === 'err'
          ? "Couldn't reach the engine — retrying automatically"
          : state === 'busy'
            ? 'Refreshing from the live feed…'
            : updated
              ? `Last refreshed ${updated} IST`
              : 'Live'
      }
    >
      <span className={state === 'err' ? 'sync err' : state === 'busy' ? 'sync on' : 'sync'} />
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
