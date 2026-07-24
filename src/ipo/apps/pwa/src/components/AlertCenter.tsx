import { type MouseEvent, useEffect, useMemo, useRef, useState } from 'react'
import { type AlertItem, buildAlertFeed, pruneDismissedKeys, pruneSeenIds } from '../alerts'
import { useHealth, useStatus, useTransitions } from '../api/hooks'
import type { IPOListRow } from '../api/types'
import {
  getAlertsSeen,
  getDismissedCrossings,
  setAlertsSeen,
  setDismissedCrossings,
} from '../state/prefs'

const fmtDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

const dotColor = (i: AlertItem): string =>
  i.kind === 'event'
    ? 'var(--apply)'
    : i.severity === 'red'
      ? 'var(--skip)'
      : 'var(--marginal)'

// The notifications surface (F12). ONE list of items — dismissible EVENTS (an IPO crossed into APPLY,
// happened once) and undismissible CONDITIONS (a degraded state that persists until it clears). The
// discriminated union built by `buildAlertFeed` keeps the split structural, so the two interactions
// stay clean:
//   * Opening the panel MARKS READ — the unread badge clears; the items stay (standard bell pattern).
//   * Clear DISMISSES the events — the events are removed (durably, per-crossing); conditions are left
//     alone, because dismiss filters the events branch only.
// The badge shows "!" (severity-coloured) whenever any condition is present, replacing the unread
// count; the count returns once the condition clears. "Current APPLY signals" (which duplicated the
// Live page) is gone; every degraded state that used to crowd the sync chip now lives here.
export function AlertCenter({
  board,
  onOpenIpo,
}: {
  board: IPOListRow[]
  onOpenIpo: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  // Persisted so the badge and dismissals survive a reload/restart (durable seen-state — OP-3).
  const [seen, setSeen] = useState<Set<string>>(() => new Set(getAlertsSeen()))
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set(getDismissedCrossings()))
  const wrap = useRef<HTMLDivElement>(null)
  const { data: transitions } = useTransitions()
  const status = useStatus()
  const health = useHealth()

  const feed = useMemo(
    () => buildAlertFeed(transitions ?? [], board ?? [], status.data, health.isError, dismissed, seen),
    [transitions, board, status.data, health.isError, dismissed, seen],
  )

  // Prune BOTH persisted sets to still-relevant ids so a durable set can't grow without bound: `seen`
  // by ipo_id, `dismissed` by its crossing-key's ipo_id. Both cold-start-guarded (pruneSeenIds /
  // pruneDismissedKeys never prune against an empty board — that would wipe the set and re-light /
  // un-dismiss on the next restart).
  useEffect(() => {
    const rows = board ?? []
    const s = getAlertsSeen()
    const ps = pruneSeenIds(s, rows)
    if (ps.length !== s.length) {
      setAlertsSeen(ps)
      setSeen(new Set(ps))
    }
    const d = getDismissedCrossings()
    const pd = pruneDismissedKeys(d, rows)
    if (pd.length !== d.length) {
      setDismissedCrossings(pd)
      setDismissed(new Set(pd))
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
    // Mark read: opening the panel marks the currently-shown EVENTS seen (badge clears; items stay).
    const ids = feed.items.filter((i) => i.kind === 'event').map((i) => i.ipo_id)
    if (ids.length) {
      const next = new Set([...seen, ...ids])
      setSeen(next)
      setAlertsSeen([...next])
    }
  }

  const clearEvents = (e: MouseEvent) => {
    e.stopPropagation()
    // Dismiss: remove every currently-shown event (durable, per-crossing). Conditions are untouched.
    const keys = feed.items.flatMap((i) => (i.kind === 'event' ? [i.key] : []))
    if (!keys.length) return
    const next = new Set([...dismissed, ...keys])
    setDismissed(next)
    setDismissedCrossings([...next])
  }

  const hasEvents = feed.items.some((i) => i.kind === 'event')

  return (
    <div className="alertwrap" ref={wrap}>
      <button className="alertbtn" onClick={toggle} title="APPLY signals & app status">
        <svg viewBox="0 0 24 24">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {feed.flag ? (
          <span className={`badge flag ${feed.flag}`}>!</span>
        ) : feed.badge > 0 ? (
          <span className="badge">{feed.badge}</span>
        ) : null}
      </button>
      {open && (
        <div className="alertpanel">
          <div className="ahrow">
            <span className="ah">Alerts</span>
            {hasEvents && (
              <button className="ah-clear" onClick={clearEvents} title="Dismiss all alerts">
                Clear
              </button>
            )}
          </div>
          {feed.items.length ? (
            feed.items.map((item) =>
              item.kind === 'condition' ? (
                <div className={`alertitem condition ${item.severity}`} key={item.key}>
                  <span className="adot" style={{ background: dotColor(item) }} />
                  <div>
                    <div className="an">{item.title}</div>
                    <div className="am">{item.detail}</div>
                  </div>
                </div>
              ) : (
                <div
                  className="alertitem event"
                  key={item.key}
                  onClick={() => {
                    setOpen(false)
                    onOpenIpo(item.ipo_id)
                  }}
                >
                  <span className="adot" style={{ background: dotColor(item) }} />
                  <div>
                    <div className="an">
                      {item.name}{' '}
                      {item.probability != null && (
                        <span style={{ color: 'var(--apply)', fontFamily: 'Fira Code' }}>
                          {Math.round(item.probability * 100)}%
                        </span>
                      )}
                    </div>
                    <div className="am">
                      crossed into APPLY · <span className="mono">{fmtDate(item.asof)}</span>
                    </div>
                  </div>
                </div>
              ),
            )
          ) : (
            <div className="alert-empty">You're all caught up.</div>
          )}
        </div>
      )}
    </div>
  )
}
