import { useEffect } from 'react'
import { useTransitions } from './api/hooks'
import type { VerdictTransition } from './api/types'
import {
  getNotifications,
  getNotifiedCrossings,
  isNotifSeeded,
  markNotifSeeded,
  setNotifiedCrossings,
} from './state/prefs'

const isDesktop = (): boolean =>
  typeof window !== 'undefined' && !!(window as { ipoDesktop?: unknown }).ipoDesktop

const key = (ipoId: string, asof: string): string => `${ipoId}@${asof}`

// Quiet hours: 22:00–08:00 IST. During quiet hours we defer (don't fire, don't advance the
// seen-frontier) so pending alerts surface once quiet hours end, rather than being dropped.
function inQuietHours(): boolean {
  const hour =
    Number(
      new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        hour12: false,
      }).format(new Date()),
    ) % 24
  return hour >= 22 || hour < 8
}

function fire(t: VerdictTransition): void {
  const pct = t.probability != null ? ` · ${Math.round(t.probability * 100)}%` : ''
  if (t.crossed_into_apply) {
    new Notification(`APPLY — ${t.name}`, {
      body: `Crossed into APPLY${pct}. Advisory only — no orders placed.`,
    })
  } else {
    new Notification(`${t.name} → ${t.to_verdict}`, {
      body: `Verdict changed${pct}. Advisory only — no orders placed.`,
    })
  }
}

// Native OS notifications for verdict transitions in the durable log, honoring the user's four
// (persisted) notification preferences. Desktop shell only — never the browser preview. On first
// ever run it adopts the existing log silently (no backfill spam); enabling a category later
// notifies only about FUTURE transitions, never replays history.
export function useCrossingNotifications(): void {
  const { data } = useTransitions()

  useEffect(() => {
    if (!isDesktop() || typeof Notification === 'undefined') return
    if (Notification.permission === 'default') void Notification.requestPermission()
  }, [])

  useEffect(() => {
    if (!isDesktop() || typeof Notification === 'undefined') return
    const all = data ?? []
    if (!all.length) return
    const allKeys = all.map((t) => key(t.ipo_id, t.asof))

    // First run: adopt the whole existing log silently so only genuinely new transitions notify.
    if (!isNotifSeeded()) {
      setNotifiedCrossings(allKeys)
      markNotifSeeded()
      return
    }

    const prefs = getNotifications()
    const known = new Set(getNotifiedCrossings())

    // Master switch off, or neither category enabled: advance the seen-frontier and fire nothing.
    if (!prefs.native || (!prefs.applyCrossing && !prefs.anyChange)) {
      setNotifiedCrossings(allKeys)
      return
    }

    // APPLY crossings are governed by `applyCrossing`; every other verdict change by `anyChange`.
    const candidates = all.filter((t) =>
      t.crossed_into_apply ? prefs.applyCrossing : prefs.anyChange,
    )
    const fresh = candidates.filter((c) => !known.has(key(c.ipo_id, c.asof)))

    // Quiet hours: defer — leave the frontier untouched so these fire once quiet hours end.
    if (fresh.length && prefs.quiet && inQuietHours()) return

    if (fresh.length && Notification.permission === 'granted') {
      for (const c of fresh) fire(c)
    }
    setNotifiedCrossings(allKeys) // advance the seen-frontier to every observed transition
  }, [data])
}
