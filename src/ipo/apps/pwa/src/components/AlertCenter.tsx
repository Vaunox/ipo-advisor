import { type MouseEvent, useEffect, useRef, useState } from 'react'
import { currentApplyAlerts, pruneSeenIds, relevantApplyCrossings } from '../alerts'
import { useTransitions } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import { getAlertsSeen, setAlertsSeen } from '../state/prefs'
import { VMETA } from '../verdict'

const fmtDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

// The notifications surface: the current APPLY signals you'd be alerted about, plus the APPLY
// crossings from the engine's transition log (recorded as the verdict crossed, never re-derived).
//
// v3 BUG 2 — relevance-scoped, not unbounded. Both lists show only IPOs whose outcome is still
// UNRESOLVED (`alertRelevant`: not yet listed — see status.ts), and crossings are deduped to the
// latest per IPO. The full transition log is untouched (it stays the permanent per-IPO audit trail
// on the detail view + primes the scheduler); this is a filtered VIEW over it, not a prune of it.
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
  const rows = board ?? []
  // Current APPLY signals + latest-per-IPO crossings, both scoped to still-unresolved IPOs (v3 BUG 2).
  const alerts = currentApplyAlerts(rows)
  const { data: transitions } = useTransitions()
  const crossings = relevantApplyCrossings(transitions ?? [], rows)
  const unread = alerts.filter((a) => !seen.has(a.ipo_id)).length

  // Prune the persisted "seen" set to ids that are still relevant (on the board and not yet listed),
  // so it can't grow without bound as IPOs list and leave (v3 BUG 2). Guarded against the cold-start
  // empty board (see pruneSeenIds) — pruning against no data used to wipe the set and re-light the
  // badge on every restart.
  useEffect(() => {
    const persisted = getAlertsSeen()
    const pruned = pruneSeenIds(persisted, rows)
    if (pruned.length !== persisted.length) {
      setAlertsSeen(pruned)
      setSeen(new Set(pruned))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board])

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
