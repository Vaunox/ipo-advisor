import { useIsFetching } from '@tanstack/react-query'
import type { IPOListRow } from '../api/types'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { ThemeToggle } from './ThemeToggle'

// A quiet always-present "live" dot that pulses while any query is in flight — so a background
// refresh (react-query refetches on its interval) is visible instead of numbers silently changing.
function SyncIndicator() {
  const fetching = useIsFetching()
  return (
    <span
      className={fetching ? 'sync on' : 'sync'}
      title={fetching ? 'Refreshing data…' : 'Live · up to date'}
      role="status"
      aria-label={fetching ? 'Refreshing data' : 'Data up to date'}
    />
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
        <SyncIndicator />
        <Clock />
        <ThemeToggle />
      </div>
    </div>
  )
}
