import { type MouseEvent, useEffect, useRef, useState } from 'react'
import type { IPOListRow } from '../api/types'
import { VMETA } from '../verdict'

// The notifications surface: the current APPLY signals — the actionable verdicts you'd be alerted
// about. (A persisted crossing-log would need the engine's transition endpoint; this shows the live
// state honestly rather than faking a history.)
export function AlertCenter({ board, onOpenIpo }: { board: IPOListRow[]; onOpenIpo: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [read, setRead] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const alerts = board.filter((r) => r.verdict === 'APPLY')

  useEffect(() => {
    const onDoc = (e: globalThis.MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onDoc)
    return () => document.removeEventListener('click', onDoc)
  }, [])

  const toggle = (e: MouseEvent) => {
    e.stopPropagation()
    setOpen((o) => !o)
    setRead(true)
  }

  return (
    <div className="alertwrap" ref={wrap}>
      <button className="alertbtn" onClick={toggle} title="Current APPLY signals">
        <svg viewBox="0 0 24 24">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {alerts.length > 0 && !read && <span className="badge">{alerts.length}</span>}
      </button>
      {open && (
        <div className="alertpanel">
          <div className="ah">Current APPLY signals</div>
          {alerts.length ? (
            alerts.map((a) => (
              <div
                className="alertitem"
                key={a.ipo_id}
                onClick={() => {
                  setOpen(false)
                  onOpenIpo(a.ipo_id)
                }}
              >
                <span className="adot" style={{ background: `var(--${VMETA[a.verdict].cls})` }} />
                <div>
                  <div className="an">
                    {a.name}{' '}
                    {a.probability != null && (
                      <span style={{ color: 'var(--apply)', fontFamily: 'Fira Code' }}>
                        {Math.round(a.probability * 100)}%
                      </span>
                    )}
                  </div>
                  <div className="am">{a.reason}</div>
                </div>
              </div>
            ))
          ) : (
            <div className="alert-empty">No APPLY signals right now.</div>
          )}
        </div>
      )}
    </div>
  )
}
