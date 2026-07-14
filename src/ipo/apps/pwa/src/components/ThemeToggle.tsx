import { IconMoon, IconSun } from './Icons'
import { resolveTheme, setThemeMode, useThemeMode } from '../state/prefs'

// Animated light/dark toggle. The label names what a click does (comp behaviour). Reads the theme
// reactively from the shared store (v3 BUG 3) — no private cache, so it stays in sync when the
// Settings control or the `t` shortcut changes the theme (previously the first click after such a
// change was swallowed).
export function ThemeToggle() {
  const resolved = resolveTheme(useThemeMode())
  const toggle = () => setThemeMode(resolved === 'light' ? 'dark' : 'light')
  const light = resolved === 'light'
  return (
    <button className="tgl" onClick={toggle} aria-label="Toggle light or dark theme">
      {light ? <IconSun /> : <IconMoon />}
      <span>{light ? 'Dark' : 'Light'}</span>
    </button>
  )
}
