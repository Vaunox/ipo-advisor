import { type MouseEvent, useEffect, useRef, useState } from 'react'
import { useTransitions } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { getAlertsSeen, setAlertsSeen } from '../state/prefs'
import { VMETA } from '../verdict'

const fmtDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

// The notifications surface: the current APPLY signals you'd be alerted about, plus the persisted
// history of APPLY crossings from the engine's transition log (recorded as the verdict crossed,
// never re-derived) — the honest "when did this become APPLY" trail.
export function AlertCenter({
  board,
  onOpenIpo,
}: {
  board: IPOListRow[]
  onOpenIpo: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  // Which APPLY signals have already been seen — persisted, so the unread badge survives a reload
  // and only re-lights when a genuinely new IPO crosses into APPLY.
  const [seen, setSeen] = useState<Set<string>>(() => new Set(getAlertsSeen()))
  const wrap = useRef<HTMLDivElement>(null)
  const alerts = (board ?? []).filter((r) => r.verdict === 'APPLY')
  const { data: transitions } = useTransitions()
  const crossings = (transitions ?? []).filter((t) => t.crossed_into_apply)
  const unread = alerts.filter((a) => !seen.has(a.ipo_id)).length

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
    // Mark the current APPLY signals as seen (persisted) when the panel is opened.
    const next = new Set([...seen, ...alerts.map((a) => a.ipo_id)])
    setSeen(next)
    setAlertsSeen([...next])
  }

  return (
    <div className="alertwrap" ref={wrap}>
      <button className="alertbtn" onClick={toggle} title="APPLY signals & crossing history">
        <svg viewBox="0 0 24 24">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {unread > 0 && <span className="badge">{unread}</span>}
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

          <div className="ah ah-sub">Recent APPLY crossings</div>
          {crossings.length ? (
            crossings.map((t, i) => (
              <div
                className="alertitem cross"
                key={`${t.ipo_id}-${i}`}
                onClick={() => {
                  setOpen(false)
                  onOpenIpo(t.ipo_id)
                }}
              >
                <span className="adot" style={{ background: 'var(--apply)' }} />
                <div>
                  <div className="an">
                    {t.name}{' '}
                    {t.probability != null && (
                      <span style={{ color: 'var(--apply)', fontFamily: 'Fira Code' }}>
                        {Math.round(t.probability * 100)}%
                      </span>
                    )}
                  </div>
                  <div className="am">
                    crossed into APPLY · <span className="mono">{fmtDate(t.asof)}</span>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="alert-empty">No crossings recorded yet.</div>
          )}
        </div>
      )}
    </div>
  )
}
