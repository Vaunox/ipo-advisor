import { useEffect, useState } from 'react'
import { IconClock } from './Icons'

// Live IST clock, 12-hour — computed in Asia/Kolkata regardless of the machine timezone.
const istTime = (): string =>
  new Date().toLocaleTimeString('en-US', {
    timeZone: 'Asia/Kolkata',
    hour12: true,
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
  })

export function Clock() {
  const [t, setT] = useState(istTime)
  useEffect(() => {
    const id = window.setInterval(() => setT(istTime()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return (
    <div className="clock" title="Current time — India Standard Time">
      <IconClock />
      <span className="t">{t}</span> <b>IST</b>
    </div>
  )
}
