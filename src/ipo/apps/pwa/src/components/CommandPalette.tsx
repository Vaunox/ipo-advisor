import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { IPOListRow } from '../api/types'
import type { View } from '../nav'

interface Item {
  type: string
  name: string
  detail: string
  act: () => void
}

export function CommandPalette({
  board,
  onOpenIpo,
  onNav,
  onClose,
}: {
  board: IPOListRow[]
  onOpenIpo: (id: string) => void
  onNav: (v: View) => void
  onClose: () => void
}) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  useLayoutEffect(() => {
    inputRef.current?.focus()
  }, [])

  const ql = q.toLowerCase()
  const ipoItems: Item[] = board
    .filter((r) => r.name.toLowerCase().includes(ql))
    .slice(0, 8)
    .map((r) => ({
      type: r.verdict.replace('_SIGNAL', ''),
      name: r.name,
      detail: r.probability != null ? `${Math.round(r.probability * 100)}%` : r.verdict.replace('_SIGNAL', ''),
      act: () => {
        onClose()
        onOpenIpo(r.ipo_id)
      },
    }))
  const navItems: Item[] = (
    [
      ['Live signals', 'live'],
      ['Upcoming', 'upcoming'],
      ['History', 'history'],
      ['Settings', 'settings'],
    ] as [string, View][]
  )
    .filter(([n]) => n.toLowerCase().includes(ql))
    .map(([n, v]) => ({
      type: 'GO',
      name: n,
      detail: 'section',
      act: () => {
        onClose()
        onNav(v)
      },
    }))
  const items = [...ipoItems, ...navItems]

  useEffect(() => {
    setSel(0)
  }, [q])

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSel((s) => Math.min(s + 1, items.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSel((s) => Math.max(s - 1, 0))
    } else if (e.key === 'Enter') {
      items[sel]?.act()
    } else if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <div
      className="overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="palette">
        <input
          ref={inputRef}
          placeholder="Search IPOs or jump to a section…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="pal-list">
          {items.length ? (
            items.map((it, i) => (
              <div
                key={i}
                className={i === sel ? 'pal-item sel' : 'pal-item'}
                onMouseEnter={() => setSel(i)}
                onClick={it.act}
              >
                <span className="pt">{it.type}</span>
                <span className="pn">{it.name}</span>
                <span className="pd">{it.detail}</span>
              </div>
            ))
          ) : (
            <div className="pal-empty">No matches.</div>
          )}
        </div>
      </div>
    </div>
  )
}
