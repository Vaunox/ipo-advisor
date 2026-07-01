import { Clock } from './Clock'
import { ThemeToggle } from './ThemeToggle'

export function TopBar({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="top">
      <div>
        <h1>{title}</h1>
        <div className="sub">{sub}</div>
      </div>
      <div className="controls">
        <Clock />
        <ThemeToggle />
      </div>
    </div>
  )
}
