import { useState } from 'react'
import { IconMoon, IconSun } from './Icons'
import { getThemeMode, resolveTheme, setThemeMode } from '../state/prefs'

// Animated light/dark toggle. The label names what a click does (comp behaviour).
export function ThemeToggle() {
  const [resolved, setResolved] = useState(() => resolveTheme(getThemeMode()))
  const toggle = () => {
    const next = resolved === 'light' ? 'dark' : 'light'
    setThemeMode(next)
    setResolved(next)
  }
  const light = resolved === 'light'
  return (
    <button className="tgl" onClick={toggle} aria-label="Toggle light or dark theme">
      {light ? <IconSun /> : <IconMoon />}
      <span>{light ? 'Dark' : 'Light'}</span>
    </button>
  )
}
