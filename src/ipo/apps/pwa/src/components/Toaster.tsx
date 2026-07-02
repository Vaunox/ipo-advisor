import { useEffect, useState } from 'react'
import { type ToastMsg, subscribeToasts } from '../toast'

// Renders transient toasts from the toast bus; each auto-dismisses after ~2.4s.
export function Toaster() {
  const [items, setItems] = useState<ToastMsg[]>([])
  useEffect(
    () =>
      subscribeToasts((t) => {
        setItems((cur) => [...cur, t])
        window.setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== t.id)), 2400)
      }),
    [],
  )
  if (!items.length) return null
  return (
    <div className="toaster">
      {items.map((t) => (
        <div className="toast" key={t.id}>
          <svg viewBox="0 0 24 24">
            <path d="M20 6 9 17l-5-5" />
          </svg>
          {t.text}
        </div>
      ))}
    </div>
  )
}
