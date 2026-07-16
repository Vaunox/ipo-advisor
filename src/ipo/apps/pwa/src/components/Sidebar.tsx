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
        {/* v3 V3-12: the brand jewel as a clean inline vector (diamond-in-diamond) — no background
            box, so it stays light inline beside the wordmark and matches the terminal aesthetic. */}
        <div className="mark" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <defs>
              <linearGradient id="brandmark" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#3ddc84" />
                <stop offset="1" stopColor="#1f9d55" />
              </linearGradient>
            </defs>
            <path d="M12 1 L23 12 L12 23 L1 12 Z" fill="url(#brandmark)" />
            <path d="M12 6.6 L17.4 12 L12 17.4 L6.6 12 Z" fill="#06170d" />
          </svg>
        </div>
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
