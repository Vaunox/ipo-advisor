import type { ReactNode } from 'react'
import type { View } from '../nav'
import { IconAllotment, IconHistory, IconSettings, IconSignals, IconUpcoming } from './Icons'

const NAV: { id: View; label: string; icon: ReactNode }[] = [
  { id: 'live', label: 'Live signals', icon: <IconSignals /> },
  { id: 'upcoming', label: 'Upcoming', icon: <IconUpcoming /> },
  { id: 'allotment', label: 'Allotment', icon: <IconAllotment /> },
  { id: 'history', label: 'History', icon: <IconHistory /> },
  { id: 'settings', label: 'Settings', icon: <IconSettings /> },
]

export function Sidebar({
  view,
  onNavigate,
  counts,
  engineUp,
  gatePassed,
  recalibrations,
}: {
  view: View
  onNavigate: (v: View) => void
  counts: Partial<Record<View, number>>
  engineUp: boolean
  gatePassed: boolean
  recalibrations: number
}) {
  return (
    <aside className="side">
      <div className="brand">
        <div className="mark mono">◆</div>
        <div>
          <b>IPO Advisor</b>
          <span>Terminal</span>
        </div>
      </div>
      <nav className="nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={view === n.id ? 'on' : ''}
            onClick={() => onNavigate(n.id)}
          >
            {n.icon} {n.label}
            {/* Live/Upcoming counts are bounded, current-state signals worth showing. History is a
                cumulative archive total — not actionable and only grows uglier — so no badge there. */}
            {n.id !== 'history' && counts[n.id] != null && (
              <span className="count">{counts[n.id]}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="side-foot">
        <span className={engineUp ? 'dot' : 'dot down'} />
        {engineUp ? 'Engine online' : 'Engine offline'}
        <br />
        {`calibrator · gate ${gatePassed ? 'passed' : 'not passed'}`}
        <br />
        <span style={{ whiteSpace: 'nowrap' }}>{`recalibrated ${recalibrations}×`}</span>
      </div>
    </aside>
  )
}
