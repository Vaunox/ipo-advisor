import { useEffect, useState } from 'react'
import { IconClock } from './Icons'

// Live IST clock, 12-hour, `h:mm AM/PM` (no seconds) — computed in Asia/Kolkata regardless of the
// machine timezone. The visible "IST" label is dropped as redundant clutter (the whole app is IST);
// the time shown is still IST, and the tooltip still names the zone. (v3 V3-13)
const istTime = (): string =>
  new Date().toLocaleTimeString('en-US', {
    timeZone: 'Asia/Kolkata',
    hour12: true,
    hour: 'numeric',
    minute: '2-digit',
  })

// ms from now to the next minute boundary — so the clock re-renders once a minute, not every second
// (seconds aren't shown, so a per-second tick would be needless churn).
const msToNextMinute = (): number => 60_000 - (Date.now() % 60_000)

export function Clock() {
  const [t, setT] = useState(istTime)
  useEffect(() => {
    let id = 0
    const tick = () => {
      setT(istTime())
      id = window.setTimeout(tick, msToNextMinute())
    }
    id = window.setTimeout(tick, msToNextMinute())
    return () => window.clearTimeout(id)
  }, [])
  return (
    <div className="clock" title="Current time — India Standard Time">
      <IconClock />
      <span className="t">{t}</span>
    </div>
  )
}
