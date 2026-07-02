import { useEffect } from 'react'
import { useTransitions } from './api/hooks'
import {
  getNotifiedCrossings,
  isNotifSeeded,
  markNotifSeeded,
  setNotifiedCrossings,
} from './state/prefs'

const isDesktop = (): boolean =>
  typeof window !== 'undefined' && !!(window as { ipoDesktop?: unknown }).ipoDesktop

const key = (ipoId: string, asof: string): string => `${ipoId}@${asof}`

// Fire a native OS notification when a *new* APPLY crossing lands in the durable transition log.
// Gated to the desktop shell (never the browser preview). On first ever run it adopts the existing
// crossings silently — no backfill spam — so only genuinely new crossings toast thereafter.
export function useCrossingNotifications(): void {
  const { data } = useTransitions()

  useEffect(() => {
    if (!isDesktop() || typeof Notification === 'undefined') return
    if (Notification.permission === 'default') void Notification.requestPermission()
  }, [])

  useEffect(() => {
    if (!isDesktop() || typeof Notification === 'undefined') return
    const crossings = (data ?? []).filter((t) => t.crossed_into_apply)
    if (!crossings.length) return

    const allKeys = crossings.map((c) => key(c.ipo_id, c.asof))
    if (!isNotifSeeded()) {
      setNotifiedCrossings(allKeys) // adopt history silently on first run
      markNotifSeeded()
      return
    }

    const known = new Set(getNotifiedCrossings())
    const fresh = crossings.filter((c) => !known.has(key(c.ipo_id, c.asof)))
    if (!fresh.length) return

    if (Notification.permission === 'granted') {
      for (const c of fresh) {
        const pct = c.probability != null ? ` · ${Math.round(c.probability * 100)}%` : ''
        new Notification(`APPLY — ${c.name}`, {
          body: `Crossed into APPLY${pct}. Advisory only — no orders placed.`,
        })
      }
    }
    setNotifiedCrossings([...known, ...fresh.map((c) => key(c.ipo_id, c.asof))])
  }, [data])
}
