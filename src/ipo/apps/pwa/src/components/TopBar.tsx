import type { IPOListRow } from '../api/types'
import { AlertCenter } from './AlertCenter'
import { Clock } from './Clock'
import { ThemeToggle } from './ThemeToggle'

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
        <Clock />
        <ThemeToggle />
      </div>
    </div>
  )
}
